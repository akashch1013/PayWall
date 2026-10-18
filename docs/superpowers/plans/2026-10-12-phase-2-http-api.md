# Phase 2: HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One FastAPI router that a host app can mount with its own auth (Mode A), and a standalone server that wraps it with API-key and JWT auth (Mode B). Every endpoint is documented in OpenAPI and tested.

**Architecture:** `api/` is a thin layer over the `PayWall` facade. A custom `APIRoute` class (`ProblemRoute`) assigns the request id, renders `PayWallError` and validation errors as `application/problem+json`, and logs one line per request. It needs no handlers or middleware on the host. Auth is a dependency that returns a `Principal`. The host supplies it in Mode A; `server.py` supplies it in Mode B.

**Tech Stack:** FastAPI 0.143, Starlette 1.7, PyJWT 2.15 (HS256), uvicorn (extra `paywall[server]`), httpx `ASGITransport` for tests.

**Spec:** `docs/superpowers/specs/2026-10-11-paywall-design.md` (sections 1, 3 `api_keys`, 5 idempotency, 7 API, 8 config, 10 Phase 2).

## Global Constraints

- All routes live under `/v1`. The host chooses the mount prefix.
- Errors use `application/problem+json`: `type` (`urn:paywall:error:<code lowercased>`), `title`, `status`, `detail`, `code` and `request_id`, plus `errors` for validation failures. Validation errors never echo the request input.
- Every response from a PayWall route carries `X-Request-ID`. An incoming id is reused only if it matches `^[A-Za-z0-9._-]{1,64}$`; otherwise a new `req_<32 hex>` id is generated.
- Money-moving POSTs require `Idempotency-Key` (1–255 chars, else 400 `IDEMPOTENCY_KEY_MISSING`). The HTTP fingerprint is `sha256(method, path, user_id, canonical body)`. The scope is the principal's subject (`user:<id>` or `apikey:<prefix>`). Replays return the stored status and body with `Idempotent-Replayed: true`.
- `POST /v1/admin/api-keys` and `POST /v1/auth/tokens` are exempt from idempotency. Their responses contain secrets, which must never be stored.
- API keys have the form `pw_<12 hex prefix>_<secret>`. Only `sha256(key)` is stored. Scopes are a non-empty subset of `wallet:read`, `wallet:write` and `admin`, `admin` implies `wallet:write`, which implies `wallet:read`.
- JWTs are HS256 only, with claims `iss=paywall`, `sub`, `iat` and `exp`. `PAYWALL_JWT_SECRET` must be at least 32 characters. If it is unset, JWT is disabled and `/v1/auth/tokens` isn't mounted.
- Building the router without `auth` raises an error. There is no insecure default.

## Review Focus

1. An API key acting for two users through `X-User-Id` with the same idempotency key and body must not replay one user's debit to the other. The fingerprint includes `user_id` (Task 5 test).
2. A revoked API key must stop working on the very next request, with no caching (Task 6 test).
3. JWT `alg: none` or HS-signed tokens from another secret: 401 (Task 6 test).
4. A naive datetime in `from`/`to`: 422, never a silent UTC assumption (Task 5 test).
5. Host `auth` that returns `None`: 401 problem+json, not a 500 (Task 5 test).

---

### Task 1: Migration 0002, request ids in the ledger, settings

**Files:** `src/paywall/db/migrations/versions/0002_api_keys_request_ids.py`, `db/models.py`, `observability.py` (`request_id_var`), `core/ledger.py`, `core/outbox.py`, `config.py`, `errors.py`.

- `api_keys` table (spec §3) with CHECKs on scopes. `request_id text` added to `journal_entries` and `outbox_events`.
- `post_entry` and `emit` record `request_id_var.get()`.
- Settings: `log_level="INFO"`, `log_json=True`, `jwt_secret: SecretStr | None` (≥32 chars), `jwt_ttl_minutes=60`.
- ErrorCodes: `IDEMPOTENCY_KEY_MISSING` 400, `UNAUTHORIZED` 401, `FORBIDDEN` 403.
- Tests: the model and migration diff stays empty; an entry posted with the contextvar set stores it.

### Task 2: API keys (core + facade)

**Files:** `src/paywall/auth.py` (`Scope`, `Principal`), `core/apikeys.py`, `app.py`; test `tests/core/test_apikeys.py`.

- `Principal(subject: str, user_id: str | None, scopes: frozenset[Scope])` with `.user(user_id)`, `.has(scope)`.
- `apikeys.create(session, *, name, scopes) -> tuple[ApiKey, str]`, `list_keys`, `revoke(session, key_id) -> ApiKey`, `authenticate(session, key) -> ApiKey | None`.
- Facade: `create_api_key`, `list_api_keys`, `revoke_api_key`, `authenticate_api_key`.
- Tests: the plaintext key is never stored; authenticate works until revoked; unknown, malformed and revoked keys give None; revoking an unknown id gives `NOT_FOUND`.

### Task 3: JSON logging

**Files:** `src/paywall/observability.py`; test `tests/test_observability.py`.

- `JsonFormatter` emits `ts`, `level`, `logger`, `message`, `request_id`, any `extra` fields, and `exc_info` when present. `configure_logging(settings)` installs it on the root logger (or a plain format when `log_json=False`).

### Task 4: ProblemRoute and schemas

**Files:** `src/paywall/api/router.py` (`ProblemRoute`, `problem_response`), `api/schemas.py`; test `tests/api/test_problems.py`.

- Tests: a `PayWallError` gives the right status, content type and body; a validation error gives 422 with `errors` and without the input; request-id reuse vs generation; an unexpected exception is logged and re-raised.

### Task 5: Wallet endpoints, embedded auth, sample host

**Files:** `api/deps.py`, `api/wallets.py`, `api/router.py` (`create_router(paywall, auth)`), `app.py` (`auth=`, `.router`, `run_idempotent`, `currency`); tests `tests/api/host_app.py`, `tests/api/test_wallets_api.py`, `tests/api/test_host_app.py`.

- `GET /v1/wallets/me`, `GET /v1/wallets/me/transactions`, `POST /v1/wallets/me/debits`.
- Tests: lazy wallet creation; pagination via an opaque `next_cursor`; type and time filters; naive datetime gives 422; a debit returns 201 with the entry and its `request_id` stored; a replay returns the same body plus a header; key reuse gives 422; missing key gives 400; 401 without a principal; 403 without scope; the fingerprint is per user; the host mounts the router under its own prefix and also calls the Python API; `PayWall(...).router` without auth raises.

### Task 6: Standalone server

**Files:** `src/paywall/server.py` (`create_app`, `standalone_auth`), `api/admin.py`; test `tests/api/test_server.py`.

- `POST/GET/DELETE /v1/admin/api-keys`, `POST /v1/auth/tokens`.
- Tests: the full API key → debit → history flow; a revoked key gives 401; a non-admin key gets 403 on admin routes; JWT mint and use; expired, tampered, foreign-secret and `alg none` tokens give 401; with JWT disabled the tokens route is 404 and a bearer non-key gives 401.

### Task 7: CLI `api-keys` and `serve`, OpenAPI completeness, docs

**Files:** `cli.py`, `tests/test_cli.py`, `tests/api/test_openapi.py`, `README.md`, `docs/decisions/0005-api-keys-and-tokens.md`.

- `paywall api-keys create NAME --scope …` prints the key once; `list`; `revoke ID`; `paywall serve --host --port --workers`.
- The OpenAPI test checks that every operation has a summary, a description and problem+json error responses, and every request body has an example.
