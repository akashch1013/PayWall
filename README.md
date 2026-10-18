# PayWall

An embeddable, self-hosted **closed-loop wallet** for Python apps: a double-entry ledger,
safe concurrent debits, idempotent APIs, promo codes and payment-gateway top-ups
(Razorpay, Stripe, Cashfree, PhonePe).

> **Status:** under active development. Phases 1–2 (ledger core, Python API, HTTP API) are
> complete. See the [design document](docs/superpowers/specs/2026-10-11-paywall-design.md) for
> the full plan and [docs/decisions](docs/decisions) for the reasoning behind the design.

## Python API

```bash
export PAYWALL_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/app
uv run paywall migrate           # creates PayWall's tables in the "paywall" schema
```

```python
from paywall import PayWall, PayWallError

wallet = PayWall.from_env()

await wallet.adjust("user_42", 50_000, reason="welcome credit", idempotency_key="seed_42")
entry = await wallet.debit("user_42", 49_900, reference="order_789", idempotency_key="order_789")
entry.balance_after  # 100 (amounts are minor units: paise)

# Retrying with the same key returns the same entry instead of charging twice.
await wallet.debit("user_42", 49_900, reference="order_789", idempotency_key="order_789")

try:
    await wallet.debit("user_42", 500, reference="order_790", idempotency_key="order_790")
except PayWallError as error:
    error.code  # ErrorCode.INSUFFICIENT_FUNDS

await wallet.reverse(entry.entry_id, reason="order cancelled", idempotency_key="cancel_789")
page = await wallet.history("user_42")  # newest first; pass page.next_cursor for more
```

## Embed in your FastAPI app

Give PayWall one dependency that maps your logged-in user to a `Principal`, then mount its
router. Errors come back as `application/problem+json` without any handler of yours.

```python
from fastapi import Depends, FastAPI
from paywall import PayWall, Principal


async def wallet_auth(user=Depends(current_user)) -> Principal | None:  # your own auth
    return Principal.user(user.id) if user else None


wallet = PayWall.from_env(auth=wallet_auth)
app = FastAPI()
app.include_router(wallet.router, prefix="/wallet")
# GET  /wallet/v1/wallets/me                the user's balance
# GET  /wallet/v1/wallets/me/transactions   history, newest first
# POST /wallet/v1/wallets/me/debits         spend (requires an Idempotency-Key header)
```

## Run it as a standalone service

```bash
pip install "paywall[server]"
export PAYWALL_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/app
export PAYWALL_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
paywall migrate
paywall api-keys create shop-backend --scope admin    # prints the key once
paywall serve --port 8000                             # docs at http://localhost:8000/docs
```

Backends call it with their API key and name the user:

```bash
curl -X POST localhost:8000/v1/wallets/me/debits \
  -H "Authorization: Bearer $PAYWALL_KEY" -H "X-User-Id: user_42" \
  -H "Idempotency-Key: order_789_pay" -H "Content-Type: application/json" \
  -d '{"amount": 49900, "reference": "order_789"}'
```

Browsers and mobile apps use a short-lived user token instead. Your backend mints it with
`POST /v1/auth/tokens` after its own login, and the token only reaches that user's wallet.

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/) and PostgreSQL 16+.

```bash
uv sync                          # creates .venv with Python 3.12 and all dev tools
cp .env.example .env             # then set PAYWALL_TEST_DATABASE_URL
uv run pre-commit install        # lint + type-check on every commit
uv run pytest                    # creates and drops a throwaway test database
```

Checks run in CI on every push: `ruff`, `mypy --strict`, `bandit`, `pip-audit`, and the
test suite against PostgreSQL 16.

## License

MIT
