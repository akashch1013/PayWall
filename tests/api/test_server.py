"""The standalone server (Mode B): API keys, user tokens and admin routes over HTTP."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall import PayWall, Scope, Settings
from paywall.db.models import JournalEntry
from paywall.server import app_factory, create_app, issue_user_token

JWT_SECRET = "test-secret-that-is-long-enough-for-hs256"
WALLET = "/v1/wallets/me"
KEYS = "/v1/admin/api-keys"


@pytest.fixture(scope="session")
def jwt_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"jwt_secret": SecretStr(JWT_SECRET)})


async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://paywall") as client:
        yield client
    await app.state.paywall.close()


@pytest.fixture
async def client(jwt_settings: Settings, engine: object) -> AsyncIterator[httpx.AsyncClient]:
    async for client in _client(create_app(jwt_settings)):
        yield client


@pytest.fixture
async def admin_key(paywall: PayWall) -> str:
    # The first admin key is bootstrapped outside HTTP (`paywall api-keys create`).
    _, key = await paywall.create_api_key("test-admin", [Scope.ADMIN])
    return key


def bearer(credential: str, user_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {credential}"}
    if user_id is not None:
        headers["X-User-Id"] = user_id
    return headers


async def new_key(client: httpx.AsyncClient, admin_key: str, *scopes: str) -> dict[str, str]:
    response = await client.post(
        KEYS, json={"name": "backend", "scopes": list(scopes)}, headers=bearer(admin_key)
    )
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


# --- API keys -------------------------------------------------------------------------------


async def test_backend_flow_with_an_api_key(
    client: httpx.AsyncClient,
    admin_key: str,
    paywall: PayWall,
    sessions: async_sessionmaker[AsyncSession],
    user_id: str,
) -> None:
    created = await new_key(client, admin_key, "wallet:write")
    key = created["key"]
    await paywall.adjust(user_id, 100_000, reason="seed", idempotency_key=uuid.uuid4().hex)

    wallet = await client.get(WALLET, headers=bearer(key, user_id))
    paid = await client.post(
        f"{WALLET}/debits",
        json={"amount": 49_900, "reference": "order_789"},
        headers=bearer(key, user_id) | {"Idempotency-Key": "order_789_pay"},
    )
    history = await client.get(f"{WALLET}/transactions", headers=bearer(key, user_id))

    assert created["prefix"] == key[: len(created["prefix"])]
    assert wallet.json()["balance"] == 100_000
    assert paid.status_code == 201
    assert [t["amount"] for t in history.json()["items"]] == [-49_900, 100_000]
    async with sessions() as session:
        entry = await session.get_one(JournalEntry, uuid.UUID(paid.json()["entry_id"]))
    assert entry.actor == f"apikey:{created['prefix']}"


async def test_api_key_must_name_the_end_user(client: httpx.AsyncClient, admin_key: str) -> None:
    key = (await new_key(client, admin_key, "wallet:read"))["key"]

    response = await client.get(WALLET, headers=bearer(key))

    assert response.status_code == 422
    assert "X-User-Id" in response.json()["detail"]


async def test_listing_never_shows_secrets(client: httpx.AsyncClient, admin_key: str) -> None:
    created = await new_key(client, admin_key, "wallet:read")

    listed = (await client.get(KEYS, headers=bearer(admin_key))).json()

    [match] = [k for k in listed if k["id"] == created["id"]]
    assert set(match) == {"id", "name", "prefix", "scopes", "created_at", "revoked_at"}
    assert created["key"] not in str(listed)


async def test_revoked_key_stops_working_immediately(
    client: httpx.AsyncClient, admin_key: str, user_id: str
) -> None:
    created = await new_key(client, admin_key, "wallet:read")
    before = await client.get(WALLET, headers=bearer(created["key"], user_id))

    revoked = await client.delete(f"{KEYS}/{created['id']}", headers=bearer(admin_key))
    after = await client.get(WALLET, headers=bearer(created["key"], user_id))

    assert before.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    assert after.status_code == 401


async def test_revoking_unknown_key_is_404(client: httpx.AsyncClient, admin_key: str) -> None:
    response = await client.delete(f"{KEYS}/{uuid.uuid4()}", headers=bearer(admin_key))

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_non_admin_key_cannot_administer(client: httpx.AsyncClient, admin_key: str) -> None:
    key = (await new_key(client, admin_key, "wallet:read", "wallet:write"))["key"]

    for response in [
        await client.get(KEYS, headers=bearer(key)),
        await client.post("/v1/auth/tokens", json={"user_id": "u1"}, headers=bearer(key, "u1")),
    ]:
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    "body",
    [{"name": "x", "scopes": []}, {"name": "x", "scopes": ["root"]}, {"name": "", "scopes": []}],
)
async def test_key_creation_validates_input(
    client: httpx.AsyncClient, admin_key: str, body: dict[str, object]
) -> None:
    response = await client.post(KEYS, json=body, headers=bearer(admin_key))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer pw_0000_not-a-real-key"},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ],
)
async def test_missing_or_bad_credentials_are_401(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get(WALLET, headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


# --- user tokens ----------------------------------------------------------------------------


async def test_user_token_grants_only_that_users_wallet(
    client: httpx.AsyncClient, admin_key: str, user_id: str
) -> None:
    minted = await client.post(
        "/v1/auth/tokens", json={"user_id": user_id}, headers=bearer(admin_key)
    )
    token = minted.json()["access_token"]

    mine = await client.get(WALLET, headers=bearer(token))
    # X-User-Id cannot redirect a user token to someone else's wallet.
    other = await client.get(WALLET, headers=bearer(token, "someone_else"))
    admin = await client.get(KEYS, headers=bearer(token))

    assert minted.json()["token_type"] == "bearer"
    assert minted.json()["expires_in"] == 3600
    assert mine.json()["user_id"] == other.json()["user_id"] == user_id
    assert admin.status_code == 403


def _token(secret: str = JWT_SECRET, algorithm: str = "HS256", **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": "paywall",
        "sub": "u1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(_token(exp=datetime.now(UTC) - timedelta(minutes=2)), id="expired"),
        pytest.param(_token(iat=datetime.now(UTC) + timedelta(minutes=2)), id="issued-later"),
        pytest.param(_token(secret="another-secret-that-is-long-enough-xx"), id="foreign"),
        pytest.param(_token(iss="someone-else"), id="issuer"),
        pytest.param(_token(sub=None), id="no-subject"),
        pytest.param(_token(sub=""), id="empty-subject"),
        pytest.param(_token(secret="", algorithm="none"), id="alg-none"),
        pytest.param(_token()[:-2] + "xx", id="tampered"),
    ],
)
async def test_invalid_user_tokens_are_401(client: httpx.AsyncClient, token: str) -> None:
    response = await client.get(WALLET, headers=bearer(token))

    assert response.status_code == 401


async def test_small_clock_skew_is_tolerated(client: httpx.AsyncClient) -> None:
    # Minted on an instance whose clock runs 10 seconds ahead of this one.
    skewed = _token(iat=datetime.now(UTC) + timedelta(seconds=10))

    response = await client.get(WALLET, headers=bearer(skewed))

    assert response.status_code == 200


async def test_without_jwt_secret_tokens_are_disabled(
    settings: Settings, engine: object, admin_key: str
) -> None:
    async for client in _client(create_app(settings)):
        minted = await client.post(
            "/v1/auth/tokens", json={"user_id": "u1"}, headers=bearer(admin_key)
        )
        used = await client.get(WALLET, headers=bearer(_token()))

        assert minted.status_code == 404
        assert used.status_code == 401


def test_issue_user_token_requires_a_secret(settings: Settings) -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        issue_user_token(settings, "u1")


def test_app_factory_reads_the_environment_and_configures_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured: list[Settings] = []
    monkeypatch.setenv("PAYWALL_DATABASE_URL", "postgresql+asyncpg://u:p@db.internal/app")
    monkeypatch.setattr("paywall.server.configure_logging", configured.append)

    app = app_factory()

    assert configured[0].database_url.get_secret_value().endswith("@db.internal/app")
    assert app.state.paywall.settings is configured[0]


async def test_shutdown_closes_the_database_pool(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(settings)
    closed: list[bool] = []

    async def close() -> None:
        closed.append(True)

    monkeypatch.setattr(app.state.paywall, "close", close)
    async with app.router.lifespan_context(app):
        assert closed == []

    assert closed == [True]


async def test_unexpected_error_is_problem_json_with_request_id(
    jwt_settings: Settings, engine: object, monkeypatch: pytest.MonkeyPatch, admin_key: str
) -> None:
    app = create_app(jwt_settings)

    async def broken(user_id: str) -> None:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(app.state.paywall, "get_wallet", broken)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://paywall") as client:
        response = await client.get(WALLET, headers=bearer(admin_key, "u1"))
    await app.state.paywall.close()

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "exploded" not in response.text
