"""Runtime configuration, read from ``PAYWALL_*`` environment variables (or a ``.env`` file)."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYWALL_", env_file=".env", extra="ignore")

    # SecretStr: the URL carries the database password, so it must never show up in logs or reprs.
    database_url: SecretStr
    # Interpolated into DDL and search_path, so only plain lowercase identifiers are accepted.
    db_schema: str = Field("paywall", pattern=r"^[a-z_][a-z0-9_]*$", max_length=63)
    db_pool_size: int = Field(10, ge=1)
    db_max_overflow: int = Field(10, ge=0)
    db_pool_timeout: float = Field(10, gt=0)

    default_currency: str = Field("INR", pattern=r"^[A-Z]{3}$")
    tx_max_attempts: int = Field(3, ge=1)
    idempotency_ttl_hours: int = Field(24, ge=1)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # Standalone server only. Unset disables JWT user tokens. HS256 needs at least 256 bits of key.
    jwt_secret: SecretStr | None = Field(None, min_length=32)
    jwt_ttl_minutes: int = Field(60, ge=1, le=24 * 60)
