"""Auth and request plumbing shared by every PayWall endpoint."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header

from paywall.auth import Principal, Scope
from paywall.errors import ErrorCode, PayWallError

type AuthDependency = Callable[..., Principal | Awaitable[Principal | None] | None]
"""A FastAPI dependency that identifies the caller.

It may declare its own parameters and sub-dependencies (cookies, headers, the host's session).
It returns a ``Principal``, or None when the request is not authenticated (PayWall answers 401).
"""

type PrincipalDependency = Callable[..., Awaitable[Principal]]


def principal_dependency(auth: AuthDependency) -> PrincipalDependency:
    async def current_principal(
        principal: Annotated[Principal | None, Depends(auth)],
    ) -> Principal:
        if principal is None:
            raise PayWallError(ErrorCode.UNAUTHORIZED, "Missing or invalid credentials.")
        return principal

    return current_principal


def requires(scope: Scope, current: PrincipalDependency) -> PrincipalDependency:
    async def check_scope(principal: Annotated[Principal, Depends(current)]) -> Principal:
        if not principal.has(scope):
            raise PayWallError(ErrorCode.FORBIDDEN, f"This credential lacks the '{scope}' scope.")
        return principal

    return check_scope


def end_user(principal: Principal) -> str:
    """The user whose wallet ``/wallets/me`` means."""
    if principal.user_id is None:
        raise PayWallError(
            ErrorCode.VALIDATION_ERROR,
            "This request does not identify an end user (API-key callers send X-User-Id).",
        )
    return principal.user_id


async def idempotency_key(
    key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=255,
            description="Unique per logical operation; retries reuse it. Kept for 24 hours.",
            examples=["order_789_pay"],
        ),
    ] = None,
) -> str:
    if key is None or not key.strip():
        raise PayWallError(
            ErrorCode.IDEMPOTENCY_KEY_MISSING,
            "Send an Idempotency-Key header so that retries cannot move money twice.",
        )
    return key


IdempotencyKey = Annotated[str, Depends(idempotency_key)]


def scope_for(principal: Principal) -> str:
    # Prefixed so an HTTP caller can never share a namespace with Python-API keys ("app").
    return f"http:{principal.subject}"
