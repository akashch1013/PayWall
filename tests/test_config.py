import pytest
from pydantic import ValidationError

from paywall.config import Settings
from paywall.errors import ErrorCode, PayWallError

URL = "postgresql+asyncpg://u:p@localhost/db"


def test_defaults() -> None:
    settings = Settings(database_url=URL)

    assert settings.db_schema == "paywall"
    assert settings.default_currency == "INR"
    assert settings.tx_max_attempts == 3


@pytest.mark.parametrize("schema", ["Pay-Wall", "1paywall", 'pw"; DROP SCHEMA public; --'])
def test_rejects_unsafe_schema_names(schema: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=URL, db_schema=schema)


@pytest.mark.parametrize("currency", ["inr", "RUPEE", "IN"])
def test_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=URL, default_currency=currency)


def test_database_url_is_not_leaked_in_repr() -> None:
    assert "p@localhost" not in repr(Settings(database_url=URL))


def test_error_codes_carry_http_status_and_summary() -> None:
    error = PayWallError(ErrorCode.INSUFFICIENT_FUNDS, "Balance 1000 < amount 49900")

    assert error.code.status == 422
    assert error.code.summary == "Insufficient funds"
    assert str(error) == "Balance 1000 < amount 49900"


def test_jwt_secret_must_be_long_enough_for_hs256() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=URL, jwt_secret="too-short")

    assert Settings(database_url=URL).jwt_secret is None
