# 3. Track in-flight idempotency keys with advisory locks, not status rows

- **Status:** accepted
- **Date:** 2026-10-12

## Context

Clients retry: after a timeout, after a mobile app reconnects, after a gateway redelivers a
webhook. A retried "debit ₹499" must not charge twice. The usual design stores the key with
status `in_progress`, runs the work, then sets status `completed`. That design has two problems:

- If the `in_progress` row is written in the **same** transaction as the work, other
  transactions can't see it until commit, so a concurrent duplicate isn't detected.
- If it is written in **its own** transaction, a crash between the two leaves the key
  `in_progress` forever, and the client can never retry.

## Decision

"In progress" is a **transaction-scoped advisory lock** on a 64-bit hash of `(scope, key)`:

1. `pg_try_advisory_xact_lock(hash)`. If it fails, a request with this key is running right
   now, so return **409 `IDEMPOTENCY_KEY_IN_PROGRESS`**.
2. Look up a completed, unexpired row for `(scope, key)`:
   - same request fingerprint (SHA-256 of the operation and canonical JSON arguments): return the
     stored response without running anything;
   - different fingerprint: return **422 `IDEMPOTENCY_KEY_REUSED`**.
3. Otherwise do the work, insert the response row, and `COMMIT`.

Postgres releases the lock automatically on commit, rollback, or a dropped connection.

## Consequences

- A key can't get stuck. A crash releases the lock, and a retry runs the operation again.
- Only successes are stored. A business failure (such as insufficient funds) rolls back, so
  retrying with the same key re-evaluates instead of replaying the failure.
- A hash collision between two keys can only cause a spurious 409, never a wrong replay. The
  row lookup uses the exact `(scope, key)`.
- Keys are scoped (`app` for the Python API, and per caller once the HTTP API exists), so two
  callers can't collide or read each other's responses.
- Spec test 3 (20 concurrent calls with one key → exactly one ledger entry) proves it.
