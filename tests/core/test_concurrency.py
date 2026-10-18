"""Spec test 1: concurrent debits can never spend the same money twice."""

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall import ErrorCode, PayWall, PayWallError, WalletEntry
from paywall.db.models import Posting


async def test_concurrent_debits_never_double_spend(
    paywall: PayWall, sessions: async_sessionmaker[AsyncSession], user_id: str
) -> None:
    # ₹100 in the wallet, 100 simultaneous ₹10 debits: exactly 10 can succeed.
    await paywall.adjust(user_id, 10_000, reason="seed", idempotency_key=uuid.uuid4().hex)

    async def debit(n: int) -> WalletEntry | PayWallError:
        try:
            return await paywall.debit(
                user_id, 1_000, reference=f"order_{n}", idempotency_key=uuid.uuid4().hex
            )
        except PayWallError as error:
            return error

    results = await asyncio.gather(*(debit(n) for n in range(100)))

    succeeded = [r for r in results if isinstance(r, WalletEntry)]
    failed = [r for r in results if isinstance(r, PayWallError)]
    assert len(succeeded) == 10
    assert {e.code for e in failed} == {ErrorCode.INSUFFICIENT_FUNDS}
    # Each success saw a distinct balance: the debits were applied strictly one after another.
    assert sorted(e.balance_after for e in succeeded) == list(range(0, 10_000, 1_000))

    wallet = await paywall.get_wallet(user_id)
    async with sessions() as session:
        posted_total = await session.scalar(
            select(func.sum(Posting.amount)).where(Posting.account_id == wallet.id)
        )
    assert wallet.balance == posted_total == 0
