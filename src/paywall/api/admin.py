"""Standalone-server administration: API keys and user tokens. Requires the ``admin`` scope.

Key creation and token minting are exempt from Idempotency-Key: their responses contain secrets,
and storing a response for replay would mean storing the secret. Repeating them is harmless
(an extra key can be revoked; tokens simply expire).
"""

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends

from paywall.api.deps import PrincipalDependency, requires
from paywall.api.problems import AUTH_ERRORS, ProblemRoute, problem_responses
from paywall.api.schemas import ApiKeyCreatedOut, ApiKeyIn, ApiKeyOut, TokenIn, TokenOut
from paywall.auth import Principal, Scope
from paywall.errors import ErrorCode

if TYPE_CHECKING:
    from paywall.app import PayWall


type TokenIssuer = Callable[[str], tuple[str, int]]
"""Mints a user token: user_id -> (token, seconds until expiry)."""


def create_admin_router(
    paywall: "PayWall", current: PrincipalDependency, issue_token: TokenIssuer | None
) -> APIRouter:
    """``issue_token`` is None when JWT is disabled; the token route is then not mounted."""
    router = APIRouter(prefix="/v1", route_class=ProblemRoute)
    Admin = Annotated[Principal, Depends(requires(Scope.ADMIN, current))]

    @router.post(
        "/admin/api-keys",
        status_code=201,
        tags=["admin"],
        summary="Create an API key",
        responses=problem_responses(*AUTH_ERRORS),
    )
    async def create_api_key(body: ApiKeyIn, _: Admin) -> ApiKeyCreatedOut:
        """The key is returned once and only its hash is stored. `admin` implies all scopes."""
        info, key = await paywall.create_api_key(body.name, body.scopes)
        return ApiKeyCreatedOut(**ApiKeyOut.from_key(info).model_dump(), key=key)

    @router.get(
        "/admin/api-keys",
        tags=["admin"],
        summary="List API keys",
        responses=problem_responses(*AUTH_ERRORS),
    )
    async def list_api_keys(_: Admin) -> list[ApiKeyOut]:
        """All keys, oldest first, including revoked ones. Secrets are never returned."""
        return [ApiKeyOut.from_key(k) for k in await paywall.list_api_keys()]

    @router.delete(
        "/admin/api-keys/{key_id}",
        tags=["admin"],
        summary="Revoke an API key",
        responses=problem_responses(*AUTH_ERRORS, ErrorCode.NOT_FOUND),
    )
    async def revoke_api_key(key_id: uuid.UUID, _: Admin) -> ApiKeyOut:
        """Takes effect on the next request. Revoking an already revoked key changes nothing."""
        return ApiKeyOut.from_key(await paywall.revoke_api_key(key_id))

    if issue_token is not None:

        @router.post(
            "/auth/tokens",
            tags=["auth"],
            summary="Mint a user token",
            responses=problem_responses(*AUTH_ERRORS),
        )
        async def mint_user_token(body: TokenIn, _: Admin) -> TokenOut:
            """For your backend: after your own login, mint a short-lived token that lets a
            browser or mobile app call `/v1/wallets/me` as that user, and nothing else."""
            token, expires_in = issue_token(body.user_id)
            return TokenOut(access_token=token, expires_in=expires_in)

    return router
