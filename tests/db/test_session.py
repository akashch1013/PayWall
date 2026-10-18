import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall.db.session import run_tx
from paywall.errors import ErrorCode, PayWallError

Sessions = async_sessionmaker[AsyncSession]


async def _raise_sqlstate(session: AsyncSession, sqlstate: str) -> None:
    # A real server-side error carrying the SQLSTATE, exactly as a real deadlock would arrive.
    await session.execute(
        text(f"DO $$ BEGIN RAISE EXCEPTION 'simulated' USING ERRCODE = '{sqlstate}'; END $$")
    )


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
async def test_retries_deadlocks_and_serialization_failures(
    sessions: Sessions, sqlstate: str
) -> None:
    calls = 0

    async def fn(session: AsyncSession) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            await _raise_sqlstate(session, sqlstate)
        return "ok"

    assert await run_tx(sessions, fn, max_attempts=3) == "ok"
    assert calls == 2


async def test_gives_up_after_max_attempts(sessions: Sessions) -> None:
    calls = 0

    async def fn(session: AsyncSession) -> None:
        nonlocal calls
        calls += 1
        await _raise_sqlstate(session, "40P01")

    with pytest.raises(DBAPIError, match="simulated"):
        await run_tx(sessions, fn, max_attempts=3)
    assert calls == 3


async def test_does_not_retry_other_database_errors(sessions: Sessions) -> None:
    calls = 0

    async def fn(session: AsyncSession) -> None:
        nonlocal calls
        calls += 1
        await _raise_sqlstate(session, "23505")

    with pytest.raises(DBAPIError):
        await run_tx(sessions, fn, max_attempts=3)
    assert calls == 1


async def test_business_error_rolls_back_everything(sessions: Sessions) -> None:
    user = uuid.uuid4().hex

    async def fn(session: AsyncSession) -> None:
        await session.execute(
            text(
                "INSERT INTO accounts (kind, external_user_id, currency, balance) "
                "VALUES ('USER_WALLET', :user, 'INR', 0)"
            ),
            {"user": user},
        )
        raise PayWallError(ErrorCode.INSUFFICIENT_FUNDS, "no money")

    with pytest.raises(PayWallError):
        await run_tx(sessions, fn, max_attempts=3)

    async with sessions() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM accounts WHERE external_user_id = :user"),
                {"user": user},
            )
            == 0
        )
