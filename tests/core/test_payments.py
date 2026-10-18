import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall.core import payments, wallets
from paywall.core.ledger import lock_wallets, post_entry
from paywall.core.results import WalletEntry
from paywall.db.models import AccountStatus, EntryType, Posting
from paywall.errors import ErrorCode, PayWallError

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def tx(sessions: Sessions) -> Callable[..., Awaitable[WalletEntry]]:
    """Run one payments function in its own committed transaction."""

    async def run(fn: Callable[..., Awaitable[WalletEntry]], **kwargs: object) -> WalletEntry:
        async with sessions() as session, session.begin():
            return await fn(session, actor="test", **kwargs)

    return run


Tx = Callable[..., Awaitable[WalletEntry]]


async def _fund(tx: Tx, user_id: str, amount: int) -> WalletEntry:
    return await tx(payments.adjust, user_id=user_id, currency="INR", amount=amount, reason="seed")


async def _debit(tx: Tx, user_id: str, amount: int, reference: str = "order_1") -> WalletEntry:
    return await tx(
        payments.debit, user_id=user_id, currency="INR", amount=amount, reference=reference
    )


async def _balance(sessions: Sessions, user_id: str) -> int:
    async with sessions() as session, session.begin():
        return (await wallets.get_or_create_wallet(session, user_id, "INR")).balance


async def test_debit_moves_money_to_app_revenue(sessions: Sessions, tx: Tx, user_id: str) -> None:
    await _fund(tx, user_id, 100_000)

    entry = await _debit(tx, user_id, 49_900, reference="order_789")

    assert entry.type is EntryType.DEBIT
    assert (entry.amount, entry.balance_after, entry.reference) == (-49_900, 50_100, "order_789")
    assert await _balance(sessions, user_id) == 50_100
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.sum(Posting.amount)).where(Posting.entry_id == entry.entry_id)
            )
            == 0
        )


async def test_debit_rejects_insufficient_funds(sessions: Sessions, tx: Tx, user_id: str) -> None:
    await _fund(tx, user_id, 1_000)

    with pytest.raises(PayWallError) as error:
        await _debit(tx, user_id, 49_900)

    assert error.value.code is ErrorCode.INSUFFICIENT_FUNDS
    assert error.value.detail == "Balance 1000 < amount 49900"
    assert await _balance(sessions, user_id) == 1_000


async def test_debit_without_wallet_does_not_create_one(tx: Tx, user_id: str) -> None:
    with pytest.raises(PayWallError) as error:
        await _debit(tx, user_id, 100)

    assert error.value.code is ErrorCode.WALLET_NOT_FOUND


async def test_frozen_wallet_cannot_be_debited(sessions: Sessions, tx: Tx, user_id: str) -> None:
    await _fund(tx, user_id, 1_000)
    async with sessions() as session, session.begin():
        await wallets.set_status(
            session, user_id=user_id, currency="INR", status=AccountStatus.FROZEN
        )

    with pytest.raises(PayWallError) as error:
        await _debit(tx, user_id, 100)

    assert error.value.code is ErrorCode.WALLET_FROZEN


@pytest.mark.parametrize("amount", [0, -1, True, 1.5])
async def test_debit_rejects_invalid_amounts(tx: Tx, user_id: str, amount: object) -> None:
    await _fund(tx, user_id, 1_000)

    with pytest.raises(PayWallError) as error:
        await _debit(tx, user_id, amount)  # type: ignore[arg-type]

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_debit_requires_reference(tx: Tx, user_id: str) -> None:
    await _fund(tx, user_id, 1_000)

    with pytest.raises(PayWallError) as error:
        await _debit(tx, user_id, 100, reference=" ")

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_negative_adjustment_cannot_overdraw(
    sessions: Sessions, tx: Tx, user_id: str
) -> None:
    await _fund(tx, user_id, 500)

    with pytest.raises(PayWallError) as error:
        await _fund(tx, user_id, -501)
    entry = await _fund(tx, user_id, -500)

    assert error.value.code is ErrorCode.INSUFFICIENT_FUNDS
    assert (entry.amount, entry.balance_after) == (-500, 0)


async def test_adjustment_requires_reason(tx: Tx, user_id: str) -> None:
    with pytest.raises(PayWallError) as error:
        await tx(payments.adjust, user_id=user_id, currency="INR", amount=1, reason="")

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_reversal_restores_balance_once(sessions: Sessions, tx: Tx, user_id: str) -> None:
    await _fund(tx, user_id, 1_000)
    debit = await _debit(tx, user_id, 300)

    reversal = await tx(payments.reverse, entry_id=debit.entry_id, reason="order cancelled")
    with pytest.raises(PayWallError) as again:
        await tx(payments.reverse, entry_id=debit.entry_id, reason="twice")
    with pytest.raises(PayWallError) as of_reversal:
        await tx(payments.reverse, entry_id=reversal.entry_id, reason="undo the undo")

    assert reversal.type is EntryType.REVERSAL
    assert (reversal.amount, reversal.balance_after, reversal.reference) == (300, 1_000, "order_1")
    assert again.value.code is ErrorCode.ENTRY_ALREADY_REVERSED
    assert of_reversal.value.code is ErrorCode.VALIDATION_ERROR
    assert await _balance(sessions, user_id) == 1_000


async def test_spent_credit_cannot_be_reversed(tx: Tx, user_id: str) -> None:
    credit = await _fund(tx, user_id, 1_000)
    await _debit(tx, user_id, 600)

    with pytest.raises(PayWallError) as error:
        await tx(payments.reverse, entry_id=credit.entry_id, reason="chargeback")

    assert error.value.code is ErrorCode.INSUFFICIENT_FUNDS


async def test_entries_touching_two_wallets_cannot_be_reversed_yet(
    sessions: Sessions, tx: Tx, user_id: str
) -> None:
    await _fund(tx, user_id, 100)
    async with sessions() as session, session.begin():
        payer = await wallets.get_or_create_wallet(session, user_id, "INR")
        payee = await wallets.get_or_create_wallet(session, f"{user_id}_payee", "INR")
        await lock_wallets(session, [payer.id, payee.id])
        posted = await post_entry(
            session,
            type=EntryType.TRANSFER,
            currency="INR",
            postings=[(payer.id, -100), (payee.id, 100)],
            actor="test",
        )

    with pytest.raises(PayWallError) as error:
        await tx(payments.reverse, entry_id=posted.entry_id, reason="refund")

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_reversing_unknown_entry_is_not_found(tx: Tx) -> None:
    with pytest.raises(PayWallError) as error:
        await tx(payments.reverse, entry_id=uuid.uuid4(), reason="typo")

    assert error.value.code is ErrorCode.NOT_FOUND
