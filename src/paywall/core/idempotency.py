"""Idempotency keys: a retried request returns the original result instead of running twice.

Used inside the operation's own transaction:

1. ``claim``: take a transaction-scoped advisory lock on (scope, key). If another transaction
   holds it, that request is still running, so this one fails with 409. Postgres releases the lock
   on commit, rollback or crash, so a key can never get stuck "in progress".
2. If a completed, unexpired row exists: same fingerprint returns the stored response; a different
   fingerprint means the key was reused for another request (422).
3. The caller does the work, then ``store`` saves the response before COMMIT.

Only successes are stored. A failed operation rolls back, so retrying the key runs it afresh.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from paywall.db.models import IdempotencyKey
from paywall.errors import ErrorCode, PayWallError


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def fingerprint(operation: str, args: Mapping[str, Any]) -> str:
    """SHA-256 of the operation and its arguments as canonical JSON (sorted keys)."""
    canonical = json.dumps(
        {"operation": operation, "args": args},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _lock_id(scope: str, key: str) -> int:
    # Advisory locks take a bigint; 64 bits of SHA-256 make accidental collisions negligible
    # (a collision would only cause a spurious 409, never a wrong replay).
    digest = hashlib.sha256(f"{scope}\x00{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def claim(
    session: AsyncSession, *, scope: str, key: str, fingerprint: str
) -> StoredResponse | None:
    """Return the stored response to replay, or None if the caller should run the operation."""
    locked = await session.scalar(select(func.pg_try_advisory_xact_lock(_lock_id(scope, key))))
    if not locked:
        raise PayWallError(
            ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS,
            "A request with this idempotency key is still being processed; retry later.",
        )

    row = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
            IdempotencyKey.expires_at > func.now(),
        )
    )
    if row is None:
        return None
    if row.fingerprint != fingerprint:
        raise PayWallError(
            ErrorCode.IDEMPOTENCY_KEY_REUSED,
            "This idempotency key was already used with different parameters.",
        )
    return StoredResponse(status_code=row.response_code, body=row.response_body)


async def store(
    session: AsyncSession,
    *,
    scope: str,
    key: str,
    fingerprint: str,
    response_code: int,
    response_body: dict[str, Any],
    ttl: timedelta,
) -> None:
    values = {
        "fingerprint": fingerprint,
        "response_code": response_code,
        "response_body": response_body,
        "created_at": func.now(),
        "expires_at": func.now() + ttl,
    }
    # We hold the key's lock and saw no live row, so a conflict can only be an expired row.
    await session.execute(
        insert(IdempotencyKey)
        .values(scope=scope, key=key, **values)
        .on_conflict_do_update(index_elements=["scope", "key"], set_=values)
    )
