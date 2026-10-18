# Phase 1: Ledger Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A correct, concurrency-safe double-entry wallet core (debit, adjust, reverse, freeze, history) usable from Python through the `PayWall` facade, with its schema installed by `paywall migrate`.

**Architecture:** `core/` functions take an `AsyncSession` and plain arguments and return frozen dataclasses. The `PayWall` facade runs each operation in one `run_tx()` transaction that claims the idempotency key, locks rows in a fixed order, posts through `post_entry()` (the only ledger writer) and stores the response. Postgres triggers enforce immutability and balanced entries as a last line of defense.

**Tech Stack:** Python 3.12, SQLAlchemy 2.1 async + asyncpg, Alembic, pydantic-settings, Typer, pytest + pytest-asyncio + Hypothesis, PostgreSQL 16+.

**Spec:** `docs/superpowers/specs/2026-10-11-paywall-design.md` (sections 3, 4, 5, 8, 9, 10).

## Global Constraints

- Money is `int` minor units (paise). Never `float`.
- Sign convention: `posting.amount > 0` increases that account's balance; every entry sums to 0.
- Only `USER_WALLET` accounts cache `balance`; system accounts never do.
- Lock order inside a transaction: resolve system accounts first, then `SELECT … FOR UPDATE` wallets sorted by id.
- Idempotency "in progress" is `pg_try_advisory_xact_lock`, never a status row. Only successful results are stored.
- Retry only SQLSTATE `40P01` and `40001`, at most `TX_MAX_ATTEMPTS` (default 3) attempts, sleep `0.05·2ⁿ·random()` seconds.
- The schema name comes from `PAYWALL_DB_SCHEMA` (default `paywall`), validated as `^[a-z_][a-z0-9_]*$`, applied through the connection `search_path`.
- No stubs, no TODOs. Tables, settings and error codes are added in the phase that first uses them.

## Review Focus

1. A debit racing a reversal of a top-up on the same wallet: the wallet must never go negative (covered by wallet row lock + balance check; test in Task 6).
2. Reversing the same entry twice concurrently: exactly one reversal (wallet lock serializes, partial unique index is last defense; test in Task 6).
3. Debiting a user who has no wallet: `WALLET_NOT_FOUND`, not a silently created empty wallet (Task 6).
4. Re-using an idempotency key with different arguments, including for a different user: `IDEMPOTENCY_KEY_REUSED` (Task 7).
5. Non-positive or boolean amounts: `VALIDATION_ERROR` before any SQL runs (Task 6).

---

### Task 1: Dependencies, settings and errors

**Files:** Modify `pyproject.toml`; create `src/paywall/config.py`, `src/paywall/errors.py`; test `tests/test_config.py`.

**Interfaces — produces:**
- `Settings` (pydantic-settings, prefix `PAYWALL_`, `.env`): `database_url: SecretStr`, `db_schema="paywall"`, `db_pool_size=10`, `db_max_overflow=10`, `db_pool_timeout=10`, `default_currency="INR"`, `tx_max_attempts=3`, `idempotency_ttl_hours=24`.
- `ErrorCode(StrEnum)` with `.status: int` and `.title: str`; Phase 1 codes: `VALIDATION_ERROR` 422, `NOT_FOUND` 404, `WALLET_NOT_FOUND` 404, `WALLET_FROZEN` 409, `INSUFFICIENT_FUNDS` 422, `IDEMPOTENCY_KEY_IN_PROGRESS` 409, `IDEMPOTENCY_KEY_REUSED` 422, `ENTRY_ALREADY_REVERSED` 409.
- `PayWallError(code: ErrorCode, detail: str)`.

- [ ] Test: invalid schema name (`"Pay-Wall"`) and lowercase currency raise `ValidationError`; `ErrorCode.INSUFFICIENT_FUNDS.status == 422`.
- [ ] Implement; `uv add alembic typer`, `uv add --dev hypothesis`.
- [ ] Commit `feat(config): add settings and error codes`.

### Task 2: Models, initial migration, migrate

**Files:** `src/paywall/db/models.py`, `src/paywall/db/migrations/env.py`, `src/paywall/db/migrations/versions/0001_ledger.py`, `src/paywall/db/migrate.py`, `src/paywall/db/session.py` (`create_engine`); tests `tests/db/test_schema.py`; modify `tests/conftest.py`.

