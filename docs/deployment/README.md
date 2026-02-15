# Deployment

This section covers deploying Mission Control in self-hosted environments.

> **Goal**
> A simple, reproducible deploy that preserves the Postgres volume and supports safe upgrades.

## Deployment mode: single host (Docker Compose)

### Prerequisites

- Docker + Docker Compose v2 (`docker compose`)
- A host where the **browser** can reach the backend URL you configure (see `NEXT_PUBLIC_API_URL` below)

### 1) Configure environment

From repo root:

```bash
cp .env.example .env
```

Edit `.env`:

- `AUTH_MODE=local` (default)
- **Set** `LOCAL_AUTH_TOKEN` to a non-placeholder value (≥ 50 chars)
- Ensure `NEXT_PUBLIC_API_URL` is reachable from the browser (not a Docker-internal hostname)

Key variables (from `.env.example` / `compose.yml`):

- Frontend: `FRONTEND_PORT` (default `3000`)
- Backend: `BACKEND_PORT` (default `8000`)
- Postgres: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- Backend:
  - `DB_AUTO_MIGRATE` (default `true` in compose)
  - `CORS_ORIGINS` (default `http://localhost:3000`)

### 2) Start the stack

```bash
docker compose -f compose.yml --env-file .env up -d --build
```

Open:

- Frontend: `http://localhost:${FRONTEND_PORT:-3000}`
- Backend health: `http://localhost:${BACKEND_PORT:-8000}/healthz`

### 3) Verify

```bash
curl -f "http://localhost:${BACKEND_PORT:-8000}/healthz"
```

If the frontend loads but API calls fail, double-check:

- `NEXT_PUBLIC_API_URL` is set and reachable from the **browser**
- backend CORS includes the frontend origin (`CORS_ORIGINS`)

## Database persistence

The Compose stack uses a named volume:

- `postgres_data` → `/var/lib/postgresql/data`

This means:

- `docker compose ... down` preserves data
- `docker compose ... down -v` is **destructive** (deletes the DB volume)

## Migrations / upgrades

### Default behavior in Compose

In `compose.yml`, the backend container defaults:

- `DB_AUTO_MIGRATE=true`

So on startup the backend will attempt to run Alembic migrations automatically.

> **Warning**
> For zero/near-zero downtime, migrations must be **backward compatible** with the currently running app if you do rolling deploys.

### Safer operator pattern (manual migrations)

If you want more control, set `DB_AUTO_MIGRATE=false` and run migrations explicitly during deploy:

```bash
cd backend
uv run alembic upgrade head
```

## Reverse proxy / TLS

Typical setup (outline):

- Put the frontend behind HTTPS (reverse proxy)
- Ensure the frontend can reach the backend over the configured `NEXT_PUBLIC_API_URL`

This section is intentionally minimal until we standardize a recommended proxy (Caddy/Nginx/Traefik).
