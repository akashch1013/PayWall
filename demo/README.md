# ReWear: clothing resale demo

A small end-to-end marketplace for pre-loved clothes: browse and search listings, create an account, list items with a photo, manage your listings, and place **demo orders** (no payment is ever taken).

- **Frontend:** React 18 + Vite + React Router (`client/`)
- **API:** Node.js + Express (`server/`)
- **Database:** MongoDB via Mongoose
- **Tests:** Vitest + Supertest + mongodb-memory-server (API), Vitest + Testing Library (UI)

The original static prototype is kept at `index.html` (repo root) as the design reference; the app itself lives in `client/` and `server/`.

## Prerequisites

- Node.js 20 or newer (developed on Node 24) and npm
- A MongoDB database, either:
  - **Local MongoDB Community Server** (e.g. `winget install MongoDB.Server` on Windows, `brew install mongodb-community` on macOS), running on `localhost:27017`, **or**
  - **MongoDB Atlas** (free tier works). Add your machine's IP under *Network Access*.

## Setup

```bash
npm install                                  # installs root, server and client workspaces
cp server/.env.example server/.env           # then edit server/.env
```

`server/.env`:

| Variable | Description |
| --- | --- |
| `MONGODB_URI` | Local: `mongodb://127.0.0.1:27017/rewear`. Atlas: `mongodb+srv://<user>:<password>@<cluster-host>/rewear?appName=<app>`. Include the `/rewear` database name. |
| `JWT_SECRET` | Long random string used to sign session cookies. Generate one with `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"` |
| `PORT` | API port (default `4000`). The Vite dev server proxies to it. |

`server/.env` is gitignored. Never commit real credentials.

If the database can't be reached, the API and seed script stop with a clear message (check that `mongod` is running, or your Atlas credentials and IP allowlist). There is no mock-data fallback.

## Seed demo data

```bash
npm run seed
```

The seed script is idempotent, so you can re-run it without creating duplicates. It creates:

| Account | Email | Password |
| --- | --- | --- |
| Demo Buyer | `demo@rewear.local` | `demo12345` |
| Demo Seller | `seller@rewear.local` | `demo12345` |

It also adds 10 sample listings split between the two accounts. They are shown with a "Sample listing" tag and use local SVG illustrations from `server/assets/seed-images/`.

> These credentials are for local demo use only.

Re-running the seed resets the demo accounts' passwords and refreshes sample listing details. It does not reset an item that was already sold through a demo order.

## Run in development

```bash
npm run dev
```

- Web app: http://localhost:5173 (Vite; proxies `/api`, `/uploads`, `/seed-images` to the API)
- API: http://localhost:4000 (health check: `/api/health`)

Uploaded photos are stored in `server/uploads/` and their paths are saved in MongoDB.

## Tests and build

```bash
npm test         # API tests, then UI tests
npm run build    # production build of the client into client/dist
```

API tests start a temporary in-memory MongoDB via `mongodb-memory-server`. They never touch the database in `server/.env`. The first run downloads a MongoDB binary (~600 MB on Windows) into `~/.cache/mongodb-binaries`. If that download isn't possible, point the tests at a disposable database instead:

```bash
# bash; the database is wiped by the tests
TEST_MONGODB_URI="mongodb://127.0.0.1:27017/rewear_test" npm test -w server
```

## Run in production mode

```bash
npm run build
NODE_ENV=production npm start    # PowerShell: $env:NODE_ENV="production"; npm start
```

The API then also serves the built app at http://localhost:4000. In production the session cookie is marked `Secure`, so serve over HTTPS; `localhost` also works in modern browsers.

## Features

- **Browse:** listings load from MongoDB. You can filter by category (Tops, Bottoms, Dresses, Jackets, Shoes, Accessories, Other), search text, and sort by newest or price. Filters live in the URL, so reload and back keep them. Each item has a detail page with its description and seller.
- **Accounts:** register, log in, log out. Passwords are hashed with bcrypt. The session is a JWT in an httpOnly, SameSite=Lax cookie.
- **Selling:** create, edit and delete your own listings, with an optional photo (JPG/PNG/WEBP/GIF, max 5 MB, checked by type and file signature). The "My listings" dashboard shows each item's status.
- **Demo orders:** order another seller's available item. The listing becomes sold and the order appears under "My orders". Self-purchase, double purchase and simultaneous purchases are rejected. Sold listings can't be edited or deleted, so order history stays consistent.
- Every data-driven screen has loading, empty, error-with-retry and success states. Forms have labels and inline errors, and controls are keyboard-accessible with visible focus.

## API overview

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | none | `{ name, email, password }` (password ≥ 8 chars) |
| POST | `/api/auth/login` | none | `{ email, password }` |
| POST | `/api/auth/logout` | none | Clears the session cookie |
| GET | `/api/auth/me` | optional | `{ user }` or `{ user: null }` |
| GET | `/api/listings` | none | `?category=&q=&sort=newest\|price_asc\|price_desc` |
| GET | `/api/listings/mine` | required | Current user's listings |
| GET | `/api/listings/:id` | none | |
| POST | `/api/listings` | required | multipart form; optional `photo` file |
| PATCH | `/api/listings/:id` | owner | multipart form; `removePhoto=true` clears the photo |
| DELETE | `/api/listings/:id` | owner | Not allowed once sold |
| POST | `/api/orders` | required | `{ listingId }`: demo order, no payment |
| GET | `/api/orders` | required | Current user's orders |

Errors are JSON `{ error, fields? }` with appropriate status codes (400, 401, 403, 404, 409).

## Project layout

```
client/            React app (pages/, components/, api.js, styles.css, __tests__/)
server/
  src/             Express app, Mongoose models, routes, middleware, seed script
  assets/          Local seed images
  uploads/         Uploaded photos (gitignored)
  test/            API tests
index.html         Original static design reference
```

## Limitations

- Demo only: there are no payments, shipping, messaging or password reset.
- Uploaded files are stored on local disk, which suits a single-machine demo but not multi-server hosting.
- There is no rate limiting on login or registration.
