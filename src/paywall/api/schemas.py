"""Request and response bodies. Amounts are integers in minor units (paise for INR)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from paywall.auth import Scope
from paywall.core.apikeys import ApiKey
from paywall.db.models import AccountStatus, EntryType

# Largest value a Postgres bigint holds; anything above would fail in the database instead.
MAX_AMOUNT = 2**63 - 1

Amount = Annotated[int, Field(gt=0, le=MAX_AMOUNT, strict=True, examples=[49900])]
Reference = Annotated[str, Field(min_length=1, max_length=255, examples=["order_789"])]
Metadata = Annotated[
    dict[str, Any],
    Field(max_length=20, description="Free-form key/values stored with the entry (≤ 20 keys)."),
]


class Model(BaseModel):
    # Lets responses be built straight from core dataclasses: Model.model_validate(result).
    model_config = ConfigDict(from_attributes=True)


class WalletOut(Model):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "user_42",
                    "currency": "INR",
                    "balance": 50100,
                    "status": "active",
                    "created_at": "2026-10-12T09:30:00Z",
                }
            ]
        }
    )

    user_id: str
    currency: str
    balance: int
    status: AccountStatus
    created_at: datetime


class TransactionOut(Model):
    entry_id: uuid.UUID
    type: EntryType
    amount: int = Field(description="Change to the wallet balance: negative means money out.")
    reference: str | None
    metadata: dict[str, Any]
    created_at: datetime


class TransactionPageOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "entry_id": "6f1c2d1e-8a8b-4b55-9a52-0f3e2b9c1a77",
                            "type": "DEBIT",
                            "amount": -49900,
                            "reference": "order_789",
                            "metadata": {"sku": "TSHIRT-M"},
                            "created_at": "2026-10-12T09:31:00Z",
                        }
                    ],
                    "next_cursor": "1042",
                }
            ]
        }
    )

    items: list[TransactionOut]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to fetch the next (older) page; null on the last page."
    )


class DebitIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"amount": 49900, "reference": "order_789", "metadata": {"sku": "TSHIRT-M"}}
            ]
        },
    )

    amount: Amount
    reference: Reference
    metadata: Metadata | None = None


class EntryOut(Model):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "entry_id": "6f1c2d1e-8a8b-4b55-9a52-0f3e2b9c1a77",
                    "type": "DEBIT",
                    "user_id": "user_42",
                    "amount": -49900,
                    "currency": "INR",
                    "balance_after": 50100,
                    "reference": "order_789",
                    "created_at": "2026-10-12T09:31:00Z",
                }
            ]
        }
    )

    entry_id: uuid.UUID
    type: EntryType
    user_id: str
    amount: int = Field(description="Change to the wallet balance: negative means money out.")
    currency: str
    balance_after: int
    reference: str | None
    created_at: datetime


class ApiKeyIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "shop-backend", "scopes": ["wallet:write"]}]},
    )

    name: Annotated[str, Field(min_length=1, max_length=100)]
    scopes: Annotated[list[Scope], Field(min_length=1)]


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str = Field(description="Public part of the key; identifies it in logs and listings.")
    scopes: list[Scope]
    created_at: datetime
    revoked_at: datetime | None

    @classmethod
    def from_key(cls, key: ApiKey) -> Self:
        return cls(
            id=key.id,
            name=key.name,
            prefix=key.prefix,
            scopes=sorted(key.scopes),
            created_at=key.created_at,
            revoked_at=key.revoked_at,
        )


class ApiKeyCreatedOut(ApiKeyOut):
    key: str = Field(description="The API key. Shown only in this response; store it now.")


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"user_id": "u42"}]})

    user_id: Annotated[str, Field(min_length=1, max_length=255)]


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # OAuth type name, not a secret
    expires_in: int = Field(description="Seconds until the token expires.")
