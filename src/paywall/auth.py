"""Who is calling, and what they may do. Framework-agnostic: the API layer only consumes these."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class Scope(StrEnum):
    WALLET_READ = "wallet:read"
    WALLET_WRITE = "wallet:write"
    ADMIN = "admin"


USER_SCOPES = frozenset({Scope.WALLET_READ, Scope.WALLET_WRITE})

# Each scope grants the ones listed here too. Writing implies reading: a debit's response
# already reveals the balance, so a write-only credential would be pointless.
IMPLIED_SCOPES = {
    Scope.ADMIN: frozenset(Scope),
    Scope.WALLET_WRITE: frozenset({Scope.WALLET_WRITE, Scope.WALLET_READ}),
    Scope.WALLET_READ: frozenset({Scope.WALLET_READ}),
}


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller of an API request.

    ``subject`` identifies the caller (``user:<id>``, ``apikey:<prefix>``, or anything a host
    chooses). It namespaces idempotency keys, so one caller can never replay another's response,
    and it is recorded as the actor of every ledger entry the request creates.
    ``user_id`` is the end user whose wallet ``/wallets/me`` refers to, if any.
    """

    subject: str
    user_id: str | None
    scopes: frozenset[Scope]

    @classmethod
    def user(cls, user_id: str) -> Self:
        """An end user acting on their own wallet."""
        return cls(subject=f"user:{user_id}", user_id=user_id, scopes=USER_SCOPES)

    def has(self, scope: Scope) -> bool:
        # .get: a host may build Principals from its own role strings; unknown ones grant nothing.
        return any(scope in IMPLIED_SCOPES.get(granted, ()) for granted in self.scopes)
