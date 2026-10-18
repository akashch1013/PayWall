"""User wallets: lookup, lazy creation, locking, history and freezing."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from paywall.core.results import Transaction, TransactionPage, Wallet
from paywall.db.models import Account, AccountKind, AccountStatus, EntryType, JournalEntry, Posting
from paywall.errors import ErrorCode, PayWallError

MAX_PAGE_SIZE = 100


def _select_wallet(user_id: str, currency: str) -> Select[Account]:
    return select(Account).where(
        Account.kind == AccountKind.USER_WALLET,
        Account.external_user_id == user_id,
        Account.currency == currency,
    )


async def get_or_create_wallet(session: AsyncSession, user_id: str, currency: str) -> Wallet:
    account = await session.scalar(_select_wallet(user_id, currency))
    if account is None:
        # Two first requests for the same user may race here; the unique index lets one insert
        # win and the other do nothing, and both then read the same row.
        await session.execute(
            insert(Account)
            .values(
                kind=AccountKind.USER_WALLET,
                external_user_id=user_id,
                currency=currency,
                balance=0,
            )
            .on_conflict_do_nothing()
        )
        account = (await session.execute(_select_wallet(user_id, currency))).scalar_one()
    return Wallet.from_account(account)


async def lock_wallet(session: AsyncSession, user_id: str, currency: str) -> Account:
    """``SELECT … FOR UPDATE`` the user's wallet; it must already exist."""
    account = await session.scalar(
        _select_wallet(user_id, currency)
        .with_for_update()
        # The row may already be in the session from an unlocked read; reload it so the
        # balance we check is the one read under the lock.
        .execution_options(populate_existing=True)
    )
    if account is None:
        raise PayWallError(ErrorCode.WALLET_NOT_FOUND, f"No {currency} wallet for user {user_id}")
    return account


async def set_status(
    session: AsyncSession, *, user_id: str, currency: str, status: AccountStatus
) -> Wallet:
    account = await lock_wallet(session, user_id, currency)
    await session.execute(
        update(Account)
        .where(Account.id == account.id)
        .values(status=status)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(account)
    return Wallet.from_account(account)


async def history(
    session: AsyncSession,
    *,
    user_id: str,
    currency: str,
    cursor: int | None = None,
    limit: int = 50,
    types: Collection[EntryType] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> TransactionPage:
    """Newest-first page of the wallet's postings. ``since`` is inclusive, ``until`` exclusive."""
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise PayWallError(
            ErrorCode.VALIDATION_ERROR, f"limit must be between 1 and {MAX_PAGE_SIZE}"
        )
    account_id = await session.scalar(
        _select_wallet(user_id, currency).with_only_columns(Account.id)
    )
    if account_id is None:
        return TransactionPage(items=[], next_cursor=None)

    query = (
        select(Posting, JournalEntry)
        .join(JournalEntry, Posting.entry_id == JournalEntry.id)
        .where(Posting.account_id == account_id)
        .order_by(Posting.id.desc())
        # One extra row tells us whether another page exists.
        .limit(limit + 1)
    )
    if cursor is not None:
        query = query.where(Posting.id < cursor)
    if types is not None:
        query = query.where(JournalEntry.type.in_(types))
    if since is not None:
        query = query.where(Posting.created_at >= since)
    if until is not None:
        query = query.where(Posting.created_at < until)

    rows = (await session.execute(query)).all()
    items = [
        Transaction(
            id=posting.id,
            entry_id=entry.id,
            type=EntryType(entry.type),
            amount=posting.amount,
            reference=entry.reference,
            metadata=entry.metadata_,
            created_at=posting.created_at,
        )
        for posting, entry in rows[:limit]
    ]
    next_cursor = items[-1].id if len(rows) > limit else None
    return TransactionPage(items=items, next_cursor=next_cursor)
