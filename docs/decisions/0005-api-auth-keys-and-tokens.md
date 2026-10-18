# 5. Pluggable auth: host dependency, API keys and short-lived user tokens

- **Status:** accepted
- **Date:** 2026-10-12

## Context

PayWall runs in two modes. Embedded in a host app, it must use the host's existing login.
PayWall can't know whether that login is cookies, OAuth or something else. Standalone, it needs
its own way to authenticate two kinds of caller:

- **backends**, which act for many users;
- **browsers and mobile apps**, which must only ever reach the signed-in user's wallet.

## Decision

**One router, auth injected as a dependency.** The API only consumes a `Principal`:
`subject` (who is calling), `user_id` (whose wallet `/wallets/me` means) and `scopes`.

- **Embedded:** the host passes `auth=`, its own FastAPI dependency that maps its user to a
  `Principal`. Building the router without it raises an error, so no deployment can end up
  with a default "trust everyone" mode.
- **Standalone:** `server.py` supplies a dependency that reads `Authorization: Bearer <credential>`.

**API keys for backends** take the form `pw_<12 hex>_<43 chars>`.

- Only `sha256(key)` is stored, under a unique index, so lookup is one indexed query.
- A slow password hash (bcrypt, argon2) would add latency and protect nothing. Those exist to
  make guessing *low-entropy* human passwords expensive, and a 256-bit random secret can't be
  guessed.
- The public prefix names the caller in logs, in idempotency scopes and as the ledger `actor`.
- The key is shown once and revoked with a timestamp. Nothing caches it, so revocation takes
  effect on the next request.
- A backend names the end user per request with `X-User-Id`.

**User tokens for front ends** are HS256 JWTs minted by `POST /v1/auth/tokens` (admin only),
with claims `iss`, `sub`, `iat` and `exp` (60 minutes by default).

- Verification pins `algorithms=["HS256"]`, which defeats `alg: none` and algorithm confusion,
  and requires every claim.
- A token always maps to `Principal.user(sub)`, and `X-User-Id` is ignored, so a token can't be
  pointed at another wallet.
- There is deliberately no password store: the host already has a login, and duplicating one
  would only add attack surface.

**Scopes** are hierarchical: `admin` ⊃ `wallet:write` ⊃ `wallet:read`.

**Idempotency** scopes keys by caller (`http:<subject>`). The request fingerprint covers the
end user, so one backend key acting for two users can't replay one user's debit to the other.
Key creation and token minting are exempt, because storing their responses for replay would
store the secrets.

## Consequences

- A host gets PayWall's API in one `include_router` call, with no handlers or middleware.
- User tokens can't be revoked before they expire. The short TTL bounds the exposure, and
  revoking keys covers backend compromise.
- HS256 means PayWall both signs and verifies with one secret. Asymmetric keys (RS256/EdDSA)
  only pay off once a different service needs to verify the tokens, which isn't the case here.
