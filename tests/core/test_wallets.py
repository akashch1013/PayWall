import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall.core import payments, wallets
from paywall.core.results import Wallet
from paywall.db.models import AccountStatus, EntryType
from paywall.errors import ErrorCode, PayWallError

Sessions = async_sessionmaker[AsyncSession]


async def test_wallet_is_created_once_even_under_concurrency(
    sessions: Sessions, user_id: str
) -> None:
    async def get() -> Wallet:
        async with sessions() as session, session.begin():
            return await wallets.get_or_create_wallet(session, user_id, "INR")

    results = await asyncio.gather(*(get() for _ in range(10)))

    assert len({w.id for w in results}) == 1
    assert results[0].balance == 0
    assert results[0].status is AccountStatus.ACTIVE


async def test_freeze_and_unfreeze(sessions: Sessions, user_id: str) -> None:
    async with sessions() as session, session.begin():
        await wallets.get_or_create_wallet(session, user_id, "INR")
        frozen = await wallets.set_status(
            session, user_id=user_id, currency="INR", status=AccountStatus.FROZEN
        )
        active = await wallets.set_status(
            session, user_id=user_id, currency="INR", status=AccountStatus.ACTIVE
        )

    assert (frozen.status, active.status) == (AccountStatus.FROZEN, AccountStatus.ACTIVE)


async def test_freezing_unknown_wallet_is_not_found(sessions: Sessions, user_id: str) -> None:
    async with sessions() as session, session.begin():
        with pytest.raises(PayWallError) as error:
            await wallets.set_status(
                session, user_id=user_id, currency="INR", status=AccountStatus.FROZEN
            )

    assert error.value.code is ErrorCode.WALLET_NOT_FOUND


async def test_history_pages_newest_first(sessions: Sessions, user_id: str) -> None:
    async with sessions() as session, session.begin():
        await payments.adjust(
            session, user_id=user_id, currency="INR", amount=1_000, reason="seed", actor="t"
        )
        for n in range(4):
            await payments.debit(
                session,
                user_id=user_id,
                currency="INR",
                amount=10 + n,
                reference=f"order_{n}",
                actor="t",
                metadata={"n": n},
            )

    async with sessions() as session:
        first = await wallets.history(session, user_id=user_id, currency="INR", limit=3)
        second = await wallets.history(
            session, user_id=user_id, currency="INR", limit=3, cursor=first.next_cursor
        )

    assert [t.amount for t in first.items] == [-13, -12, -11]
    assert first.items[0].reference == "order_3"
    assert first.items[0].metadata == {"n": 3}
    assert [t.amount for t in second.items] == [-10, 1_000]
    assert second.next_cursor is None


async def test_history_filters_by_type_and_time(sessions: Sessions, user_id: str) -> None:
    async with sessions() as session, session.begin():
        await payments.adjust(
            session, user_id=user_id, currency="INR", amount=1_000, reason="seed", actor="t"
        )
        await payments.debit(
            session, user_id=user_id, currency="INR", amount=5, reference="o", actor="t"
        )

    now = datetime.now(UTC)
    async with sessions() as session:
        debits = await wallets.history(
            session, user_id=user_id, currency="INR", types=[EntryType.DEBIT]
        )
        future = await wallets.history(
            session, user_id=user_id, currency="INR", since=now + timedelta(minutes=1)
        )
        past = await wallets.history(
            session, user_id=user_id, currency="INR", until=now - timedelta(minutes=1)
        )

    async with sessions() as session:
        none = await wallets.history(session, user_id=user_id, currency="INR", types=[])

    assert [t.type for t in debits.items] == [EntryType.DEBIT]
    assert future.items == past.items == none.items == []


async def test_history_of_unknown_user_is_empty(sessions: Sessions, user_id: str) -> None:
    async with sessions() as session:
        page = await wallets.history(session, user_id=user_id, currency="INR")

    assert page.items == []
    assert page.next_cursor is None


@pytest.mark.parametrize("limit", [0, 101])
async def test_history_rejects_bad_limit(sessions: Sessions, user_id: str, limit: int) -> None:
    async with sessions() as session:
        with pytest.raises(PayWallError) as error:
            await wallets.history(session, user_id=user_id, currency="INR", limit=limit)

    assert error.value.code is ErrorCode.VALIDATION_ERROR
