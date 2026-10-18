from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_postgres_is_reachable_and_supported(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        version = await conn.scalar(text("SHOW server_version_num"))

    # The schema relies on UNIQUE NULLS NOT DISTINCT (PG 15+); we support and test PG 16+.
    assert int(version) >= 160000
