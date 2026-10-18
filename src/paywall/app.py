"""The ``PayWall`` facade: the Python API host apps call, and the source of the HTTP router.

It owns the database engine and runs every operation as one ``run_tx`` transaction. Mutations
take an ``idempotency_key``: calling again with the same key and arguments returns the original
result instead of moving money twice.
"""

import uuid
from collections.abc import Awaitable, Callable, Collection
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, Self

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall.api.deps import AuthDependency
from paywall.api.router import create_router
from paywall.auth import Scope
from paywall.config import Settings
from paywall.core import apikeys, idempotency, payments, wallets
from paywall.core.apikeys import ApiKey
from paywall.core.results import TransactionPage, Wallet, WalletEntry
from paywall.db.migrate import upgrade
from paywall.db.models import AccountStatus, EntryType
from paywall.db.session import create_engine, run_tx
from paywall.errors import ErrorCode, PayWallError

# Idempotency keys passed to the Python API share one namespace (HTTP callers get their own).
APP_SCOPE = "app"


class PayWall:
    def __init__(self, settings: Settings, *, auth: AuthDependency | None = None) -> None:
        """``auth`` is only needed to mount ``router``: see ``paywall.api.deps.AuthDependency``."""
        self.settings = settings
        self.engine = create_engine(settings)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._auth = auth

    @classmethod
    def from_env(cls, *, auth: AuthDependency | None = None) -> Self:
        """Build from ``PAYWALL_*`` environment variables (and ``.env``)."""
        return cls(Settings(), auth=auth)

    @cached_property
    def router(self) -> APIRouter:
        """The ``/v1`` wallet API, for ``app.include_router(paywall.router, prefix=...)``."""
        if self._auth is None:
            raise ValueError(
                "PayWall(auth=...) is required to mount the router: it tells PayWall which of "
                "your users is making each request. There is deliberately no default."
            )
        return create_router(self, auth=self._auth)

    async def close(self) -> None:
        await self.engine.dispose()

    async def migrate(self) -> None:
        """Create or upgrade PayWall's tables in ``PAYWALL_DB_SCHEMA``."""
        await upgrade(self.engine, self.settings.db_schema)

    @property
    def currency(self) -> str:
        """Currency of every wallet this instance manages (``PAYWALL_DEFAULT_CURRENCY``)."""
        return self.settings.default_currency

    async def _tx[T](self, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
        return await run_tx(self._sessions, fn, max_attempts=self.settings.tx_max_attempts)

    async def _idempotent(
        self,
        operation: str,
        key: str,
        args: dict[str, Any],
        fn: Callable[[AsyncSession], Awaitable[WalletEntry]],
    ) -> WalletEntry:
        if not key.strip():
            raise PayWallError(ErrorCode.VALIDATION_ERROR, "idempotency_key is required")
        entry, _ = await self.run_idempotent(
            scope=APP_SCOPE,
            key=key,
            fingerprint=idempotency.fingerprint(operation, args),
            operation=fn,
        )
        return entry

    async def run_idempotent(
        self,
        *,
        scope: str,
        key: str,
        fingerprint: str,
        operation: Callable[[AsyncSession], Awaitable[WalletEntry]],
    ) -> tuple[WalletEntry, bool]:
        """Run ``operation`` at most once per (scope, key). Returns (entry, replayed).

        Building block for the HTTP layer, which brings its own scope and request fingerprint.
        Python callers use ``debit``/``adjust``/``reverse``, which call this.
        """
        ttl = timedelta(hours=self.settings.idempotency_ttl_hours)

        async def work(session: AsyncSession) -> tuple[WalletEntry, bool]:
            stored = await idempotency.claim(session, scope=scope, key=key, fingerprint=fingerprint)
            if stored is not None:
                return WalletEntry.from_json(stored.body), True
            result = await operation(session)
            await idempotency.store(
                session,
                scope=scope,
                key=key,
                fingerprint=fingerprint,
                response_code=201,
                response_body=result.to_json(),
                ttl=ttl,
            )
            return result, False

        return await self._tx(work)

    async def get_wallet(self, user_id: str) -> Wallet:
        """Return the user's wallet, creating an empty one on first use."""
        return await self._tx(
            lambda session: wallets.get_or_create_wallet(session, user_id, self.currency)
        )

    async def history(
        self,
        user_id: str,
        *,
        cursor: int | None = None,
        limit: int = 50,
        types: Collection[EntryType] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> TransactionPage:
        return await self._tx(
            lambda session: wallets.history(
                session,
                user_id=user_id,
                currency=self.currency,
                cursor=cursor,
                limit=limit,
                types=types,
                since=since,
                until=until,
            )
        )

    async def debit(
        self,
        user_id: str,
        amount: int,
        *,
        reference: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
        actor: str = "app",
    ) -> WalletEntry:
        """Charge ``amount`` (minor units) to the user's wallet, e.g. to pay for an order."""
        return await self._idempotent(
            "debit",
            idempotency_key,
            {
                "user_id": user_id,
                "amount": amount,
                "currency": self.currency,
                "reference": reference,
                "metadata": metadata,
                "actor": actor,
            },
            lambda session: payments.debit(
                session,
                user_id=user_id,
                currency=self.currency,
                amount=amount,
                reference=reference,
                metadata=metadata,
                actor=actor,
            ),
        )

    async def adjust(
        self,
        user_id: str,
        amount: int,
        *,
        reason: str,
        idempotency_key: str,
        actor: str = "app",
    ) -> WalletEntry:
        """Operator correction: positive ``amount`` credits the wallet, negative debits it."""
        return await self._idempotent(
            "adjust",
            idempotency_key,
            {
                "user_id": user_id,
                "amount": amount,
                "currency": self.currency,
                "reason": reason,
                "actor": actor,
            },
            lambda session: payments.adjust(
                session,
                user_id=user_id,
                currency=self.currency,
                amount=amount,
                reason=reason,
                actor=actor,
            ),
        )

    async def reverse(
        self,
        entry_id: uuid.UUID,
        *,
        reason: str,
        idempotency_key: str,
        actor: str = "app",
    ) -> WalletEntry:
        """Undo an entry by posting its exact negation. Each entry can be reversed once."""
        return await self._idempotent(
            "reverse",
            idempotency_key,
            {"entry_id": str(entry_id), "reason": reason, "actor": actor},
            lambda session: payments.reverse(
                session, entry_id=entry_id, reason=reason, actor=actor
            ),
        )

    async def freeze(self, user_id: str) -> Wallet:
        """Block spending from the wallet. Operator actions (adjust, reverse) still apply."""
        return await self._set_status(user_id, AccountStatus.FROZEN)

    async def unfreeze(self, user_id: str) -> Wallet:
        return await self._set_status(user_id, AccountStatus.ACTIVE)

    async def _set_status(self, user_id: str, status: AccountStatus) -> Wallet:
        return await self._tx(
            lambda session: wallets.set_status(
                session, user_id=user_id, currency=self.currency, status=status
            )
        )

    async def create_api_key(self, name: str, scopes: Collection[Scope]) -> tuple[ApiKey, str]:
        """Create a standalone-server API key. The returned key is shown once and never stored."""
        return await self._tx(lambda session: apikeys.create(session, name=name, scopes=scopes))

    async def list_api_keys(self) -> list[ApiKey]:
        return await self._tx(apikeys.list_keys)

    async def revoke_api_key(self, key_id: uuid.UUID) -> ApiKey:
        return await self._tx(lambda session: apikeys.revoke(session, key_id))

    async def authenticate_api_key(self, key: str) -> ApiKey | None:
        return await self._tx(lambda session: apikeys.authenticate(session, key))
