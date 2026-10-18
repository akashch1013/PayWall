"""API keys for the standalone server.

A key is ``pw_<prefix>_<secret>``: 48 random bits of public prefix (shown in listings and used to
name the caller) plus 256 random bits of secret. Only ``sha256(key)`` is stored. A fast hash is
safe here because the key is random, not a human password: there is nothing to brute-force, and an
indexed lookup by hash keeps authentication O(1). bcrypt-style slow hashes exist to protect
low-entropy passwords and would only add latency.
"""

import hashlib
import secrets
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from paywall.auth import Scope
from paywall.db.models import ApiKeyRecord
from paywall.errors import ErrorCode, PayWallError

KEY_PREFIX = "pw_"
# Longer than any key we issue; anything bigger is rejected before hashing.
MAX_KEY_LENGTH = 100


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: uuid.UUID
    name: str
    prefix: str
    scopes: frozenset[Scope]
    created_at: datetime
    revoked_at: datetime | None

    @classmethod
    def from_record(cls, record: ApiKeyRecord) -> Self:
        return cls(
            id=record.id,
            name=record.name,
            prefix=record.prefix,
            scopes=frozenset(Scope(s) for s in record.scopes),
            created_at=record.created_at,
            revoked_at=record.revoked_at,
        )


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def create(
    session: AsyncSession, *, name: str, scopes: Collection[Scope]
) -> tuple[ApiKey, str]:
    """Create a key. Returns its metadata and the key itself, which is never retrievable again."""
    if not name.strip():
        raise PayWallError(ErrorCode.VALIDATION_ERROR, "name is required")
    if not scopes:
        raise PayWallError(ErrorCode.VALIDATION_ERROR, "at least one scope is required")
    prefix = f"{KEY_PREFIX}{secrets.token_hex(6)}"
    key = f"{prefix}_{secrets.token_urlsafe(32)}"
    record = (
        await session.execute(
            insert(ApiKeyRecord)
            .values(
                name=name,
                prefix=prefix,
                key_hash=_hash(key),
                scopes=sorted({Scope(s).value for s in scopes}),
            )
            .returning(ApiKeyRecord)
        )
    ).scalar_one()
    return ApiKey.from_record(record), key


async def list_keys(session: AsyncSession) -> list[ApiKey]:
    records = await session.scalars(select(ApiKeyRecord).order_by(ApiKeyRecord.created_at))
    return [ApiKey.from_record(r) for r in records]


async def revoke(session: AsyncSession, key_id: uuid.UUID) -> ApiKey:
    """Revoke a key. Idempotent: revoking an already revoked key keeps its original timestamp."""
    record = await session.scalar(
        update(ApiKeyRecord)
        .where(ApiKeyRecord.id == key_id)
        .values(revoked_at=func.coalesce(ApiKeyRecord.revoked_at, func.now()))
        .returning(ApiKeyRecord)
        .execution_options(synchronize_session=False)
    )
    if record is None:
        raise PayWallError(ErrorCode.NOT_FOUND, f"API key {key_id} not found")
    return ApiKey.from_record(record)


async def authenticate(session: AsyncSession, key: str) -> ApiKey | None:
    """Return the key's metadata if it exists and is not revoked, else None."""
    if not key.startswith(KEY_PREFIX) or len(key) > MAX_KEY_LENGTH:
        return None
    record = await session.scalar(
        select(ApiKeyRecord).where(
            ApiKeyRecord.key_hash == _hash(key), ApiKeyRecord.revoked_at.is_(None)
        )
    )
    return None if record is None else ApiKey.from_record(record)
