"""Plain, immutable results returned by core operations (no ORM objects leak out)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self, cast

from paywall.db.models import Account, AccountStatus, EntryType


@dataclass(frozen=True, slots=True)
class Wallet:
    id: uuid.UUID
    user_id: str
    currency: str
    balance: int
    status: AccountStatus
    created_at: datetime

    @classmethod
    def from_account(cls, account: Account) -> Self:
        # Never NULL for user wallets (CHECKs accounts_wallet_owner, accounts_balance_cached).
        return cls(
            id=account.id,
            user_id=cast(str, account.external_user_id),
            currency=account.currency,
            balance=cast(int, account.balance),
            status=AccountStatus(account.status),
            created_at=account.created_at,
        )


@dataclass(frozen=True, slots=True)
class Transaction:
    """One line of a wallet's history: a posting on that wallet plus its entry's details."""

    id: int
    entry_id: uuid.UUID
    type: EntryType
    # Signed change to the wallet balance: positive is money in, negative is money out.
    amount: int
    reference: str | None
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TransactionPage:
    items: list[Transaction]
    # Pass back as ``cursor`` to get the next (older) page; None when there are no more.
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class WalletEntry:
    """A journal entry as seen from the one user wallet it changed."""

    entry_id: uuid.UUID
    type: EntryType
    user_id: str
    # Signed change to the wallet balance, like Transaction.amount.
    amount: int
    currency: str
    balance_after: int
    reference: str | None
    created_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "type": self.type.value,
            "user_id": self.user_id,
            "amount": self.amount,
            "currency": self.currency,
            "balance_after": self.balance_after,
            "reference": self.reference,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(
            entry_id=uuid.UUID(data["entry_id"]),
            type=EntryType(data["type"]),
            user_id=data["user_id"],
            amount=data["amount"],
            currency=data["currency"],
            balance_after=data["balance_after"],
            reference=data["reference"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )
