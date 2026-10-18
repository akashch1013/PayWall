"""PayWall's router mounted inside a host app (Mode A), exercised over HTTP."""

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from host_app import ORDER_PRICE, create_host_app, host_auth
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall import PayWall, Settings
from paywall.db.models import JournalEntry

Sessions = async_sessionmaker[AsyncSession]
WALLET = "/wallet/v1/wallets/me"


@pytest.fixture(scope="session")
async def host_paywall(settings: Settings, engine: object) -> AsyncIterator[PayWall]:
    paywall = PayWall(settings, auth=host_auth)
    yield paywall
    await paywall.close()


@pytest.fixture
async def client(host_paywall: PayWall) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_host_app(host_paywall))
    async with httpx.AsyncClient(transport=transport, base_url="http://shop") as client:
        yield client


def as_user(user_id: str, role: str | None = None, key: str | None = None) -> dict[str, str]:
    headers = {"X-Demo-User": user_id}
    if role:
        headers["X-Demo-Role"] = role
    if key:
        headers["Idempotency-Key"] = key
    return headers


def new_key() -> str:
    return uuid.uuid4().hex


async def fund(paywall: PayWall, user_id: str, amount: int) -> None:
    await paywall.adjust(user_id, amount, reason="test funding", idempotency_key=new_key())


async def debit(
    client: httpx.AsyncClient, user_id: str, body: object, key: str | None = None, **kw: str
) -> httpx.Response:
    return await client.post(
        f"{WALLET}/debits", json=body, headers=as_user(user_id, key=key or new_key(), **kw)
    )


# --- wallet ---------------------------------------------------------------------------------


async def test_get_my_wallet_creates_it(client: httpx.AsyncClient, user_id: str) -> None:
    response = await client.get(WALLET, headers=as_user(user_id))

    assert response.status_code == 200
    body = response.json()
    assert (body["user_id"], body["balance"], body["currency"], body["status"]) == (
        user_id,
        0,
        "INR",
        "active",
    )


async def test_unauthenticated_request_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get(WALLET)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "UNAUTHORIZED"


async def test_principal_without_end_user_is_rejected(
    client: httpx.AsyncClient, user_id: str
) -> None:
    response = await client.get(WALLET, headers=as_user(user_id, role="ops"))

    assert response.status_code == 422
    assert "end user" in response.json()["detail"]


# --- debits ---------------------------------------------------------------------------------


async def test_debit(
    client: httpx.AsyncClient, host_paywall: PayWall, sessions: Sessions, user_id: str
) -> None:
    await fund(host_paywall, user_id, 100_000)

    response = await debit(
        client, user_id, {"amount": 49_900, "reference": "order_789", "metadata": {"sku": "TS"}}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["amount"], body["balance_after"]) == ("DEBIT", -49_900, 50_100)
    assert "idempotent-replayed" not in response.headers
    async with sessions() as session:
        entry = await session.get_one(JournalEntry, uuid.UUID(body["entry_id"]))
    assert entry.request_id == response.headers["x-request-id"]
    assert entry.actor == f"user:{user_id}"
    assert entry.metadata_ == {"sku": "TS"}


async def test_retried_debit_is_replayed_not_charged_twice(
    client: httpx.AsyncClient, host_paywall: PayWall, user_id: str
) -> None:
    await fund(host_paywall, user_id, 1_000)
    key, body = new_key(), {"amount": 300, "reference": "order_1"}

    first = await debit(client, user_id, body, key=key)
    retry = await debit(client, user_id, body, key=key)

    assert (first.status_code, retry.status_code) == (201, 201)
    assert retry.json() == first.json()
    assert retry.headers["idempotent-replayed"] == "true"
    assert (await host_paywall.get_wallet(user_id)).balance == 700


async def test_key_reused_with_another_body_is_422(
    client: httpx.AsyncClient, host_paywall: PayWall, user_id: str
) -> None:
    await fund(host_paywall, user_id, 1_000)
    key = new_key()
    await debit(client, user_id, {"amount": 300, "reference": "order_1"}, key=key)

    response = await debit(client, user_id, {"amount": 301, "reference": "order_1"}, key=key)

    assert response.status_code == 422
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_key_is_bound_to_the_end_user(
    client: httpx.AsyncClient, host_paywall: PayWall, user_id: str
) -> None:
    # One backend identity acting for two users with the same key and body: the second call
    # must be rejected, not answered with the first user's debit.
    other = f"{user_id}_b"
    await fund(host_paywall, user_id, 1_000)
    await fund(host_paywall, other, 1_000)
    key, body = new_key(), {"amount": 100, "reference": "order_x"}

    first = await debit(client, user_id, body, key=key, role="billing-service")
    second = await debit(client, other, body, key=key, role="billing-service")

    assert first.status_code == 201
    assert second.status_code == 422
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (await host_paywall.get_wallet(other)).balance == 1_000


