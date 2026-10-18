# 2. Serialize wallet updates with `SELECT … FOR UPDATE`

- **Status:** accepted
- **Date:** 2026-10-12

## Context

Two debits of ₹10 against a ₹10 balance can both read "10" and both succeed unless something
orders them. This is the classic double-spend. We considered three ways to prevent it:

| Option | Under contention |
|---|---|
| Optimistic locking (version column) | Losers fail and must retry. A hot wallet with 100 parallel debits retries over and over. |
| `SERIALIZABLE` isolation | Correct, but any transaction may abort with `40001`, every path needs retry, and predicate locks cause false-positive aborts. |
| **Row locks (`FOR UPDATE`) at READ COMMITTED** | Waiters queue on that one wallet row instead of failing. Simple to reason about. |

## Decision

Every mutating operation runs as one transaction (`run_tx`) in this order:

1. claim the idempotency key;
2. resolve system accounts (get-or-create), **before** any wallet lock is held;
3. `SELECT … FOR UPDATE` the wallets involved, **sorted by id**;
4. check business rules (frozen, sufficient funds) against the balance read under the lock;
5. `post_entry`, then store the idempotency response and `COMMIT`.

`run_tx` retries `40P01` (deadlock) and `40001` (serialization failure) up to 3 attempts with
jittered exponential backoff. A retry is safe because the rollback undid everything.

## Consequences

- Contention is per wallet. Unrelated wallets never wait for each other.
- Locking in a fixed order prevents A-waits-for-B-waits-for-A deadlocks. Resolving system
  accounts first stops a first-time system-account insert from waiting on another transaction
  while we hold a wallet lock.
- Locking selects use `populate_existing` because SQLAlchemy's identity map would otherwise keep
  a balance it read earlier, without the lock.
- Transactions must stay short. Gateway HTTP calls are never made while a wallet lock is held.
- Spec test 1 (100 parallel ₹10 debits on ₹100 → exactly 10 succeed) proves the approach.
