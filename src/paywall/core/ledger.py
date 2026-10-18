"""The double-entry ledger. ``post_entry`` is the only code that writes journal entries.

Sign convention: a positive posting increases that account's balance, a negative one decreases it.
Every entry sums to zero, so the sum of all postings in the system is always zero.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from paywall.core import outbox
from paywall.db.models import Account, AccountKind, EntryType, JournalEntry, Posting
from paywall.observability import request_id_var


@dataclass(frozen=True, slots=True)
class PostedEntry:
    entry_id: uuid.UUID
    created_at: datetime
    # New cached balance of each user wallet the entry touched.
    wallet_balances: dict[uuid.UUID, int]


async def system_account(
    session: AsyncSession, kind: AccountKind, currency: str, gateway: str | None = None
) -> uuid.UUID:
    """Return the id of the system account for (kind, gateway, currency), creating it if needed.

    Call this before locking any wallet: a concurrent first-time insert makes this wait for the
    other transaction, and waiting while holding a wallet lock could deadlock.
    """
    query = select(Account.id).where(
        Account.kind == kind,
        Account.gateway.is_not_distinct_from(gateway),
        Account.currency == currency,
    )
    account_id = await session.scalar(query)
    if account_id is not None:
        return account_id
    await session.execute(
        pg_insert(Account)
        .values(kind=kind, gateway=gateway, currency=currency)
        .on_conflict_do_nothing()
    )
    # Exactly one row now: ours, or one a concurrent transaction committed first.
    return (await session.execute(query)).scalar_one()


async def lock_wallets(
    session: AsyncSession, account_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Account]:
    """``SELECT … FOR UPDATE`` the user wallets among ``account_ids``.

    Rows are locked in id order. Every transaction locking several wallets does so in the same
    order, so two transactions can never each hold a wallet the other is waiting for.
    """
    rows = await session.scalars(
        select(Account)
        .where(Account.id.in_(set(account_ids)), Account.kind == AccountKind.USER_WALLET)
        .order_by(Account.id)
        .with_for_update()
        # Reload rows already in the session so balances reflect what we read under the lock.
        .execution_options(populate_existing=True)
    )
    return {account.id: account for account in rows}


async def post_entry(
    session: AsyncSession,
    *,
    type: EntryType,
    currency: str,
    postings: Sequence[tuple[uuid.UUID, int]],
    actor: str,
    reference: str | None = None,
    metadata: dict[str, Any] | None = None,
    reverses_entry_id: uuid.UUID | None = None,
) -> PostedEntry:
    """Write one balanced journal entry and update the cached balances of the wallets it touches.

    The caller must already hold the locks of those wallets and have checked its business rules
    (sufficient funds, frozen status). The database CHECK and triggers are the last defense.
    """
    if len(postings) < 2:
        raise ValueError("an entry needs at least two postings")
    if any(amount == 0 for _, amount in postings):
        raise ValueError("posting amounts must be non-zero")
    if sum(amount for _, amount in postings) != 0:
        raise ValueError("posting amounts must sum to zero")
    deltas = dict(postings)
    if len(deltas) != len(postings):
        raise ValueError("an account may appear only once per entry")

    accounts = {
        account.id: account
        for account in await session.scalars(select(Account).where(Account.id.in_(deltas)))
    }
    if unknown := deltas.keys() - accounts.keys():
        raise ValueError(f"unknown account(s): {sorted(map(str, unknown))}")
    if any(account.currency != currency for account in accounts.values()):
        raise ValueError(f"all accounts in an entry must use its currency {currency}")

    entry_id, created_at = (
        await session.execute(
            insert(JournalEntry)
            .values(
                type=type,
                currency=currency,
                reference=reference,
                metadata_=metadata or {},
                actor=actor,
                reverses_entry_id=reverses_entry_id,
                request_id=request_id_var.get(),
            )
            .returning(JournalEntry.id, JournalEntry.created_at)
        )
    ).one()
    await session.execute(
        insert(Posting),
        [{"entry_id": entry_id, "account_id": a, "amount": amount} for a, amount in postings],
    )

    balances: dict[uuid.UUID, int] = {}
    for account_id, delta in deltas.items():
        account = accounts[account_id]
        if account.kind != AccountKind.USER_WALLET:
            continue
        # Never NULL: user wallets always cache a balance (accounts_balance_cached CHECK).
        result = await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(balance=Account.balance + delta, updated_at=func.now())
            .returning(Account.balance)
            # The in-memory Account (if any) is stale now; don't try to sync it.
            .execution_options(synchronize_session=False)
        )
        balance = cast(int, result.scalar_one())
        balances[account_id] = balance
        await outbox.emit(
            session,
            "wallet.credited" if delta > 0 else "wallet.debited",
            {
                "entry_id": str(entry_id),
                "entry_type": type.value,
                "user_id": account.external_user_id,
                "amount": delta,
                "currency": currency,
                "balance_after": balance,
                "reference": reference,
            },
        )

    return PostedEntry(entry_id=entry_id, created_at=created_at, wallet_balances=balances)
