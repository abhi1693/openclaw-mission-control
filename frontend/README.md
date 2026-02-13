# Mission Control Frontend (`frontend/`)

This package is the **Next.js** web UI for OpenClaw Mission Control.

- Talks to the Mission Control **backend** over HTTP (typically `http://localhost:8000`).
- Uses **React Query** for data fetching.
- Supports two auth modes:
  - **local** shared bearer token mode (self-host default)
  - **clerk** mode

## Prerequisites

- Node.js (recommend **18+**) and npm
- Backend running locally (see `../backend/README.md` if present) **or** run the stack via Docker Compose from repo root.

## Local development

From `frontend/`:

```bash
npm install

# set env vars (see below)
cp .env.example .env.local

npm run dev
```

Open http://localhost:3000.

### LAN development

To bind Next dev server to all interfaces:

```bash
npm run dev:lan
```

## Environment variables

The frontend reads configuration from standard Next.js env files (`.env.local`, `.env`, etc.).

### Required

#### `NEXT_PUBLIC_API_URL`

Base URL of the backend API.

- Default for local dev: `http://localhost:8000`
- Used by the generated API client and helpers (see `src/lib/api-base.ts` and `src/api/mutator.ts`).

Example:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Authentication mode

Set `NEXT_PUBLIC_AUTH_MODE` to one of:

- `local` (default for self-host)
- `clerk`

For `local` mode:

- users enter the token in the local login screen
- requests use that token as `Authorization: Bearer ...`

For `clerk` mode, configure:

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- optional `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL`
- optional `NEXT_PUBLIC_CLERK_AFTER_SIGN_OUT_URL`

## How the frontend talks to the backend

### API base URL

The client builds URLs using `NEXT_PUBLIC_API_URL` (normalized to remove trailing slashes).

### Generated API client (Orval + React Query)

We generate a typed client from the backend OpenAPI schema using **Orval**:

- Config: `orval.config.ts`
- Output: `src/api/generated/*`
- Script: `npm run api:gen`

By default, Orval reads:

- `ORVAL_INPUT` (if set), otherwise
- `http://127.0.0.1:8000/openapi.json`

Example:

```bash
# from frontend/
ORVAL_INPUT=http://localhost:8000/openapi.json npm run api:gen
```

### Auth header / Clerk token injection

All Orval-generated requests go through the custom mutator (`src/api/mutator.ts`).
It will:

- set `Content-Type: application/json` when there is a body and you didn’t specify a content type
- add `Authorization: Bearer <token>` automatically from local mode token or Clerk session
- parse errors into an `ApiError` with status + parsed response body

## Mobile / responsive UI validation

When changing UI intended to be mobile-ready, validate in Chrome (or similar) using the device toolbar at common widths (e.g. **320px**, **375px**, **768px**).

Quick checklist:

- No horizontal scroll
- Primary actions reachable without precision taps
- Focus rings visible when tabbing
- Modals/popovers not clipped

## Common commands

From `frontend/`:

```bash
npm run dev        # start dev server
npm run build      # production build
npm run start      # run the built app
npm run lint       # eslint
npm run test       # vitest (with coverage)
npm run test:watch # watch mode
npm run api:gen    # regenerate typed API client via Orval
```

## Docker

There is a `frontend/Dockerfile` used by the root `compose.yml`.

If you’re working on self-hosting, prefer running compose from the repo root so the backend/db are aligned with the documented ports/env.

## Troubleshooting

### `NEXT_PUBLIC_API_URL is not set`

The API client throws if `NEXT_PUBLIC_API_URL` is missing.

Fix:

```bash
cp .env.example .env.local
# then edit .env.local if your backend URL differs
```

### Frontend loads, but API calls fail (CORS / network errors)

- Confirm backend is up: http://localhost:8000/healthz
- Confirm `NEXT_PUBLIC_API_URL` points to the correct host/port.
- If accessing from another device (LAN), use a reachable backend URL (not `localhost`).

### Wrong auth mode UI

- Ensure `NEXT_PUBLIC_AUTH_MODE` matches backend `AUTH_MODE`.
- For local mode, set `NEXT_PUBLIC_AUTH_MODE=local`.
- For Clerk mode, set `NEXT_PUBLIC_AUTH_MODE=clerk` and a real Clerk publishable key.

### Dev server blocked by origin restrictions

`next.config.ts` sets `allowedDevOrigins` for dev proxy safety.

If you see repeated proxy errors (often `ECONNRESET`), make sure your dev server hostname and browser URL match (e.g. `localhost` vs `127.0.0.1`), and that your origin is included in `allowedDevOrigins`.

Notes:

- Local dev should work via `http://localhost:3000` and `http://127.0.0.1:3000`.
- LAN dev should work via the configured LAN IP (e.g. `http://192.168.1.101:3000`) **only** if you bind the dev server to all interfaces (`npm run dev:lan`).
- If you bind Next to `127.0.0.1` only, remote LAN clients won’t connect.
