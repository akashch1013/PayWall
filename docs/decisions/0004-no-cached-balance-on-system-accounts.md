# 4. Cache balances on user wallets only

- **Status:** accepted
- **Date:** 2026-10-12

## Context

Reading a wallet balance as `SUM(postings)` on every request is slow for active users, so user
wallets cache `balance` and every posting updates it in the same transaction. The obvious next
step would be to cache every account's balance the same way.

But system accounts sit on the other side of almost every movement. `APP_REVENUE` receives
every debit from every user. Updating its cached balance would take a row lock on that one row
in every debit transaction, so all debits in the system would queue behind each other. That
defeats the per-wallet locking in ADR 2.

## Decision

- Only `USER_WALLET` accounts have a non-NULL `balance`. A CHECK constraint enforces it:
  `(kind = 'USER_WALLET') = (balance IS NOT NULL)`.
- System account balances are computed with `SUM(postings)` when they are needed (admin stats,
  reconciliation), which is rare.
- `CHECK (balance >= 0)` is the database's last defense against a negative wallet.

## Consequences

- Debits for different users never block each other, even though they all post to the same
  `APP_REVENUE` account. Inserting a posting only takes the foreign-key check's `FOR KEY SHARE`
  lock on the account row, and those locks don't conflict with each other. Under heavy load,
  many concurrent key-share lockers on one row do create MultiXact overhead. That is far cheaper
  than an exclusive row lock, but it is a known cost to watch in load tests.
- Nothing may take `FOR UPDATE` on a system account row: that would conflict with every
  concurrent posting to it.
- Cached balances can be verified: `balance = SUM(postings)` for every wallet is checked by the
  property test and later by `paywall reconcile`.
- Reports on system accounts cost an aggregate query. The `(account_id, id DESC)` index on
  postings keeps that acceptable.
