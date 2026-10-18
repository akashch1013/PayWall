import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall import PayWall, WalletEntry
from paywall.core.idempotency import StoredResponse, claim, fingerprint, store
from paywall.db.models import JournalEntry
from paywall.errors import ErrorCode, PayWallError

Sessions = async_sessionmaker[AsyncSession]
TTL = timedelta(hours=1)


def test_fingerprint_ignores_argument_order() -> None:
    assert fingerprint("debit", {"a": 1, "b": "x"}) == fingerprint("debit", {"b": "x", "a": 1})


def test_fingerprint_depends_on_operation_and_arguments() -> None:
    base = fingerprint("debit", {"amount": 100})

    assert fingerprint("debit", {"amount": 101}) != base
    assert fingerprint("adjust", {"amount": 100}) != base
    assert len(base) == 64


async def test_completed_key_replays_stored_response(sessions: Sessions) -> None:
    key, fp = uuid.uuid4().hex, fingerprint("op", {})
    async with sessions() as session, session.begin():
        assert await claim(session, scope="test", key=key, fingerprint=fp) is None
        await store(
            session,
            scope="test",
            key=key,
            fingerprint=fp,
            response_code=201,
            response_body={"ok": True},
            ttl=TTL,
        )

    async with sessions() as session, session.begin():
        stored = await claim(session, scope="test", key=key, fingerprint=fp)

    assert stored == StoredResponse(status_code=201, body={"ok": True})


async def test_same_key_in_another_scope_is_independent(sessions: Sessions) -> None:
    key, fp = uuid.uuid4().hex, fingerprint("op", {})
    async with sessions() as session, session.begin():
        await store(
            session,
            scope="a",
            key=key,
            fingerprint=fp,
            response_code=201,
            response_body={},
            ttl=TTL,
        )
        assert await claim(session, scope="b", key=key, fingerprint=fp) is None


async def test_key_reused_with_different_request_is_rejected(sessions: Sessions) -> None:
    key = uuid.uuid4().hex
    async with sessions() as session, session.begin():
        await store(
            session,
            scope="test",
            key=key,
            fingerprint=fingerprint("op", {"amount": 1}),
            response_code=201,
            response_body={},
            ttl=TTL,
        )

    async with sessions() as session, session.begin():
        with pytest.raises(PayWallError) as error:
            await claim(
                session, scope="test", key=key, fingerprint=fingerprint("op", {"amount": 2})
            )
    assert error.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED


async def test_key_held_by_running_transaction_is_in_progress(sessions: Sessions) -> None:
    key, fp = uuid.uuid4().hex, fingerprint("op", {})
    async with sessions() as first, first.begin():
        await claim(first, scope="test", key=key, fingerprint=fp)

        async with sessions() as second, second.begin():
            with pytest.raises(PayWallError) as error:
                await claim(second, scope="test", key=key, fingerprint=fp)
    assert error.value.code is ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS


async def test_expired_key_is_ignored_and_overwritten(sessions: Sessions) -> None:
    key = uuid.uuid4().hex
    old, new = fingerprint("op", {"v": 1}), fingerprint("op", {"v": 2})
    async with sessions() as session, session.begin():
        await store(
            session,
            scope="test",
            key=key,
            fingerprint=old,
            response_code=201,
            response_body={"v": 1},
            ttl=-TTL,
        )

    async with sessions() as session, session.begin():
        assert await claim(session, scope="test", key=key, fingerprint=new) is None
        await store(
            session,
            scope="test",
            key=key,
            fingerprint=new,
            response_code=201,
            response_body={"v": 2},
            ttl=TTL,
        )

    async with sessions() as session, session.begin():
        assert await claim(session, scope="test", key=key, fingerprint=new) == StoredResponse(
            status_code=201, body={"v": 2}
        )


async def test_concurrent_requests_with_one_key_execute_once(
    paywall: PayWall, sessions: Sessions, user_id: str
) -> None:
    """Spec test 3: 20 simultaneous retries of one request create exactly one ledger entry."""
    await paywall.adjust(user_id, 10_000, reason="seed", idempotency_key=uuid.uuid4().hex)
    key, reference = uuid.uuid4().hex, f"order_{uuid.uuid4().hex}"

    async def attempt() -> WalletEntry | PayWallError:
        try:
            return await paywall.debit(user_id, 100, reference=reference, idempotency_key=key)
        except PayWallError as error:
            return error

    results = await asyncio.gather(*(attempt() for _ in range(20)))

    entries = {r.entry_id for r in results if isinstance(r, WalletEntry)}
    errors = {r.code for r in results if isinstance(r, PayWallError)}
    assert len(entries) == 1
    assert errors <= {ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS}
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).where(JournalEntry.reference == reference))
            == 1
        )
    assert (await paywall.get_wallet(user_id)).balance == 9_900

    # After the race, a retry replays; the same key with another amount is rejected.
    replay = await paywall.debit(user_id, 100, reference=reference, idempotency_key=key)
    with pytest.raises(PayWallError) as error:
        await paywall.debit(user_id, 200, reference=reference, idempotency_key=key)
    assert replay.entry_id in entries
    assert error.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED
