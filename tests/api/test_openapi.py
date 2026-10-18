"""Every endpoint is documented: summary, description, problem+json errors, request examples."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from host_app import create_host_app, host_auth
from pydantic import SecretStr

from paywall import PayWall, Settings
from paywall.server import create_app

Operation = tuple[str, str, dict[str, Any]]


@pytest.fixture(scope="module")
def schema(settings: Settings) -> dict[str, Any]:
    jwt_settings = settings.model_copy(update={"jwt_secret": SecretStr("s" * 32)})
    openapi: dict[str, Any] = create_app(jwt_settings).openapi()
    return openapi


def operations(schema: dict[str, Any]) -> Iterator[Operation]:
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            yield path, method, operation


def test_all_endpoints_are_present(schema: dict[str, Any]) -> None:
    assert {(method.upper(), path) for path, method, _ in operations(schema)} == {
        ("GET", "/v1/wallets/me"),
        ("GET", "/v1/wallets/me/transactions"),
        ("POST", "/v1/wallets/me/debits"),
        ("POST", "/v1/admin/api-keys"),
        ("GET", "/v1/admin/api-keys"),
        ("DELETE", "/v1/admin/api-keys/{key_id}"),
        ("POST", "/v1/auth/tokens"),
    }


def test_every_operation_has_summary_and_description(schema: dict[str, Any]) -> None:
    for path, method, operation in operations(schema):
        assert operation.get("summary"), (method, path)
        assert operation.get("description"), (method, path)


def test_every_operation_documents_problem_errors(schema: dict[str, Any]) -> None:
    for path, method, operation in operations(schema):
        for status in ("401", "403", "422"):
            content = operation["responses"][status]["content"]
            assert set(content) == {"application/problem+json"}, (method, path, status)
            assert content["application/problem+json"]["examples"], (method, path, status)
    # FastAPI's default validation schema would misdescribe PayWall's 422 responses.
    assert "HTTPValidationError" not in json.dumps(schema)


def test_debit_documents_its_business_errors(schema: dict[str, Any]) -> None:
    responses = schema["paths"]["/v1/wallets/me/debits"]["post"]["responses"]

    assert set(responses) == {"201", "400", "401", "403", "404", "409", "422"}
    assert set(responses["409"]["content"]["application/problem+json"]["examples"]) == {
        "IDEMPOTENCY_KEY_IN_PROGRESS",
        "WALLET_FROZEN",
    }


def test_request_bodies_have_examples(schema: dict[str, Any]) -> None:
    components = schema["components"]["schemas"]
    for path, method, operation in operations(schema):
        if "requestBody" not in operation:
            continue
        ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert components[ref.rsplit("/", 1)[1]].get("examples"), (method, path)


def test_standalone_auth_is_documented(schema: dict[str, Any]) -> None:
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    debit = schema["paths"]["/v1/wallets/me/debits"]["post"]
    headers = {p["name"] for p in debit["parameters"] if p["in"] == "header"}
    assert headers == {"Idempotency-Key", "X-User-Id"}


def test_embedded_router_appears_under_the_host_prefix(settings: Settings) -> None:
    paths = create_host_app(PayWall(settings, auth=host_auth)).openapi()["paths"]

    assert "/wallet/v1/wallets/me/debits" in paths
    assert "/orders/{order_id}/pay" in paths
