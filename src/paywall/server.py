"""Standalone PayWall server (Mode B): the same API, behind API-key and JWT auth.

Run it with ``paywall serve`` (needs ``pip install paywall[server]``). Every request sends
``Authorization: Bearer <credential>``, where the credential is either:

- an **API key** (``pw_…``), for backends. A key acts for any end user, named per request with
  ``X-User-Id``. Create the first admin key with ``paywall api-keys create``.
- a **user token** (JWT), for browsers and mobile apps. Your backend mints one with
  ``POST /v1/auth/tokens`` after its own login. It only grants access to that user's wallet.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from paywall import __version__
from paywall.api.admin import create_admin_router
from paywall.api.deps import AuthDependency, principal_dependency
from paywall.api.problems import PROBLEM_MEDIA_TYPE, REQUEST_ID_HEADER, problem_body
from paywall.api.router import create_router
from paywall.app import PayWall
from paywall.auth import Principal
from paywall.config import Settings
from paywall.core.apikeys import KEY_PREFIX
from paywall.errors import ErrorCode
from paywall.observability import configure_logging

# HS256 only. Accepting the algorithm named in the token header would let an attacker pick
# "none", or confuse HMAC with public-key algorithms.
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "paywall"
# Tolerated clock difference between the instance that minted a token and the one checking it.
JWT_LEEWAY_SECONDS = 30


def issue_user_token(settings: Settings, user_id: str) -> tuple[str, int]:
    """Return (token, seconds until expiry) for ``user_id``. Requires PAYWALL_JWT_SECRET."""
    if settings.jwt_secret is None:
        raise ValueError("PAYWALL_JWT_SECRET is not set")
    now = datetime.now(UTC)
    ttl = settings.jwt_ttl_minutes * 60
    token = jwt.encode(
        {"iss": JWT_ISSUER, "sub": user_id, "iat": now, "exp": now + timedelta(seconds=ttl)},
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    return token, ttl


def read_user_token(settings: Settings, token: str) -> str | None:
    """Return the user id of a valid, unexpired token we issued; otherwise None."""
    if settings.jwt_secret is None:
        return None
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            leeway=JWT_LEEWAY_SECONDS,
            options={"require": ["iss", "sub", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    subject = claims["sub"]
    return subject if isinstance(subject, str) and subject else None


def standalone_auth(paywall: PayWall) -> AuthDependency:
    bearer = HTTPBearer(
        auto_error=False,
        description="An API key (`pw_…`) or a user token from `POST /v1/auth/tokens`.",
    )

    async def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        x_user_id: Annotated[
            str | None,
            Header(
                alias="X-User-Id",
                min_length=1,
                max_length=255,
                description="API-key callers: the end user this request acts for.",
            ),
        ] = None,
    ) -> Principal | None:
        if credentials is None:
            return None
        credential = credentials.credentials
        if credential.startswith(KEY_PREFIX):
            key = await paywall.authenticate_api_key(credential)
            if key is None:
                return None
            return Principal(subject=f"apikey:{key.prefix}", user_id=x_user_id, scopes=key.scopes)
        # A user token is bound to its user; X-User-Id cannot widen it to anyone else.
        user_id = read_user_token(paywall.settings, credential)
        return None if user_id is None else Principal.user(user_id)

    return authenticate


async def internal_error(request: Request, _: Exception) -> JSONResponse:
    """Unexpected errors still get problem+json and the request id, to match the server log."""
    request_id: str | None = getattr(request.state, "request_id", None)
    return JSONResponse(
        problem_body(ErrorCode.INTERNAL_ERROR, "An unexpected error occurred.")
        | {"request_id": request_id},
        status_code=500,
        media_type=PROBLEM_MEDIA_TYPE,
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the server for ``settings``. Leaves logging alone (see ``app_factory``)."""
    settings = settings or Settings()
    paywall = PayWall(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await paywall.close()

    app = FastAPI(
        title="PayWall",
        version=__version__,
        summary="Closed-loop wallet API: balances, debits and an auditable double-entry ledger.",
        lifespan=lifespan,
    )
    app.state.paywall = paywall
    app.add_exception_handler(Exception, internal_error)
    auth = standalone_auth(paywall)
    app.include_router(create_router(paywall, auth=auth))
    app.include_router(
        create_admin_router(
            paywall,
            principal_dependency(auth),
            None
            if settings.jwt_secret is None
            else lambda user_id: issue_user_token(settings, user_id),
        )
    )
    return app


def app_factory() -> FastAPI:
    """Entry point for ``paywall serve`` or ``uvicorn --factory paywall.server:app_factory``.

    Configures logging from the environment first, then builds the app.
    """
    settings = Settings()
    configure_logging(settings)
    return create_app(settings)
