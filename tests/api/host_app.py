"""A minimal host app embedding PayWall (Mode A), written the way a real user would.

The host keeps its own auth and routes. It gives PayWall one ``auth`` dependency that maps its
users to Principals, mounts PayWall's router under its own prefix, and calls the Python API from
its own business endpoints.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException

from paywall import PayWall, PayWallError, Principal, Scope
from paywall.auth import USER_SCOPES

ORDER_PRICE = 49_900


async def host_auth(
    x_demo_user: Annotated[str | None, Header()] = None,
    x_demo_role: Annotated[str | None, Header()] = None,
) -> Principal | None:
    """Stands in for the host's real session/cookie auth."""
    if x_demo_user is None:
        return None
    if x_demo_role == "banned":  # hosts often reject with their own HTTPException
        raise HTTPException(403, "Account suspended")
    if x_demo_role == "viewer":  # a user who may look but not spend
        return Principal(
            subject=f"user:{x_demo_user}",
            user_id=x_demo_user,
            scopes=frozenset({Scope.WALLET_READ}),
        )
    if x_demo_role == "billing-service":  # one backend identity acting for many users
        return Principal(subject="service:billing", user_id=x_demo_user, scopes=USER_SCOPES)
    if x_demo_role == "ops":  # staff with no wallet of their own
        return Principal(subject="ops:alice", user_id=None, scopes=frozenset({Scope.ADMIN}))
    return Principal.user(x_demo_user)


def create_host_app(paywall: PayWall) -> FastAPI:
    app = FastAPI(title="Demo shop")
    app.include_router(paywall.router, prefix="/wallet")

    @app.post("/orders/{order_id}/pay")
    async def pay_order(
        order_id: str, principal: Annotated[Principal | None, Depends(host_auth)]
    ) -> dict[str, int | str]:
        if principal is None or principal.user_id is None:
            raise HTTPException(401)
        try:
            entry = await paywall.debit(
                principal.user_id,
                ORDER_PRICE,
                reference=f"order_{order_id}",
                idempotency_key=f"order_{order_id}_pay",
            )
        except PayWallError as error:
            raise HTTPException(402, error.detail) from error
        return {"order_id": order_id, "balance": entry.balance_after}

    return app
