import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall import PayWall
from paywall.auth import Principal, Scope
from paywall.db.models import ApiKeyRecord
from paywall.errors import ErrorCode, PayWallError

Sessions = async_sessionmaker[AsyncSession]


async def test_only_the_hash_of_a_key_is_stored(paywall: PayWall, sessions: Sessions) -> None:
    info, key = await paywall.create_api_key("billing-backend", [Scope.WALLET_WRITE])

    assert key.startswith(f"{info.prefix}_")
    assert info.prefix.startswith("pw_")
    async with sessions() as session:
        record = await session.get_one(ApiKeyRecord, info.id)
    assert record.key_hash == hashlib.sha256(key.encode()).hexdigest()
    assert key not in (record.prefix, record.key_hash, record.name)


async def test_key_authenticates_until_revoked(paywall: PayWall) -> None:
    info, key = await paywall.create_api_key("ops", [Scope.ADMIN])

    assert await paywall.authenticate_api_key(key) == info
    revoked = await paywall.revoke_api_key(info.id)
    again = await paywall.revoke_api_key(info.id)

    assert revoked.revoked_at is not None
    assert again.revoked_at == revoked.revoked_at  # revoking twice keeps the first timestamp
    assert await paywall.authenticate_api_key(key) is None


@pytest.mark.parametrize("candidate", ["", "pw_", "not-a-key", "pw_" + "x" * 500])
async def test_unknown_or_malformed_keys_do_not_authenticate(
    paywall: PayWall, candidate: str
) -> None:
    assert await paywall.authenticate_api_key(candidate) is None


async def test_list_includes_revoked_keys(paywall: PayWall) -> None:
    info, _ = await paywall.create_api_key("temp", [Scope.WALLET_READ])
    await paywall.revoke_api_key(info.id)

    listed = {k.id: k for k in await paywall.list_api_keys()}

    assert listed[info.id].revoked_at is not None


async def test_revoking_unknown_key_is_not_found(paywall: PayWall) -> None:
    with pytest.raises(PayWallError) as error:
        await paywall.revoke_api_key(uuid.uuid4())

    assert error.value.code is ErrorCode.NOT_FOUND


@pytest.mark.parametrize(("name", "scopes"), [(" ", [Scope.ADMIN]), ("ok", [])])
async def test_key_needs_a_name_and_scopes(
    paywall: PayWall, name: str, scopes: list[Scope]
) -> None:
    with pytest.raises(PayWallError) as error:
        await paywall.create_api_key(name, scopes)

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_database_rejects_unknown_scopes(sessions: Sessions) -> None:
    async with sessions() as session:
        await session.begin()
        session.add(ApiKeyRecord(name="x", prefix="pw_x", key_hash="0" * 64, scopes=["superuser"]))
        with pytest.raises(Exception, match="api_keys_scopes"):
            await session.flush()


def test_scopes_imply_weaker_scopes() -> None:
    admin = Principal(subject="apikey:pw_1", user_id=None, scopes=frozenset({Scope.ADMIN}))
    writer = Principal(subject="apikey:pw_2", user_id=None, scopes=frozenset({Scope.WALLET_WRITE}))
    reader = Principal(subject="apikey:pw_3", user_id=None, scopes=frozenset({Scope.WALLET_READ}))
    user = Principal.user("u1")

    assert admin.has(Scope.WALLET_WRITE)
    assert writer.has(Scope.WALLET_READ)
    assert not writer.has(Scope.ADMIN)
    assert not reader.has(Scope.WALLET_WRITE)
    assert user.has(Scope.WALLET_READ)
    assert user.has(Scope.WALLET_WRITE)
    assert not user.has(Scope.ADMIN)
    assert user.subject == "user:u1"


def test_unknown_scopes_from_a_host_grant_nothing() -> None:
    # A host may build Principals from its own role strings.
    principal = Principal(
        subject="svc",
        user_id="u1",
        scopes=frozenset({"reports", "wallet:read"}),  # type: ignore[arg-type]
    )

    assert principal.has(Scope.WALLET_READ)
    assert not principal.has(Scope.WALLET_WRITE)


async def test_repeated_scopes_are_stored_once(paywall: PayWall, sessions: Sessions) -> None:
    info, _ = await paywall.create_api_key("dup", [Scope.ADMIN, Scope.ADMIN])

    async with sessions() as session:
        record = await session.get_one(ApiKeyRecord, info.id)
    assert record.scopes == ["admin"]


async def test_keys_are_listed_oldest_first(paywall: PayWall) -> None:
    first, _ = await paywall.create_api_key("first", [Scope.WALLET_READ])
    second, _ = await paywall.create_api_key("second", [Scope.WALLET_READ])

    ids = [k.id for k in await paywall.list_api_keys()]

    assert ids.index(first.id) < ids.index(second.id)
