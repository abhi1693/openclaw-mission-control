# Quickstart (Docker Compose)

This is the fastest way to run Mission Control locally or on a single host.

## What you get

From `compose.yml` you get three services:

- Postgres (`db`)
- FastAPI backend (`backend`) on `http://localhost:8000`
- Next.js frontend (`frontend`) on `http://localhost:3000`

## Prerequisites

- Docker + Docker Compose v2 (`docker compose`)

## Run

From repo root:

```bash
cp .env.example .env

docker compose -f compose.yml --env-file .env up -d --build
```

Open:
- UI: http://localhost:3000
- Backend health: http://localhost:8000/healthz

## Verify

```bash
curl -f http://localhost:8000/healthz
curl -I http://localhost:3000/
```

## Common gotchas

- `NEXT_PUBLIC_API_URL` must be reachable from your **browser**.
  - If it’s missing/blank/wrong, the UI may load but API calls will fail (e.g. Activity feed blank).
- If you are running locally without Clerk:
  - keep `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` unset/blank so Clerk stays gated off in the frontend.

## Useful commands

```bash
# tail logs
docker compose -f compose.yml --env-file .env logs -f --tail=200

# stop (keeps data)
docker compose -f compose.yml --env-file .env down

# reset data (DESTRUCTIVE)
docker compose -f compose.yml --env-file .env down -v
```

## Next

- Want a faster contributor loop? See [Development](03-development.md) (DB via Compose, backend+frontend in dev mode).
- Need to change env vars/migrations/CORS? See [Configuration](06-configuration.md).
