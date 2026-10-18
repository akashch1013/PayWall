"""Spec test 6: random operation sequences never break the ledger's invariants."""

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paywall import ErrorCode, PayWall, PayWallError, WalletEntry

USERS = 3
# Business rejections each operation may legitimately hit; anything else is a bug.
EXPECTED_ERRORS = {
    "adjust": {ErrorCode.INSUFFICIENT_FUNDS},
    "debit": {ErrorCode.INSUFFICIENT_FUNDS},
    "reverse": {
        ErrorCode.INSUFFICIENT_FUNDS,  # the credit was already spent
        ErrorCode.ENTRY_ALREADY_REVERSED,
        ErrorCode.VALIDATION_ERROR,  # reversing a reversal
    },
}

operations = st.lists(
    st.one_of(
        st.tuples(
            st.just("adjust"),
            st.integers(0, USERS - 1),
            st.integers(-5_000, 20_000).filter(bool),
        ),
        st.tuples(st.just("debit"), st.integers(0, USERS - 1), st.integers(1, 10_000)),
        # The middle value picks one of the entries created so far.
        st.tuples(st.just("reverse"), st.integers(0, 30), st.just(0)),
    ),
    max_size=15,
)

# Each query returns the rows that violate one invariant; all must come back empty.
VIOLATIONS = {
    "entry does not sum to zero or has < 2 postings": """
        SELECT e.id FROM journal_entries e LEFT JOIN postings p ON p.entry_id = e.id
        GROUP BY e.id HAVING count(p.id) < 2 OR coalesce(sum(p.amount), 0) <> 0
    """,
    "cached wallet balance differs from its postings": """
        SELECT a.id FROM accounts a LEFT JOIN postings p ON p.account_id = a.id
        WHERE a.kind = 'USER_WALLET'
        GROUP BY a.id, a.balance HAVING a.balance <> coalesce(sum(p.amount), 0)
    """,
    "postings across the whole system do not sum to zero": """
        SELECT 1 FROM postings HAVING sum(amount) <> 0
    """,
}


@settings(max_examples=40, deadline=None)
@given(ops=operations)
async def test_ledger_invariants_hold(
    paywall: PayWall, sessions: async_sessionmaker[AsyncSession], ops: list[tuple[str, int, int]]
) -> None:
    users = [f"prop_{uuid.uuid4().hex}" for _ in range(USERS)]
    expected = dict.fromkeys(users, 0)
    entries: list[WalletEntry] = []
    for user in users:
        await paywall.get_wallet(user)

    for op, target, amount in ops:
        key = uuid.uuid4().hex
        try:
            if op == "adjust":
                entry = await paywall.adjust(
                    users[target], amount, reason="property test", idempotency_key=key
                )
            elif op == "debit":
                entry = await paywall.debit(
                    users[target], amount, reference="prop", idempotency_key=key
                )
            elif entries:
                original = entries[target % len(entries)]
                entry = await paywall.reverse(
                    original.entry_id, reason="property test", idempotency_key=key
                )
            else:
                continue
        except PayWallError as error:
            assert error.code in EXPECTED_ERRORS[op], error
            continue
        entries.append(entry)
        expected[entry.user_id] += entry.amount
        assert entry.balance_after == expected[entry.user_id]

    for user in users:
        assert (await paywall.get_wallet(user)).balance == expected[user] >= 0

    async with sessions() as session:
        for invariant, query in VIOLATIONS.items():
            assert (await session.execute(text(query))).all() == [], invariant
