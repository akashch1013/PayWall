"""Money movements on user wallets: debit, admin adjustment and reversal.

Every function runs inside the caller's transaction and follows the same order: resolve system
accounts, lock wallets, check business rules, then ``post_entry``.
"""

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from paywall.core import wallets
from paywall.core.ledger import PostedEntry, lock_wallets, post_entry, system_account
from paywall.core.results import WalletEntry
from paywall.db.models import (
    Account,
    AccountKind,
    AccountStatus,
    EntryType,
    JournalEntry,
    Posting,
)
from paywall.errors import ErrorCode, PayWallError


def _require_amount(amount: int, *, allow_negative: bool = False) -> None:
    # bool is a subclass of int; True must not mean "1 paisa".
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise PayWallError(ErrorCode.VALIDATION_ERROR, "amount must be an integer (minor units)")
    if amount == 0 or (amount < 0 and not allow_negative):
        qualifier = "non-zero" if allow_negative else "positive"
        raise PayWallError(ErrorCode.VALIDATION_ERROR, f"amount must be {qualifier}")


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise PayWallError(ErrorCode.VALIDATION_ERROR, f"{name} is required")


def _ensure_funds(wallet: Account, delta: int) -> None:
    balance = cast(int, wallet.balance)  # never NULL for user wallets
    if balance + delta < 0:
        raise PayWallError(ErrorCode.INSUFFICIENT_FUNDS, f"Balance {balance} < amount {-delta}")


def _wallet_entry(
    posted: PostedEntry,
    type: EntryType,
    wallet: Account,
    amount: int,
    reference: str | None,
) -> WalletEntry:
    return WalletEntry(
        entry_id=posted.entry_id,
        type=type,
        user_id=cast(str, wallet.external_user_id),
        amount=amount,
        currency=wallet.currency,
        balance_after=posted.wallet_balances[wallet.id],
        reference=reference,
        created_at=posted.created_at,
    )


async def debit(
    session: AsyncSession,
    *,
    user_id: str,
    currency: str,
    amount: int,
    reference: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
) -> WalletEntry:
    """Spend ``amount`` from the user's wallet, paid to the app (APP_REVENUE)."""
    _require_amount(amount)
    _require_text(reference, "reference")
    revenue = await system_account(session, AccountKind.APP_REVENUE, currency)
    wallet = await wallets.lock_wallet(session, user_id, currency)
    if wallet.status == AccountStatus.FROZEN:
        raise PayWallError(ErrorCode.WALLET_FROZEN, f"Wallet of user {user_id} is frozen")
    _ensure_funds(wallet, -amount)

    posted = await post_entry(
        session,
        type=EntryType.DEBIT,
        currency=currency,
        postings=[(wallet.id, -amount), (revenue, amount)],
        actor=actor,
        reference=reference,
        metadata=metadata,
    )
    return _wallet_entry(posted, EntryType.DEBIT, wallet, -amount, reference)


async def adjust(
    session: AsyncSession,
    *,
    user_id: str,
    currency: str,
    amount: int,
    reason: str,
    actor: str,
) -> WalletEntry:
    """Admin correction: credit (amount > 0) or debit (amount < 0) the wallet against ADJUSTMENTS.

    Creates the wallet if needed and works on frozen wallets, because it is an operator action.
    """
    _require_amount(amount, allow_negative=True)
    _require_text(reason, "reason")
    source = await system_account(session, AccountKind.ADJUSTMENTS, currency)
    await wallets.get_or_create_wallet(session, user_id, currency)
    wallet = await wallets.lock_wallet(session, user_id, currency)
    _ensure_funds(wallet, amount)

    posted = await post_entry(
        session,
        type=EntryType.ADJUSTMENT,
        currency=currency,
        postings=[(source, -amount), (wallet.id, amount)],
        actor=actor,
        metadata={"reason": reason},
    )
    return _wallet_entry(posted, EntryType.ADJUSTMENT, wallet, amount, None)


async def reverse(
    session: AsyncSession,
    *,
    entry_id: uuid.UUID,
    reason: str,
    actor: str,
) -> WalletEntry:
    """Post the exact negation of an entry. Each entry can be reversed at most once.

    Allowed on frozen wallets (it undoes an earlier movement), but never drives a wallet negative:
    a credit that was already spent cannot be reversed.
    """
    _require_text(reason, "reason")
    entry = await session.get(JournalEntry, entry_id)
    if entry is None:
        raise PayWallError(ErrorCode.NOT_FOUND, f"Entry {entry_id} not found")
    if entry.type == EntryType.REVERSAL:
        raise PayWallError(ErrorCode.VALIDATION_ERROR, "A reversal cannot itself be reversed")

    postings = (
        await session.execute(
            select(Posting.account_id, Posting.amount)
            .where(Posting.entry_id == entry_id)
            .order_by(Posting.id)
        )
    ).all()
    locked = await lock_wallets(session, [account_id for account_id, _ in postings])
    if len(locked) != 1:
        raise PayWallError(
            ErrorCode.VALIDATION_ERROR, "Only entries that touch exactly one wallet can be reversed"
        )
    # Checked under the wallet lock, so a concurrent reversal of the same entry has either
    # committed (and is seen here) or is waiting behind us.
    already = await session.scalar(
        select(JournalEntry.id).where(
            JournalEntry.reverses_entry_id == entry_id,
            JournalEntry.type == EntryType.REVERSAL,
        )
    )
    if already is not None:
        raise PayWallError(
            ErrorCode.ENTRY_ALREADY_REVERSED, f"Entry {entry_id} was already reversed by {already}"
        )

    [wallet] = locked.values()
    delta = -dict(postings)[wallet.id]
    _ensure_funds(wallet, delta)

    posted = await post_entry(
        session,
        type=EntryType.REVERSAL,
        currency=entry.currency,
        postings=[(account_id, -amount) for account_id, amount in postings],
        actor=actor,
        reference=entry.reference,
        metadata={"reason": reason},
        reverses_entry_id=entry_id,
    )
    return _wallet_entry(posted, EntryType.REVERSAL, wallet, delta, entry.reference)