@pytest.mark.parametrize("key", [None, "", "   "])
async def test_debit_requires_idempotency_key(
    client: httpx.AsyncClient, user_id: str, key: str | None
) -> None:
    headers = as_user(user_id)
    if key is not None:
        headers["Idempotency-Key"] = key

    response = await client.post(
        f"{WALLET}/debits", json={"amount": 1, "reference": "r"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_MISSING"


async def test_debit_insufficient_funds(
    client: httpx.AsyncClient, host_paywall: PayWall, user_id: str
) -> None:
    await fund(host_paywall, user_id, 1_000)

    response = await debit(client, user_id, {"amount": 49_900, "reference": "order_789"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Balance 1000 < amount 49900"


async def test_debit_without_wallet_is_404(client: httpx.AsyncClient, user_id: str) -> None:
    response = await debit(client, user_id, {"amount": 1, "reference": "r"})

    assert response.status_code == 404
    assert response.json()["code"] == "WALLET_NOT_FOUND"


async def test_read_only_user_cannot_debit(client: httpx.AsyncClient, user_id: str) -> None:
    read = await client.get(WALLET, headers=as_user(user_id, role="viewer"))
    write = await debit(client, user_id, {"amount": 1, "reference": "r"}, role="viewer")

    assert read.status_code == 200
    assert write.status_code == 403
    assert write.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    "body",
    [
        {"amount": "100", "reference": "r"},
        {"amount": 1.5, "reference": "r"},
        {"amount": True, "reference": "r"},
        {"amount": 0, "reference": "r"},
        {"amount": -5, "reference": "r"},
        {"amount": 2**63, "reference": "r"},
        {"amount": 1, "reference": ""},
        {"amount": 1},
        {"amount": 1, "reference": "r", "currency": "USD"},
        {"amount": 1, "reference": "r", "metadata": {str(i): i for i in range(21)}},
    ],
)
async def test_debit_rejects_invalid_bodies(
    client: httpx.AsyncClient, user_id: str, body: object
) -> None:
    response = await debit(client, user_id, body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


# --- transactions ---------------------------------------------------------------------------


async def test_transactions_pages_and_filters(
    client: httpx.AsyncClient, host_paywall: PayWall, user_id: str
) -> None:
    await fund(host_paywall, user_id, 1_000)
    for n in range(3):
        await debit(client, user_id, {"amount": 10 + n, "reference": f"o{n}"})
    url = f"{WALLET}/transactions"

    first = (await client.get(url, params={"limit": 2}, headers=as_user(user_id))).json()
    rest = (
        await client.get(
            url, params={"limit": 2, "cursor": first["next_cursor"]}, headers=as_user(user_id)
        )
    ).json()
    debits = (await client.get(url, params={"type": "DEBIT"}, headers=as_user(user_id))).json()
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    none = (await client.get(url, params={"from": future}, headers=as_user(user_id))).json()

    assert [t["amount"] for t in first["items"]] == [-12, -11]
    assert isinstance(first["next_cursor"], str)
    assert [t["amount"] for t in rest["items"]] == [-10, 1_000]
    assert rest["next_cursor"] is None
    assert {t["type"] for t in debits["items"]} == {"DEBIT"}
    assert none == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-10-12T00:00:00"},  # no timezone
        {"cursor": "abc"},
        {"cursor": "0"},
        {"limit": 101},
        {"type": "PAYOUT"},
    ],
)
async def test_transactions_reject_bad_parameters(
    client: httpx.AsyncClient, user_id: str, params: dict[str, str | int]
) -> None:
    response = await client.get(f"{WALLET}/transactions", params=params, headers=as_user(user_id))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


# --- the host side --------------------------------------------------------------------------


async def test_host_route_uses_the_python_api(
    client: httpx.AsyncClient, host_paywall: PayWall, user_id: str
) -> None:
    await fund(host_paywall, user_id, ORDER_PRICE + 100)
    order = f"o_{uuid.uuid4().hex}"

    paid = await client.post(f"/orders/{order}/pay", headers=as_user(user_id))
    again = await client.post(f"/orders/{order}/pay", headers=as_user(user_id))
    broke = await client.post(f"/orders/{order}_2/pay", headers=as_user(user_id))

    assert paid.json() == {"order_id": order, "balance": 100}
    assert again.json() == paid.json()  # the host's own retry is idempotent too
    assert broke.status_code == 402


async def test_host_http_exceptions_keep_the_hosts_format(
    client: httpx.AsyncClient, user_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="paywall.api"):
        response = await client.get(WALLET, headers=as_user(user_id, role="banned"))

    assert response.status_code == 403
    assert response.json() == {"detail": "Account suspended"}  # the host's own error body
    assert response.headers["x-request-id"].startswith("req_")
    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert record.__dict__["status"] == 403


async def test_retry_through_another_mount_path_is_replayed(
    host_paywall: PayWall, user_id: str
) -> None:
    await fund(host_paywall, user_id, 1_000)
    other_mount = FastAPI()
    other_mount.include_router(host_paywall.router, prefix="/api/wallet")
    key, body = new_key(), {"amount": 100, "reference": "order_1"}
    headers = as_user(user_id, key=key)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_host_app(host_paywall)), base_url="http://a"
    ) as first_client:
        first = await first_client.post(f"{WALLET}/debits", json=body, headers=headers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=other_mount), base_url="http://b"
    ) as second_client:
        retry = await second_client.post(
            "/api/wallet/v1/wallets/me/debits", json=body, headers=headers
        )

    assert retry.json() == first.json()
    assert retry.headers["idempotent-replayed"] == "true"


def test_router_requires_auth(settings: Settings) -> None:
    with pytest.raises(ValueError, match="auth"):
        _ = PayWall(settings).router
