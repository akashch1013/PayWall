import uuid

import pytest

from paywall import AccountStatus, EntryType, ErrorCode, PayWall, PayWallError


def _key() -> str:
    return uuid.uuid4().hex


async def test_from_env_reads_paywall_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYWALL_DATABASE_URL", "postgresql+asyncpg://u:p@db.internal/app")
    monkeypatch.setenv("PAYWALL_DEFAULT_CURRENCY", "USD")

    wallet = PayWall.from_env()
    try:
        assert wallet.settings.default_currency == "USD"
        assert wallet.engine.url.host == "db.internal"
    finally:
        await wallet.close()


async def test_get_wallet_creates_an_empty_wallet(paywall: PayWall, user_id: str) -> None:
    wallet = await paywall.get_wallet(user_id)

    assert (wallet.user_id, wallet.balance, wallet.currency) == (user_id, 0, "INR")
    assert wallet.status is AccountStatus.ACTIVE


async def test_debit_with_same_key_is_charged_once(paywall: PayWall, user_id: str) -> None:
    await paywall.adjust(user_id, 1_000, reason="seed", idempotency_key=_key())
    key = _key()

    first = await paywall.debit(user_id, 300, reference="order_1", idempotency_key=key)
    replay = await paywall.debit(user_id, 300, reference="order_1", idempotency_key=key)

    assert replay == first
    assert (await paywall.get_wallet(user_id)).balance == 700


async def test_reusing_a_key_for_another_request_is_rejected(
    paywall: PayWall, user_id: str
) -> None:
    await paywall.adjust(user_id, 1_000, reason="seed", idempotency_key=_key())
    key = _key()
    await paywall.debit(user_id, 300, reference="order_1", idempotency_key=key)

    with pytest.raises(PayWallError) as error:
        await paywall.debit(user_id, 301, reference="order_1", idempotency_key=key)

    assert error.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED


async def test_reusing_a_key_for_another_user_is_rejected(paywall: PayWall, user_id: str) -> None:
    key = _key()
    await paywall.adjust(user_id, 100, reason="seed", idempotency_key=key)

    with pytest.raises(PayWallError) as error:
        await paywall.adjust(f"{user_id}_other", 100, reason="seed", idempotency_key=key)

    assert error.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED


async def test_reusing_a_key_as_another_actor_is_rejected(paywall: PayWall, user_id: str) -> None:
    key = _key()
    await paywall.adjust(user_id, 100, reason="seed", idempotency_key=key, actor="ops_a")

    with pytest.raises(PayWallError) as error:
        await paywall.adjust(user_id, 100, reason="seed", idempotency_key=key, actor="ops_b")

    assert error.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED


async def test_failed_operation_can_be_retried_with_same_key(
    paywall: PayWall, user_id: str
) -> None:
    key = _key()
    await paywall.get_wallet(user_id)
    with pytest.raises(PayWallError):
        await paywall.debit(user_id, 500, reference="order_1", idempotency_key=key)

    await paywall.adjust(user_id, 500, reason="seed", idempotency_key=_key())
    entry = await paywall.debit(user_id, 500, reference="order_1", idempotency_key=key)

    assert entry.balance_after == 0


async def test_blank_idempotency_key_is_rejected(paywall: PayWall, user_id: str) -> None:
    with pytest.raises(PayWallError) as error:
        await paywall.adjust(user_id, 100, reason="seed", idempotency_key=" ")

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_reverse_freeze_and_history(paywall: PayWall, user_id: str) -> None:
    await paywall.adjust(user_id, 1_000, reason="seed", idempotency_key=_key())
    debit = await paywall.debit(user_id, 400, reference="order_9", idempotency_key=_key())
    await paywall.freeze(user_id)

    # Frozen wallets still accept reversals (money coming back) but not debits.
    reversal = await paywall.reverse(
        debit.entry_id, reason="order cancelled", idempotency_key=_key()
    )
    with pytest.raises(PayWallError) as error:
        await paywall.debit(user_id, 1, reference="order_10", idempotency_key=_key())
    unfrozen = await paywall.unfreeze(user_id)
    page = await paywall.history(user_id)

    assert reversal.balance_after == 1_000
    assert error.value.code is ErrorCode.WALLET_FROZEN
    assert unfrozen.status is AccountStatus.ACTIVE
    assert [t.type for t in page.items] == [
        EntryType.REVERSAL,
        EntryType.DEBIT,
        EntryType.ADJUSTMENT,
    ]
