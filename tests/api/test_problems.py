"""ProblemRoute in isolation, on a throwaway app with routes that fail in each possible way."""

import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from paywall.api.problems import PROBLEM_MEDIA_TYPE, ProblemRoute, problem_responses
from paywall.errors import ErrorCode, PayWallError
from paywall.observability import request_id_var


class Body(BaseModel):
    amount: int
    secret: str


router = APIRouter(route_class=ProblemRoute)


@router.get("/fail")
async def fail() -> None:
    raise PayWallError(ErrorCode.INSUFFICIENT_FUNDS, "Balance 1000 < amount 49900")


@router.post("/validate")
async def validate(body: Body) -> None:
    return None


@router.get("/crash")
async def crash() -> None:
    raise RuntimeError("bug")


@router.get("/ok")
async def ok() -> dict[str, str | None]:
    return {"request_id": request_id_var.get()}


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_business_error_is_problem_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/fail")

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "urn:paywall:error:insufficient_funds",
        "title": "Insufficient funds",
        "status": 422,
        "detail": "Balance 1000 < amount 49900",
        "code": "INSUFFICIENT_FUNDS",
        "request_id": response.headers["x-request-id"],
    }


async def test_validation_error_lists_issues_without_echoing_input(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/validate", json={"amount": "lots", "secret": "hunter2"})

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [
        {"loc": ["body", "amount"], "msg": body["errors"][0]["msg"], "type": "int_parsing"}
    ]
    assert "hunter2" not in response.text
    assert "lots" not in response.text


async def test_valid_incoming_request_id_is_reused(client: httpx.AsyncClient) -> None:
    response = await client.get("/ok", headers={"X-Request-ID": "trace-42.a_b"})

    assert response.headers["x-request-id"] == "trace-42.a_b"
    assert response.json() == {"request_id": "trace-42.a_b"}


@pytest.mark.parametrize("incoming", ["", "has space", "x" * 65, "<script>"])
async def test_unsafe_incoming_request_id_is_replaced(
    client: httpx.AsyncClient, incoming: str
) -> None:
    response = await client.get("/ok", headers={"X-Request-ID": incoming})

    assert response.headers["x-request-id"].startswith("req_")
    assert len(response.headers["x-request-id"]) == 36


async def test_unexpected_error_is_logged_with_request_id(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="paywall.api"):
        response = await client.get("/crash", headers={"X-Request-ID": "req_crash"})

    assert response.status_code == 500
    [record] = caplog.records
    assert record.exc_info is not None
    assert (record.__dict__["method"], record.__dict__["path"]) == ("GET", "/crash")
    assert request_id_var.get() is None  # the request's id does not leak into other code


async def test_each_request_is_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="paywall.api"):
        await client.get("/fail")

    [record] = caplog.records
    fields = record.__dict__
    assert (fields["method"], fields["path"], fields["status"]) == ("GET", "/fail", 422)
    assert fields["duration_ms"] >= 0


def test_problem_responses_group_codes_by_status() -> None:
    responses = problem_responses(ErrorCode.INSUFFICIENT_FUNDS, ErrorCode.UNAUTHORIZED)

    assert sorted(responses) == [401, 422]
    examples = responses[422]["content"][PROBLEM_MEDIA_TYPE]["examples"]
    assert set(examples) == {"INSUFFICIENT_FUNDS", "VALIDATION_ERROR"}
    assert "INSUFFICIENT_FUNDS" in responses[422]["description"]
