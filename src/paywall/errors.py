"""Business errors. Each code maps to one HTTP status, so the API layer can render them directly."""

from enum import StrEnum


class ErrorCode(StrEnum):
    status: int
    summary: str

    def __new__(cls, value: str, status: int, summary: str) -> "ErrorCode":
        member = str.__new__(cls, value)
        member._value_ = value
        member.status = status
        member.summary = summary
        return member

    IDEMPOTENCY_KEY_MISSING = "IDEMPOTENCY_KEY_MISSING", 400, "Idempotency-Key header is required"
    UNAUTHORIZED = "UNAUTHORIZED", 401, "Authentication required"
    FORBIDDEN = "FORBIDDEN", 403, "Not allowed"
    NOT_FOUND = "NOT_FOUND", 404, "Not found"
    WALLET_NOT_FOUND = "WALLET_NOT_FOUND", 404, "Wallet not found"
    IDEMPOTENCY_KEY_IN_PROGRESS = (
        "IDEMPOTENCY_KEY_IN_PROGRESS",
        409,
        "A request with this idempotency key is in progress",
    )
    WALLET_FROZEN = "WALLET_FROZEN", 409, "Wallet is frozen"
    ENTRY_ALREADY_REVERSED = "ENTRY_ALREADY_REVERSED", 409, "Entry already reversed"
    VALIDATION_ERROR = "VALIDATION_ERROR", 422, "Validation error"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS", 422, "Insufficient funds"
    INTERNAL_ERROR = "INTERNAL_ERROR", 500, "Internal error"
    IDEMPOTENCY_KEY_REUSED = (
        "IDEMPOTENCY_KEY_REUSED",
        422,
        "Idempotency key was already used with a different request",
    )


class PayWallError(Exception):
    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
