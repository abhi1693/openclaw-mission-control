# Configuration

This page documents **where configuration comes from**, the key **environment variables**, and a couple operational footguns (migrations, CORS).

For deployment/production patterns, see:
- [Deployment](deployment/README.md)
- [Production](production/README.md)

## Configuration sources & precedence

Mission Control is a 3-service stack (`compose.yml`): Postgres (`db`), backend (`backend`), frontend (`frontend`).

### Docker Compose (recommended for local/self-host)

Common pattern:

```bash
cp .env.example .env

docker compose -f compose.yml --env-file .env up -d --build
```

Precedence (high → low):

1. Environment exported in your shell (or `-e NAME=value`)
2. Compose `--env-file .env` (variable interpolation)
3. Defaults in `compose.yml` (e.g. `${BACKEND_PORT:-8000}`)
4. Backend defaults via `env_file: ./backend/.env.example`
5. Frontend optional user-managed `frontend/.env`

> Note: Compose intentionally does **not** load `frontend/.env.example` to avoid placeholder Clerk keys accidentally enabling Clerk.

### Backend env-file loading (non-Compose)

Evidence: `backend/app/core/config.py`.

When running the backend directly (uvicorn), settings are loaded from:
- `backend/.env` (always attempted)
- `.env` (repo root; optional)
- plus process env vars

## Environment variables (grouped)

### Root `.env` (Compose-level)

Template: `.env.example`.

- Ports: `FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`
- Postgres defaults: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Backend knobs: `CORS_ORIGINS`, `DB_AUTO_MIGRATE`
- Frontend: `NEXT_PUBLIC_API_URL` (required)

### Backend

Template: `backend/.env.example` + settings model `backend/app/core/config.py`.

- `ENVIRONMENT`
- `LOG_LEVEL`
- `DATABASE_URL`
- `CORS_ORIGINS`
- `DB_AUTO_MIGRATE`

Clerk:
- `CLERK_SECRET_KEY` (required; backend enforces non-empty)
- `CLERK_API_URL`, `CLERK_VERIFY_IAT`, `CLERK_LEEWAY`

### Frontend

Template: `frontend/.env.example`.

| Variable | Required? | Purpose | Default / example | Footguns |
|---|---:|---|---|---|
| `NEXT_PUBLIC_API_URL` | **yes** | Backend base URL used by the browser | `http://localhost:8000` | Must be browser-reachable |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | **yes** | Enables Clerk in the frontend | (none) | Must be a real publishable key |
| `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL` | optional | Fallback redirect | `/boards` | — |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_OUT_URL` | optional | Post-logout redirect | `/` | — |

## Minimal dev configuration

### Split-mode dev (fastest contributor loop)

- Start DB via Compose.
- Run backend+frontend dev servers.

See [Development](03-development.md).

## Migrations (`DB_AUTO_MIGRATE`)

Evidence: `backend/app/db/session.py`.

On backend startup:
- if `DB_AUTO_MIGRATE=true` and migrations exist under `backend/migrations/versions/`, backend runs `alembic upgrade head`.
- otherwise it falls back to `SQLModel.metadata.create_all`.

Operational guidance:
- Auto-migrate is convenient on a single host.
- In multi-instance deployments, prefer running migrations as an explicit deploy step to avoid race conditions.

## CORS (`CORS_ORIGINS`)

Evidence: `backend/app/main.py`, `backend/app/core/config.py`.

- `CORS_ORIGINS` is a comma-separated list.
- It must include the frontend origin (e.g. `http://localhost:3000`) or browser requests will fail.

## Common footguns

- **Frontend env template vs runtime env**: `frontend/.env.example` is a template and `compose.yml` intentionally does **not** load it at runtime. Use user-managed `frontend/.env` (for Compose) or `frontend/.env.local` (for Next dev).
- **`NEXT_PUBLIC_API_URL` reachability**: must work from the browser’s network context (host), not only from within the Docker network.

## Troubleshooting config issues

- UI loads but API calls fail / Activity feed blank → `NEXT_PUBLIC_API_URL` is missing/incorrect.
- Backend fails at startup → check required env vars (notably `CLERK_SECRET_KEY`) and migrations.

See also: `docs/troubleshooting/README.md`.
