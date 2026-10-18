"""The database itself enforces the ledger rules, independently of the Python code."""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from paywall.db.models import Base

Sessions = async_sessionmaker[AsyncSession]


async def _wallet(session: AsyncSession, balance: int = 0) -> uuid.UUID:
    return uuid.UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO accounts (kind, external_user_id, currency, balance) "
                    "VALUES ('USER_WALLET', :user, 'INR', :balance) RETURNING id"
                ),
                {"user": uuid.uuid4().hex, "balance": balance},
            )
        )
    )


async def _entry(session: AsyncSession, *postings: tuple[uuid.UUID, int]) -> uuid.UUID:
    entry_id = uuid.UUID(
        str(
            await session.scalar(
                text(
                    "INSERT INTO journal_entries (type, currency, actor) "
                    "VALUES ('ADJUSTMENT', 'INR', 'test') RETURNING id"
                )
            )
        )
    )
    for account_id, amount in postings:
        await session.execute(
            text("INSERT INTO postings (entry_id, account_id, amount) VALUES (:e, :a, :amt)"),
            {"e": entry_id, "a": account_id, "amt": amount},
        )
    return entry_id


async def test_balanced_entry_commits(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        a, b = await _wallet(session), await _wallet(session)
        entry_id = await _entry(session, (a, -100), (b, 100))

    async with sessions() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM postings WHERE entry_id = :e"), {"e": entry_id}
            )
            == 2
        )


@pytest.mark.parametrize(
    "amounts",
    [
        pytest.param((-100, 99), id="sum-not-zero"),
        pytest.param((100,), id="single-posting"),
        pytest.param((), id="no-postings"),
    ],
)
async def test_unbalanced_entry_is_rejected_at_commit(
    sessions: Sessions, amounts: tuple[int, ...]
) -> None:
    async with sessions() as session:
        await session.begin()
        accounts = [await _wallet(session) for _ in amounts]
        await _entry(session, *zip(accounts, amounts, strict=True))
        # The check is deferred: nothing fails until COMMIT.
        with pytest.raises(IntegrityError, match="unbalanced"):
            await session.commit()


@pytest.mark.parametrize("table", ["journal_entries", "postings"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {table} SET created_at = now()",
        "DELETE FROM {table}",
        "TRUNCATE {table} CASCADE",
    ],
)
async def test_ledger_tables_are_append_only(
    sessions: Sessions, table: str, statement: str
) -> None:
    async with sessions() as session, session.begin():
        a, b = await _wallet(session), await _wallet(session)
        await _entry(session, (a, -1), (b, 1))

    async with sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text(statement.format(table=table)))


async def test_wallet_balance_cannot_go_negative(sessions: Sessions) -> None:
    async with sessions() as session:
        await session.begin()
        with pytest.raises(IntegrityError, match="accounts_balance_non_negative"):
            await _wallet(session, balance=-1)


async def test_only_user_wallets_cache_a_balance(sessions: Sessions) -> None:
    async with sessions() as session:
        await session.begin()
        with pytest.raises(IntegrityError, match="accounts_balance_cached"):
            await session.execute(
                text(
                    "INSERT INTO accounts (kind, currency, balance) "
                    "VALUES ('APP_REVENUE', 'INR', 0)"
                )
            )


def _diff(connection: Connection) -> list[object]:
    diff: list[object] = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    return diff


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        assert await conn.run_sync(_diff) == []
