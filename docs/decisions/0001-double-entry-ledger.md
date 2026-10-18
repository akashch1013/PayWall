# 1. Store money as an append-only double-entry ledger

- **Status:** accepted
- **Date:** 2026-10-12

## Context

A wallet that stores only a `balance` column can't explain itself. Nothing records where a
balance came from. A bug that adds ₹10 twice leaves no trace, and an auditor can't rebuild
history. Payment systems also have to answer "where is the money?" for the app's own revenue,
promo spend and gateway float, not just for user wallets.

## Decision

- Every money movement is one **journal entry** with **two or more postings**. A posting is
  `(account, signed amount)`: positive increases that account's balance, negative decreases it.
- Every entry sums to **zero**. Money is only ever moved between accounts, never created or
  destroyed, so the sum of all postings in the system is always zero.
- System accounts (`APP_REVENUE`, `ADJUSTMENTS`, `PROMO_EXPENSE`, `GATEWAY_CLEARING`) are the
  other side of every user-wallet movement.
- Amounts are `bigint` minor units (paise). Floats are never used.
- `post_entry()` is the only code that writes ledger rows.
- The ledger is **append-only**. Mistakes are corrected with new entries (a reversal or an
  adjustment), never by editing old ones.

The database enforces the rules independently of the Python code:

- triggers reject `UPDATE`, `DELETE` and `TRUNCATE` on `journal_entries` and `postings`;
- a `DEFERRABLE INITIALLY DEFERRED` constraint trigger rejects, at `COMMIT`, any entry with fewer
  than two postings or a non-zero sum.

## Consequences

- Any balance can be recomputed as `SUM(postings)` and checked. The property test and the
  future `reconcile` command depend on this.
- Two layers have to agree: `post_entry` validates for clear error messages, and the triggers
  are the last defense against bugs or manual `psql` sessions.
- Storage grows with activity, not with the number of users. That is the price of an audit trail.
