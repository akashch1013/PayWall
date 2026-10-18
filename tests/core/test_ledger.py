import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall.core.ledger import lock_wallets, post_entry, system_account
from paywall.db.models import Account, AccountKind, EntryType, JournalEntry, OutboxEvent, Posting
from paywall.observability import request_id_var

Sessions = async_sessionmaker[AsyncSession]


async def _wallet(session: AsyncSession, currency: str = "INR") -> uuid.UUID:
    account = Account(
        kind=AccountKind.USER_WALLET,
        external_user_id=uuid.uuid4().hex,
        currency=currency,
        balance=0,
    )
    session.add(account)
    await session.flush()
    return account.id


async def test_system_account_is_created_once(sessions: Sessions) -> None:
    currency = "XTS"  # ISO 4217 code reserved for testing; no other test touches it
    async with sessions() as session, session.begin():
        first = await system_account(session, AccountKind.APP_REVENUE, currency)
    async with sessions() as session, session.begin():
        second = await system_account(session, AccountKind.APP_REVENUE, currency)
        gateway = await system_account(session, AccountKind.GATEWAY_CLEARING, currency, "mock")

    assert first == second
    assert gateway != first


async def test_post_entry_updates_cached_wallet_balance(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        wallet = await _wallet(session)
        source = await system_account(session, AccountKind.ADJUSTMENTS, "INR")
        posted = await post_entry(
            session,
            type=EntryType.ADJUSTMENT,
            currency="INR",
            postings=[(source, -5000), (wallet, 5000)],
            actor="test",
            reference="ref_1",
        )

    assert posted.wallet_balances == {wallet: 5000}
    async with sessions() as session:
        account = await session.get_one(Account, wallet)
        total = await session.scalar(
            select(func.sum(Posting.amount)).where(Posting.account_id == wallet)
        )
    assert account.balance == total == 5000


async def test_post_entry_emits_one_event_per_wallet_posting(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        payer, payee = await _wallet(session), await _wallet(session)
        source = await system_account(session, AccountKind.ADJUSTMENTS, "INR")
        await post_entry(
            session,
            type=EntryType.ADJUSTMENT,
            currency="INR",
            postings=[(source, -300), (payer, 300)],
            actor="test",
        )
        posted = await post_entry(
            session,
            type=EntryType.TRANSFER,
            currency="INR",
            postings=[(payer, -100), (payee, 100)],
            actor="test",
            reference="t1",
        )

    async with sessions() as session:
        events = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.payload["entry_id"].astext == str(posted.entry_id))
                .order_by(OutboxEvent.id)
            )
        ).all()

    assert [(e.event_type, e.payload["amount"], e.payload["balance_after"]) for e in events] == [
        ("wallet.debited", -100, 200),
        ("wallet.credited", 100, 100),
    ]
    assert events[0].payload["reference"] == "t1"
    assert events[0].payload["entry_type"] == "TRANSFER"


@pytest.mark.parametrize(
    ("amounts", "message"),
    [
        pytest.param((100,), "at least two postings", id="single"),
        pytest.param((100, -99), "sum to zero", id="unbalanced"),
        pytest.param((0, 0), "non-zero", id="zero"),
    ],
)
async def test_post_entry_rejects_invalid_postings(
    sessions: Sessions, amounts: tuple[int, ...], message: str
) -> None:
    async with sessions() as session, session.begin():
        wallets = [await _wallet(session) for _ in amounts]
        with pytest.raises(ValueError, match=message):
            await post_entry(
                session,
                type=EntryType.ADJUSTMENT,
                currency="INR",
                postings=list(zip(wallets, amounts, strict=True)),
                actor="test",
            )


async def test_post_entry_rejects_repeated_account(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        a, b = await _wallet(session), await _wallet(session)
        with pytest.raises(ValueError, match="only once"):
            await post_entry(
                session,
                type=EntryType.TRANSFER,
                currency="INR",
                postings=[(a, -5), (b, 10), (a, -5)],
                actor="test",
            )


async def test_post_entry_rejects_mixed_currencies(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        inr, usd = await _wallet(session, "INR"), await _wallet(session, "USD")
        with pytest.raises(ValueError, match="currency"):
            await post_entry(
                session,
                type=EntryType.TRANSFER,
                currency="INR",
                postings=[(inr, -1), (usd, 1)],
                actor="test",
            )


async def test_post_entry_rejects_unknown_accounts(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        wallet = await _wallet(session)
        with pytest.raises(ValueError, match="unknown account"):
            await post_entry(
                session,
                type=EntryType.TRANSFER,
                currency="INR",
                postings=[(wallet, -1), (uuid.uuid4(), 1)],
                actor="test",
            )


async def test_lock_wallets_returns_only_wallets(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        a, b = await _wallet(session), await _wallet(session)
        revenue = await system_account(session, AccountKind.APP_REVENUE, "INR")

        locked = await lock_wallets(session, [b, revenue, a])

    assert set(locked) == {a, b}


async def test_post_entry_records_the_current_request_id(sessions: Sessions) -> None:
    token = request_id_var.set("req_test_123")
    try:
        async with sessions() as session, session.begin():
            wallet = await _wallet(session)
            source = await system_account(session, AccountKind.ADJUSTMENTS, "INR")
            posted = await post_entry(
                session,
                type=EntryType.ADJUSTMENT,
                currency="INR",
                postings=[(source, -1), (wallet, 1)],
                actor="test",
            )
    finally:
        request_id_var.reset(token)

    async with sessions() as session:
        entry = await session.get_one(JournalEntry, posted.entry_id)
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.payload["entry_id"].astext == str(posted.entry_id)
            )
        )
    assert entry.request_id == "req_test_123"
    assert event is not None
    assert event.request_id == "req_test_123"
