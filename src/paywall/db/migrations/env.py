"""Alembic environment. Migrations only run through ``paywall.db.migrate.upgrade``.

It passes an open connection and the target schema in ``config.attributes``. Tables are created
unqualified and land in that schema because ``search_path`` is set to it first.
"""

from alembic import context
from sqlalchemy import Connection, text

connection: Connection = context.config.attributes["connection"]
schema: str = context.config.attributes["schema"]

quoted = connection.dialect.identifier_preparer.quote_schema(schema)
connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted}"))
connection.execute(text(f"SET LOCAL search_path TO {quoted}"))

context.configure(connection=connection, version_table_schema=schema, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
