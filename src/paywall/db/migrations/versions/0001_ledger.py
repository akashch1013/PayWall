"""Ledger tables, idempotency keys, outbox, and the triggers that protect the ledger.

Revision ID: 0001
Revises:
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None

NOW = sa.func.now()


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.func.gen_random_uuid())


def _created_at() -> sa.Column[Any]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW)


def upgrade() -> None:
    op.create_table(
        "accounts",
        _uuid_pk(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("external_user_id", sa.Text()),
        sa.Column("gateway", sa.Text()),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("balance", sa.BigInteger()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "kind IN ('USER_WALLET', 'GATEWAY_CLEARING', 'PROMO_EXPENSE', 'APP_REVENUE', "
            "'ADJUSTMENTS')",
            name="accounts_kind",
        ),
        sa.CheckConstraint("status IN ('active', 'frozen')", name="accounts_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="accounts_currency"),
        sa.CheckConstraint(
            "(kind = 'USER_WALLET') = (balance IS NOT NULL)", name="accounts_balance_cached"
        ),
        sa.CheckConstraint(
            "(kind = 'USER_WALLET') = (external_user_id IS NOT NULL)", name="accounts_wallet_owner"
        ),
        sa.CheckConstraint("balance >= 0", name="accounts_balance_non_negative"),
    )
    op.create_index(
        "accounts_one_wallet_per_user",
        "accounts",
        ["external_user_id", "currency"],
        unique=True,
        postgresql_where=sa.text("kind = 'USER_WALLET'"),
    )
    op.create_index(
        "accounts_one_system_account",
        "accounts",
        ["kind", "gateway", "currency"],
        unique=True,
        postgresql_where=sa.text("kind <> 'USER_WALLET'"),
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "journal_entries",
        _uuid_pk(),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text()),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reverses_entry_id", sa.Uuid(), sa.ForeignKey("journal_entries.id")),
        _created_at(),
        sa.CheckConstraint(
            "type IN ('TOPUP', 'PROMO', 'DEBIT', 'REFUND', 'TRANSFER', 'ADJUSTMENT', 'REVERSAL')",
            name="journal_entries_type",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="journal_entries_currency"),
    )
    op.create_index(
        "journal_entries_one_reversal",
        "journal_entries",
        ["reverses_entry_id"],
        unique=True,
        postgresql_where=sa.text("type = 'REVERSAL'"),
    )
    op.create_index("journal_entries_reverses_entry_id", "journal_entries", ["reverses_entry_id"])
    op.create_index("journal_entries_reference", "journal_entries", ["reference"])

    op.create_table(
        "postings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("entry_id", sa.Uuid(), sa.ForeignKey("journal_entries.id"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        _created_at(),
        sa.CheckConstraint("amount <> 0", name="postings_amount_non_zero"),
    )
    op.create_index("postings_account_id_id", "postings", ["account_id", sa.text("id DESC")])
    op.create_index("postings_entry_id", "postings", ["entry_id"])

    op.create_table(
        "idempotency_keys",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index(
        "outbox_events_pending",
        "outbox_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("delivered_at IS NULL"),
    )

    # The ledger is append-only, even for a buggy release or a hand-typed psql session.
    # Corrections are new entries (reversals, adjustments), never edits.
    op.execute("""
        CREATE FUNCTION forbid_ledger_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END $$
    """)
    for table in ("journal_entries", "postings"):
        op.execute(f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation()
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION forbid_ledger_mutation()
        """)

    # Checked at COMMIT (deferred), once all postings of an entry exist: an entry needs at least
    # two postings and must sum to zero. Fires for entries too, so an entry with no postings fails.
    # SET search_path FROM CURRENT pins the function to this schema regardless of the caller's path.
    op.execute("""
        CREATE FUNCTION check_entry_balanced() RETURNS trigger LANGUAGE plpgsql
        SET search_path FROM CURRENT AS $$
        DECLARE
            target uuid;
            n int;
            total numeric;
        BEGIN
            IF TG_TABLE_NAME = 'postings' THEN
                target := NEW.entry_id;
            ELSE
                target := NEW.id;
            END IF;
            SELECT count(*), coalesce(sum(amount), 0) INTO n, total
                FROM postings WHERE entry_id = target;
            IF n < 2 OR total <> 0 THEN
                RAISE EXCEPTION 'journal entry % is unbalanced: % postings summing to %',
                    target, n, total USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in ("journal_entries", "postings"):
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER {table}_balanced AFTER INSERT ON {table}
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION check_entry_balanced()
        """)


def downgrade() -> None:
    for table in ("outbox_events", "idempotency_keys", "postings", "journal_entries", "accounts"):
        op.drop_table(table)
    op.execute("DROP FUNCTION check_entry_balanced()")
    op.execute("DROP FUNCTION forbid_ledger_mutation()")
