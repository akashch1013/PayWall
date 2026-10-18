"""``/v1/wallets/me``: the calling user's own wallet."""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime

from paywall.api.deps import IdempotencyKey, PrincipalDependency, end_user, requires, scope_for
from paywall.api.problems import AUTH_ERRORS, ProblemRoute, problem_responses
from paywall.api.schemas import DebitIn, EntryOut, TransactionOut, TransactionPageOut, WalletOut
from paywall.auth import Principal, Scope
from paywall.core import idempotency, payments
from paywall.core.wallets import MAX_PAGE_SIZE
from paywall.db.models import EntryType
from paywall.errors import ErrorCode

if TYPE_CHECKING:
    from paywall.app import PayWall

REPLAYED_HEADER = "Idempotent-Replayed"


def create_wallets_router(paywall: "PayWall", current: PrincipalDependency) -> APIRouter:
    router = APIRouter(prefix="/wallets/me", tags=["wallets"], route_class=ProblemRoute)
    Reader = Annotated[Principal, Depends(requires(Scope.WALLET_READ, current))]
    Writer = Annotated[Principal, Depends(requires(Scope.WALLET_WRITE, current))]

    @router.get("", summary="Get my wallet", responses=problem_responses(*AUTH_ERRORS))
    async def get_my_wallet(principal: Reader) -> WalletOut:
        """Return the caller's wallet and balance. The wallet is created, empty, on first use."""
        wallet = await paywall.get_wallet(end_user(principal))
        return WalletOut.model_validate(wallet)

    @router.get(
        "/transactions",
        summary="List my transactions",
        responses=problem_responses(*AUTH_ERRORS),
    )
    async def list_my_transactions(
        principal: Reader,
        cursor: Annotated[
            str | None,
            Query(
                pattern=r"^[1-9][0-9]{0,17}$",
                description="`next_cursor` from the previous page. Treat it as opaque.",
            ),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
        types: Annotated[
            list[EntryType] | None,
            Query(alias="type", description="Only these entry types (repeat the parameter)."),
        ] = None,
        since: Annotated[
            AwareDatetime | None,
            Query(alias="from", description="Inclusive lower bound. Must include a timezone."),
        ] = None,
        until: Annotated[
            AwareDatetime | None,
            Query(alias="to", description="Exclusive upper bound. Must include a timezone."),
        ] = None,
    ) -> TransactionPageOut:
        """Newest first. Each item is one change to the wallet balance."""
        page = await paywall.history(
            end_user(principal),
            cursor=None if cursor is None else int(cursor),
            limit=limit,
            types=types,
            since=since,
            until=until,
        )
        return TransactionPageOut(
            items=[TransactionOut.model_validate(t) for t in page.items],
            next_cursor=None if page.next_cursor is None else str(page.next_cursor),
        )

    @router.post(
        "/debits",
        status_code=201,
        summary="Spend from my wallet",
        responses=problem_responses(
            ErrorCode.IDEMPOTENCY_KEY_MISSING,
            *AUTH_ERRORS,
            ErrorCode.WALLET_NOT_FOUND,
            ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS,
            ErrorCode.WALLET_FROZEN,
            ErrorCode.INSUFFICIENT_FUNDS,
            ErrorCode.IDEMPOTENCY_KEY_REUSED,
        ),
    )
    async def debit_my_wallet(
        body: DebitIn,
        principal: Writer,
        key: IdempotencyKey,
        response: Response,
    ) -> EntryOut:
        """Pay `amount` from the caller's wallet to the app, e.g. for an order.

        Retrying with the same `Idempotency-Key` and body returns the original result with
        `Idempotent-Replayed: true`, and never charges twice. The same key with a different body
        is rejected (422). Hosts should prefer debiting from their backend (Python API or an API
        key), where the order is known to exist.
        """
        user_id = end_user(principal)
        entry, replayed = await paywall.run_idempotent(
            scope=scope_for(principal),
            key=key,
            # The user is part of the request: one API key acting for two users with the same
            # key and body must not get one user's debit replayed to the other.
            # Named by operation, not URL: a retry through another mount path or proxy prefix
            # is still the same debit.
            fingerprint=idempotency.fingerprint(
                "wallets.debit", {"user_id": user_id, "body": body.model_dump(mode="json")}
            ),
            operation=lambda session: payments.debit(
                session,
                user_id=user_id,
                currency=paywall.currency,
                amount=body.amount,
                reference=body.reference,
                metadata=body.metadata,
                actor=principal.subject,
            ),
        )
        if replayed:
            response.headers[REPLAYED_HEADER] = "true"
        return EntryOut.model_validate(entry)

    return router
