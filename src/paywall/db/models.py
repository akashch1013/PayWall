"""SQLAlchemy table definitions.

Tables carry no schema name: the engine's ``search_path`` points at ``PAYWALL_DB_SCHEMA``.
The migrations in ``db/migrations`` are the source of truth for the database; a test checks that
these models and the migrated schema agree.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AccountKind(StrEnum):
    USER_WALLET = "USER_WALLET"
    GATEWAY_CLEARING = "GATEWAY_CLEARING"
    PROMO_EXPENSE = "PROMO_EXPENSE"
    APP_REVENUE = "APP_REVENUE"
    ADJUSTMENTS = "ADJUSTMENTS"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"


class EntryType(StrEnum):
    TOPUP = "TOPUP"
    PROMO = "PROMO"
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        str: Text,
    }


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(_in("kind", AccountKind), name="accounts_kind"),
        CheckConstraint(_in("status", AccountStatus), name="accounts_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="accounts_currency"),
        # Only user wallets cache a balance; system accounts are summed from postings on demand.
        CheckConstraint(
            "(kind = 'USER_WALLET') = (balance IS NOT NULL)", name="accounts_balance_cached"
        ),
        CheckConstraint(
            "(kind = 'USER_WALLET') = (external_user_id IS NOT NULL)", name="accounts_wallet_owner"
        ),
        CheckConstraint("balance >= 0", name="accounts_balance_non_negative"),
        Index(
            "accounts_one_wallet_per_user",
            "external_user_id",
            "currency",
            unique=True,
            postgresql_where=text("kind = 'USER_WALLET'"),
        ),
        Index(
            "accounts_one_system_account",
            "kind",
            "gateway",
            "currency",
            unique=True,
            postgresql_where=text("kind <> 'USER_WALLET'"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    kind: Mapped[str]
    external_user_id: Mapped[str | None]
    gateway: Mapped[str | None]
    currency: Mapped[str] = mapped_column(CHAR(3))
    balance: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(server_default=AccountStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint(_in("type", EntryType), name="journal_entries_type"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="journal_entries_currency"),
        # An entry can be reversed at most once.
        Index(
            "journal_entries_one_reversal",
            "reverses_entry_id",
            unique=True,
            postgresql_where=text("type = 'REVERSAL'"),
        ),
        Index("journal_entries_reverses_entry_id", "reverses_entry_id"),
        Index("journal_entries_reference", "reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    type: Mapped[str]
    reference: Mapped[str | None]
    currency: Mapped[str] = mapped_column(CHAR(3))
    # "metadata" is reserved on declarative classes, hence the trailing underscore.
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", server_default=text("'{}'"))
    actor: Mapped[str]
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("journal_entries.id"))
    # Ties the entry to the API request (and its log lines) that created it.
    request_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="postings_amount_non_zero"),
        # Serves history pagination (newest first) and per-account sums.
        Index("postings_account_id_id", "account_id", text("id DESC")),
        Index("postings_entry_id", "entry_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journal_entries.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("idempotency_keys_expires_at", "expires_at"),)

    scope: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    response_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "outbox_events_pending",
            "next_attempt_at",
            postgresql_where=text("delivered_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_type: Mapped[str]
    payload: Mapped[dict[str, Any]]
    request_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    delivered_at: Mapped[datetime | None]
    last_error: Mapped[str | None]


class ApiKeyRecord(Base):
    """Standalone-server API keys. Only the SHA-256 of the key is stored, never the key."""

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "cardinality(scopes) > 0 "
            "AND scopes <@ ARRAY['wallet:read', 'wallet:write', 'admin']::text[]",
            name="api_keys_scopes",
        ),
        UniqueConstraint("prefix", name="api_keys_prefix_key"),
        UniqueConstraint("key_hash", name="api_keys_key_hash_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str]
    prefix: Mapped[str]
    key_hash: Mapped[str] = mapped_column(CHAR(64))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]
