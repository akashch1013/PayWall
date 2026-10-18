"""Engine creation and the transaction runner every mutating operation goes through."""

import asyncio
import random
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from paywall.config import Settings

# deadlock_detected, serialization_failure: Postgres aborted the transaction to resolve a conflict,
# so running it again from the start is safe.
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})
RETRY_BASE_SECONDS = 0.05


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        # Every PayWall connection resolves unqualified table names in PayWall's own schema,
        # so the tables never collide with the host app's tables.
        connect_args={"server_settings": {"search_path": settings.db_schema}},
    )


async def run_tx[T](
    sessions: async_sessionmaker[AsyncSession],
    fn: Callable[[AsyncSession], Awaitable[T]],
    *,
    max_attempts: int,
) -> T:
    """Run ``fn`` in one transaction: commit if it returns, roll back if it raises.

    Deadlocks and serialization failures are retried with jittered exponential backoff. The
    rollback undid everything, so a retry starts from a clean slate.
    """
    attempt = 1
    while True:
        try:
            async with sessions() as session, session.begin():
                return await fn(session)
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate not in RETRYABLE_SQLSTATES or attempt >= max_attempts:
                raise
        # Jitter spreads out the retries of transactions that just collided with each other.
        await asyncio.sleep(RETRY_BASE_SECONDS * 2**attempt * random.random())  # noqa: S311  # nosec B311
        attempt += 1
