"""API keys for the standalone server; request ids on ledger entries and outbox events.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.CHAR(64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "cardinality(scopes) > 0 "
            "AND scopes <@ ARRAY['wallet:read', 'wallet:write', 'admin']::text[]",
            name="api_keys_scopes",
        ),
        sa.UniqueConstraint("prefix", name="api_keys_prefix_key"),
        sa.UniqueConstraint("key_hash", name="api_keys_key_hash_key"),
    )
    # Nullable, no default: adding these does not rewrite the (append-only) tables.
    op.add_column("journal_entries", sa.Column("request_id", sa.Text()))
    op.add_column("outbox_events", sa.Column("request_id", sa.Text()))


def downgrade() -> None:
    op.drop_column("outbox_events", "request_id")
    op.drop_column("journal_entries", "request_id")
    op.drop_table("api_keys")