**Interfaces — produces:**
- Tables (spec §3): `accounts`, `journal_entries`, `postings`, `idempotency_keys` (no `status` column: rows are only ever "completed"), `outbox_events`.
- `AccountKind`, `AccountStatus`, `EntryType` StrEnums (full vocabulary from spec §3).
- `create_engine(settings) -> AsyncEngine` sets `server_settings={"search_path": schema}`.
- `async upgrade(engine, schema) -> None` runs Alembic `upgrade head` on a connection passed via `config.attributes["connection"]`.
- Triggers: append-only (`UPDATE`/`DELETE`/`TRUNCATE`) on `journal_entries`, `postings`; deferred constraint trigger on both tables checking ≥2 postings and `SUM = 0` per entry. Functions use `SET search_path FROM CURRENT`.
- conftest: session fixtures `settings`, `engine` (migrated), `sessions`.

- [ ] Tests: UPDATE/DELETE on postings and journal_entries raise; an entry with one posting, or postings summing ≠ 0, fails at COMMIT; negative wallet balance violates CHECK; migrated schema matches models (`alembic.autogenerate.compare_metadata` is empty).
- [ ] Implement, run, commit `feat(db): add ledger schema, triggers and migrations`.

### Task 3: `run_tx` with retry

**Files:** `src/paywall/db/session.py`; test `tests/db/test_session.py`.

**Interfaces — produces:** `async run_tx(sessions: async_sessionmaker[AsyncSession], fn: Callable[[AsyncSession], Awaitable[T]], *, max_attempts: int) -> T`.

- [ ] Tests: fn raising `40P01` on attempt 1 then succeeding → result returned, 2 calls; always `40001` → raises after exactly `max_attempts` calls; other DB error → 1 call; `PayWallError` → rollback, re-raised, nothing committed. Errors raised via `DO $$ BEGIN RAISE EXCEPTION USING ERRCODE = '40P01'; END $$`.
- [ ] Implement, commit `feat(db): add run_tx with deadlock and serialization retry`.

### Task 4: Ledger + outbox emit

**Files:** `src/paywall/core/ledger.py`, `src/paywall/core/outbox.py`; test `tests/core/test_ledger.py`.

**Interfaces — produces:**
- `async system_account(session, kind: AccountKind, currency: str, gateway: str | None = None) -> uuid.UUID` (get-or-create, `ON CONFLICT DO NOTHING`).
- `async lock_wallets(session, account_ids: Iterable[UUID]) -> dict[UUID, Account]` (`FOR UPDATE`, ordered by id).
- `async post_entry(session, *, type: EntryType, currency: str, postings: Sequence[tuple[UUID, int]], actor: str, reference: str | None = None, metadata: dict | None = None, reverses_entry_id: UUID | None = None) -> PostedEntry` where `PostedEntry(entry_id, created_at, wallet_balances: dict[UUID, int])`. Raises `ValueError` on <2 postings, a zero amount, non-zero sum, or an account of another currency. Emits `wallet.credited` / `wallet.debited` per wallet posting.
- `async emit(session, event_type: str, payload: dict) -> None`.

- [ ] Tests: balanced post updates the cached wallet balance and returns it; outbox gets one event per wallet posting; each `ValueError` case; `system_account` returns the same id twice.
- [ ] Implement, commit `feat(core): add double-entry post_entry and outbox emit`.

### Task 5: Idempotency

**Files:** `src/paywall/core/idempotency.py`; test `tests/core/test_idempotency.py` (unit parts).

**Interfaces — produces:** `fingerprint(operation: str, args: Mapping[str, Any]) -> str` (sha256 hex of canonical JSON); `async claim(session, *, scope, key, fingerprint) -> StoredResponse | None` (409 if lock busy, 422 on different fingerprint, replay if same); `async store(session, *, scope, key, fingerprint, response_code, response_body, ttl: timedelta)`.

- [ ] Tests: fingerprint independent of dict order; claim → None, store, claim again in a new tx → replay; different fingerprint → 422; expired row is ignored and overwritten.
- [ ] Implement, commit `feat(core): add idempotency keys with advisory-lock claims`.

