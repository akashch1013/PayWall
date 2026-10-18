"""Apply the bundled Alembic migrations to a database."""

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

SCRIPT_LOCATION = "paywall.db:migrations"


def _upgrade(connection: Connection, schema: str) -> None:
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    config.attributes["connection"] = connection
    config.attributes["schema"] = schema
    command.upgrade(config, "head")


async def upgrade(engine: AsyncEngine, schema: str) -> None:
    """Upgrade ``schema`` to the latest revision, creating the schema if needed.

    Runs in one transaction, so a failed migration leaves the database unchanged.
    """
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade, schema)
