"""Assembles PayWall's ``/v1`` API from its parts. Shared by embedded and standalone modes."""

from typing import TYPE_CHECKING

from fastapi import APIRouter

from paywall.api.deps import AuthDependency, principal_dependency
from paywall.api.problems import ProblemRoute
from paywall.api.wallets import create_wallets_router

if TYPE_CHECKING:
    from paywall.app import PayWall


def create_router(paywall: "PayWall", *, auth: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/v1", route_class=ProblemRoute)
    router.include_router(create_wallets_router(paywall, principal_dependency(auth)))
    return router