### Task 6: Wallets and payments

**Files:** `src/paywall/core/wallets.py`, `src/paywall/core/payments.py`, `src/paywall/core/results.py`; tests `tests/core/test_wallets.py`, `tests/core/test_payments.py`.

**Interfaces — produces:**
- `Wallet(id, user_id, currency, balance, status, created_at)`; `Transaction(id, entry_id, type, amount, reference, metadata, created_at)`; `TransactionPage(items, next_cursor: int | None)`; `WalletEntry(entry_id, type, user_id, amount (signed wallet delta), currency, balance_after, reference, created_at)` with `to_json()`/`from_json()`.
- wallets: `get_or_create_wallet(session, user_id, currency) -> Wallet`; `history(session, *, user_id, currency, cursor, limit, types=None, since=None, until=None) -> TransactionPage`; `set_status(session, *, user_id, currency, status) -> Wallet`.
- payments: `debit(session, *, user_id, currency, amount, reference, metadata, actor)`, `adjust(session, *, user_id, currency, amount (signed), reason, actor)`, `reverse(session, *, entry_id, reason, actor)`, all `-> WalletEntry`.

- [ ] Tests: debit happy path; insufficient funds; frozen → `WALLET_FROZEN`; no wallet → `WALLET_NOT_FOUND`; amount 0, -1, `True` → `VALIDATION_ERROR`; negative adjust below zero → `INSUFFICIENT_FUNDS`; reverse of a debit restores balance; reverse twice → `ENTRY_ALREADY_REVERSED`; reversing a reversal → `VALIDATION_ERROR`; reversing a spent credit → `INSUFFICIENT_FUNDS`; history pagination with cursor and type filter; unknown user history is empty.
- [ ] Implement, commit `feat(core): add wallets, debit, adjust and reverse`.

### Task 7: PayWall facade + spec tests 1 and 3

**Files:** `src/paywall/app.py`, `src/paywall/__init__.py`; tests `tests/core/test_concurrency.py`, `tests/core/test_idempotency.py` (race part), `tests/test_app.py`.

**Interfaces — produces:** `PayWall(settings)`, `PayWall.from_env()`, `await close()`, `await migrate()`, `get_wallet(user_id)`, `history(user_id, *, cursor=None, limit=50, types=None, since=None, until=None)`, `debit(user_id, amount, *, reference, idempotency_key, metadata=None)`, `adjust(user_id, amount, *, reason, idempotency_key, actor="app")`, `reverse(entry_id, *, reason, idempotency_key, actor="app")`, `freeze(user_id)`, `unfreeze(user_id)`. Idempotency scope for the Python API is `"app"`.

- [ ] Test 1: 100 concurrent ₹10 debits on ₹100 → exactly 10 succeed, balance 0, balance = SUM(postings).
- [ ] Test 3: 20 concurrent same-key debits → 1 ledger entry; others replay the same `entry_id` or get 409; same key with a different amount → 422.
- [ ] Implement, commit `feat: add PayWall facade with idempotent Python API`.

### Task 8: Ledger invariant property test (spec test 6)

**Files:** `tests/core/test_invariants.py`.

- [ ] Hypothesis generates sequences of adjust/debit/reverse over 3 users; expected business errors are ignored; afterwards every entry sums to 0, every wallet's cached balance equals SUM(postings), and the global sum is 0.
- [ ] Commit `test: add ledger invariant property test`.

### Task 9: `paywall migrate` CLI and ADRs

**Files:** `src/paywall/cli.py`, `pyproject.toml` (`[project.scripts]`), `tests/test_cli.py`, `docs/decisions/0001-double-entry-ledger.md`, `0002-pessimistic-row-locking.md`, `0003-idempotency-advisory-locks.md`, `0004-no-cached-balance-on-system-accounts.md`, `README.md`.

- [ ] Test: `migrate` against a fresh schema exits 0 twice and creates `alembic_version` in that schema.
- [ ] Implement, write ADRs, commit `feat(cli): add migrate command` and `docs: add ADRs 1-4`.

### Phase exit

`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` green, then code review, summary and stop.
