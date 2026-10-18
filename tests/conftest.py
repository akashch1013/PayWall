"""Shared fixtures. Each test session runs against its own throwaway Postgres database.

Money logic is only ever tested against real Postgres (row locks, constraints, triggers);
SQLite would not exercise any of it. Tests share one migrated database and isolate themselves
with unique user ids, because concurrency tests need committed data (no rollback-per-test).
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from paywall.app import PayWall
from paywall.config import Settings
from paywall.db.migrate import upgrade
from paywall.db.session import create_engine


class DevSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYWALL_", env_file=".env", extra="ignore")

    test_database_url: str | None = None


@pytest.fixture(scope="session")
async def database_url() -> AsyncIterator[URL]:
    base = DevSettings().test_database_url
    if base is None:
        pytest.exit("PAYWALL_TEST_DATABASE_URL is not set (see .env.example).", returncode=1)

    server = make_url(base)
    # Generated from a UUID, never from input, so interpolating it into DDL is safe.
    name = f"paywall_test_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(server, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name)
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest.fixture(scope="session")
def settings(database_url: URL) -> Settings:
    return Settings(database_url=database_url.render_as_string(hide_password=False))


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """An engine on the test database, migrated to the latest revision."""
    engine = create_engine(settings)
    await upgrade(engine, settings.db_schema)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="session")
async def paywall(settings: Settings, engine: AsyncEngine) -> AsyncIterator[PayWall]:
    """The facade under test; depends on ``engine`` so the schema is migrated first."""
    wallet = PayWall(settings)
    yield wallet
    await wallet.close()


@pytest.fixture
def user_id() -> str:
    return f"user_{uuid.uuid4().hex}"
