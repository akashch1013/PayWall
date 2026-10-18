import asyncio
import sys
import uuid

import pytest
from sqlalchemy import URL, Column, MetaData, Table, Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from typer.testing import CliRunner

from paywall.cli import app


async def _revision(url: URL, schema: str) -> str | None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            version = Table("alembic_version", MetaData(schema=schema), Column("version_num", Text))
            return await conn.scalar(select(version.c.version_num))
    finally:
        await engine.dispose()


def test_migrate_is_repeatable(
    database_url: URL, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = f"cli_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("PAYWALL_DATABASE_URL", database_url.render_as_string(hide_password=False))
    monkeypatch.setenv("PAYWALL_DB_SCHEMA", schema)  # a fresh schema, migrated from nothing
    runner = CliRunner()

    first = runner.invoke(app, ["migrate"])
    second = runner.invoke(app, ["migrate"])

    assert first.exit_code == second.exit_code == 0, first.output
    assert f"Schema '{schema}' is up to date." in second.output
    assert asyncio.run(_revision(database_url, schema)) == "0002"


@pytest.fixture
def cli_env(database_url: URL, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYWALL_DATABASE_URL", database_url.render_as_string(hide_password=False))


@pytest.mark.usefixtures("cli_env")
def test_api_key_lifecycle() -> None:
    runner = CliRunner()

    created = runner.invoke(app, ["api-keys", "create", "shop-backend", "--scope", "wallet:write"])
    key = created.output.strip().splitlines()[-1]
    prefix = key[: len("pw_") + 12]  # the secret part may itself contain "_"
    listed = runner.invoke(app, ["api-keys", "list"])
    [line] = [line for line in listed.output.splitlines() if prefix in line]
    revoked = runner.invoke(app, ["api-keys", "revoke", line.split()[0]])
    listed_after = runner.invoke(app, ["api-keys", "list"])

    assert created.exit_code == 0, created.output
    assert key.startswith("pw_")
    assert "cannot be shown again" in created.output
    assert "shop-backend" in line
    assert "active" in line
    assert key not in listed.output
    assert revoked.exit_code == 0
    assert f"Revoked {prefix}" in revoked.output
    assert "revoked" in next(line for line in listed_after.output.splitlines() if prefix in line)


@pytest.mark.usefixtures("cli_env")
def test_api_key_errors_exit_non_zero() -> None:
    runner = CliRunner()

    unknown = runner.invoke(app, ["api-keys", "revoke", str(uuid.uuid4())])
    bad_scope = runner.invoke(app, ["api-keys", "create", "x", "--scope", "root"])

    assert unknown.exit_code == 1
    assert "not found" in unknown.output
    assert bad_scope.exit_code != 0


def test_serve_runs_uvicorn_with_the_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = CliRunner().invoke(app, ["serve", "--port", "9000", "--workers", "2"])

    assert result.exit_code == 0, result.output
    [(args, kwargs)] = calls
    assert args == ("paywall.server:app_factory",)
    assert kwargs["factory"] is True
    assert (kwargs["host"], kwargs["port"], kwargs["workers"]) == ("127.0.0.1", 9000, 2)


def test_serve_explains_the_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "uvicorn", None)  # makes `import uvicorn` fail

    result = CliRunner().invoke(app, ["serve"])

    assert result.exit_code == 1
    assert "paywall[server]" in result.output
