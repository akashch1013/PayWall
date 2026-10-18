"""The ``paywall`` command. Configuration comes from ``PAYWALL_*`` environment variables."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import typer

from paywall.app import PayWall
from paywall.auth import Scope
from paywall.errors import PayWallError

app = typer.Typer(help="PayWall operations tooling.", no_args_is_help=True)
api_keys = typer.Typer(help="Manage API keys for the standalone server.", no_args_is_help=True)
app.add_typer(api_keys, name="api-keys")


def _run[T](operation: Callable[[PayWall], Awaitable[T]]) -> T:
    async def run() -> T:
        paywall = PayWall.from_env()
        try:
            return await operation(paywall)
        finally:
            await paywall.close()

    try:
        return asyncio.run(run())
    except PayWallError as error:
        typer.echo(f"Error: {error.detail}", err=True)
        raise typer.Exit(1) from error


@app.command()
def migrate() -> None:
    """Create or upgrade PayWall's tables in PAYWALL_DB_SCHEMA. Safe to run repeatedly."""

    async def upgrade(paywall: PayWall) -> str:
        await paywall.migrate()
        return paywall.settings.db_schema

    typer.echo(f"Schema '{_run(upgrade)}' is up to date.")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    workers: Annotated[int, typer.Option(min=1, help="Worker processes.")] = 1,
) -> None:
    """Run the standalone API server (needs the 'server' extra)."""
    try:
        import uvicorn  # optional dependency
    except ImportError as error:
        typer.echo("The server needs extra packages: pip install 'paywall[server]'", err=True)
        raise typer.Exit(1) from error
    uvicorn.run(
        "paywall.server:app_factory",
        factory=True,
        host=host,
        port=port,
        workers=workers,
        # PayWall logs every request itself (as JSON, with its request id).
        log_config=None,
        access_log=False,
    )


@api_keys.command("create")
def create_api_key(
    name: Annotated[str, typer.Argument(help="Who will use the key, e.g. 'shop-backend'.")],
    scope: Annotated[
        list[Scope], typer.Option(help="Repeat for several. admin > wallet:write > wallet:read.")
    ],
) -> None:
    """Create an API key and print it. It is shown only once."""
    info, key = _run(lambda paywall: paywall.create_api_key(name, scope))
    typer.echo(f"Created {info.prefix} ({info.id}) with scopes {', '.join(sorted(info.scopes))}.")
    typer.echo("Store this key now; it cannot be shown again:")
    typer.echo(key)


@api_keys.command("list")
def list_api_keys() -> None:
    """List all keys (secrets are never shown)."""
    for key in _run(lambda paywall: paywall.list_api_keys()):
        status = f"revoked {key.revoked_at:%Y-%m-%d}" if key.revoked_at else "active"
        typer.echo(
            f"{key.id}  {key.prefix}  {key.name}  [{', '.join(sorted(key.scopes))}]  {status}"
        )


@api_keys.command("revoke")
def revoke_api_key(key_id: Annotated[uuid.UUID, typer.Argument(help="Id from 'list'.")]) -> None:
    """Revoke a key. Requests using it fail from now on."""
    key = _run(lambda paywall: paywall.revoke_api_key(key_id))
    typer.echo(f"Revoked {key.prefix} ({key.name}).")
