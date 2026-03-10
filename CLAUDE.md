# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**OpenClaw Mission Control** is a centralized operations and governance platform for running OpenClaw (an AI agent orchestration system) across teams. It's a monorepo with:

- **`backend/`** — FastAPI (Python 3.12+) REST API with PostgreSQL + Redis
- **`frontend/`** — Next.js 16 (React 19, TypeScript) web app
- **Docker Compose** orchestrates all services: `db`, `redis`, `backend`, `frontend`, `webhook-worker`

## Development commands

All common tasks are in the `Makefile`. Run `make help` to see all targets.

### Setup

```bash
make setup                  # Install all deps (uv + npm)
make backend-sync           # Backend only (uv sync --extra dev)
make frontend-sync          # Frontend only (npm install)
```

### Running locally (non-Docker)

Backend needs `backend/.env` set. Then:

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Docker database/Redis can be started separately: `docker compose up db redis -d`

### Full Docker stack

```bash
cp .env.example .env        # Configure AUTH_MODE, LOCAL_AUTH_TOKEN, NEXT_PUBLIC_API_URL
docker compose -f compose.yml --env-file .env up -d --build
```

### Tests

```bash
make backend-test            # pytest (all backend tests)
make frontend-test           # vitest (frontend unit tests)
make backend-coverage        # pytest with 100% coverage gate on scoped modules
# Run a single backend test file:
cd backend && uv run pytest tests/path/to/test_file.py -v
# Run a single test:
cd backend && uv run pytest tests/path/to/test_file.py::test_name -v
```

### Lint, typecheck, build

```bash
make lint                    # flake8 (backend) + eslint (frontend)
make typecheck               # mypy --strict (backend) + tsc (frontend)
make format                  # isort + black (backend) + prettier (frontend)
make frontend-build          # next build
make check                   # Full CI suite: lint + typecheck + coverage + test + build
```

### Database migrations

```bash
make backend-migrate         # alembic upgrade head
make backend-migration-check # Validate graph + test up/down on clean Postgres
```

### API client codegen

```bash
make api-gen                 # Regenerate frontend/src/api/ from backend OpenAPI (backend must be running)
```

## Architecture

### Backend (`backend/app/`)

Layered FastAPI application:

- **`api/`** — FastAPI routers (~26 modules). All routers registered in `main.py`. Auth/DB injected via `api/deps.py` using `Depends()`.
- **`services/`** — Business logic layer. `services/openclaw/` handles gateway RPC and dispatch.
- **`models/`** — SQLModel DB schemas (~30 models).
- **`schemas/`** — Pydantic request/response schemas (~29 modules, separate from DB models).
- **`db/`** — Session management, generic CRUD, pagination, query manager.
- **`core/`** — Config (Pydantic Settings), auth logic, error handling, logging. Two auth modes: `local` (shared bearer token) and `clerk` (Clerk JWT).
- **`migrations/`** — Alembic migrations. CI enforces max 1 per PR and tests reversibility.

Background jobs run via **RQ** (Redis Queue) in the `webhook-worker` service.

### Frontend (`frontend/src/`)

- **`api/`** — Auto-generated TypeScript client from backend OpenAPI via Orval. **Do not edit manually** — regenerate with `make api-gen`.
- **`app/`** — Next.js App Router pages (activity, approvals, agents, boards, organizations).
- **`components/`** — Atomic design: `atoms/` → `molecules/` → `organisms/`. Feature dirs: `agents/`, `boards/`, etc. Radix UI primitives in `ui/`.
- **`auth/`** — Abstracts Clerk vs local token auth. Mode controlled by `NEXT_PUBLIC_AUTH_MODE`.
- **`hooks/`** — React Query hooks for server state; React hooks for local state.
- **`lib/`** — `api-base.ts` configures the Orval client base URL and auth header injection.

### Key env vars

| Variable | Purpose |
|---|---|
| `AUTH_MODE` | `local` or `clerk` |
| `LOCAL_AUTH_TOKEN` | Shared bearer token (≥50 chars, required for local mode) |
| `NEXT_PUBLIC_API_URL` | Backend URL as seen from the browser |
| `DATABASE_URL` | PostgreSQL connection string |
| `RQ_REDIS_URL` | Redis URL for background worker |
| `DB_AUTO_MIGRATE` | Auto-run migrations on backend startup (true in Docker mode) |
| `CORS_ORIGINS` | Comma-separated allowed origins |

## Railway deployment

Project: **happy-quietude** | Workspace: Anirudha Jadhav's Projects

| Service | URL | Notes |
|---|---|---|
| backend | https://backend-production-1f9f.up.railway.app | FastAPI, port 8000 |
| frontend | https://frontend-production-62a7.up.railway.app | Next.js, port 8080 |
| Postgres | postgres.railway.internal:5432 | Internal only |
| Redis | redis.railway.internal:6379 | Internal only |
| webhook-worker | (internal) | RQ worker, no public port |

### Full setup from scratch

Use this if the Railway project is deleted or you need to deploy to a new account.

**Prerequisites:** Railway CLI installed and logged in (`railway login`).

#### Step 1 — Generate a secure auth token

```bash
openssl rand -hex 32
# Save the output — this is your LOCAL_AUTH_TOKEN (must be 50+ chars, no special chars is safest)
```

#### Step 2 — Create the Railway project

```bash
railway init
# Select workspace when prompted, give the project a name
```

#### Step 3 — Add managed databases

```bash
railway add --database postgres
railway add --database redis
```

Get the connection strings for use below:

```bash
railway service Postgres && railway variables --json | python3 -c "import json,sys; v=json.load(sys.stdin); print('DB:', v['DATABASE_URL']); print('DB_PUBLIC:', v['DATABASE_PUBLIC_URL'])"
railway service Redis && railway variables --json | python3 -c "import json,sys; v=json.load(sys.stdin); print('REDIS:', v['REDIS_URL'])"
```

Note: `DATABASE_URL` uses scheme `postgresql://` — you must change it to `postgresql+psycopg://` for the backend.

#### Step 4 — Create and configure the backend service

```bash
railway add --service backend
railway service backend

railway variables set \
  AUTH_MODE=local \
  LOCAL_AUTH_TOKEN="<your-50-char-token>" \
  DATABASE_URL="postgresql+psycopg://<user>:<pass>@postgres.railway.internal:5432/railway" \
  CORS_ORIGINS="http://localhost:3000" \
  DB_AUTO_MIGRATE=true \
  ENVIRONMENT=production \
  LOG_LEVEL=INFO \
  LOG_FORMAT=json \
  RQ_REDIS_URL="redis://default:<pass>@redis.railway.internal:6379" \
  RQ_QUEUE_NAME=default \
  RQ_DISPATCH_THROTTLE_SECONDS=2.0 \
  RQ_DISPATCH_MAX_RETRIES=3 \
  PORT=8000

# Generate a public domain for the backend
railway domain
# Note the URL (e.g. https://backend-production-xxxx.up.railway.app)

# Deploy backend (from repo root — picks up railway.toml → backend/Dockerfile)
railway up --service backend --detach
```

#### Step 5 — Create and configure the frontend service

```bash
railway add --service frontend
railway service frontend

railway variables set \
  NEXT_PUBLIC_API_URL="https://<backend-url-from-step-4>" \
  NEXT_PUBLIC_AUTH_MODE=local

# Generate a public domain for the frontend
railway domain
# Note the URL (e.g. https://frontend-production-xxxx.up.railway.app)
```

Go back and update the backend CORS to the real frontend URL:

```bash
railway service backend
railway variables set CORS_ORIGINS="https://<frontend-url-from-above>"
```

Deploy the frontend — **must use `--path-as-root` so `frontend/` is the archive root**:

```bash
railway service frontend
railway up --service frontend --detach --path-as-root ./frontend
```

Then set the PORT Railway injected (Next.js will be on 8080):

```bash
railway variables set PORT=8080
```

#### Step 6 — Create and configure the webhook-worker

```bash
railway add --service webhook-worker
railway service webhook-worker

railway variables set \
  AUTH_MODE=local \
  LOCAL_AUTH_TOKEN="<same-token-as-backend>" \
  DATABASE_URL="postgresql+psycopg://<user>:<pass>@postgres.railway.internal:5432/railway" \
  RQ_REDIS_URL="redis://default:<pass>@redis.railway.internal:6379" \
  RQ_QUEUE_NAME=default \
  RQ_DISPATCH_THROTTLE_SECONDS=2.0 \
  RQ_DISPATCH_MAX_RETRIES=3 \
  ENVIRONMENT=production
```

Deploy the worker — temporarily swap `railway.toml` so it uses `webhook-worker/Dockerfile`:

```bash
cp railway.toml railway.toml.bak
cp webhook-worker/railway.toml railway.toml
railway up --service webhook-worker --detach
mv railway.toml.bak railway.toml
```

#### Step 7 — Verify

```bash
curl https://<backend-url>/healthz   # → {"ok":true}
curl https://<backend-url>/readyz    # → {"ok":true}
# Open https://<frontend-url> in browser — log in with LOCAL_AUTH_TOKEN
```

---

### Re-deploying existing services

```bash
# Backend
railway service backend && railway up --service backend --detach

# Frontend (must always use --path-as-root)
railway service frontend && railway up --service frontend --detach --path-as-root ./frontend

# Webhook-worker (swap configs, deploy, restore)
cp railway.toml railway.toml.bak
cp webhook-worker/railway.toml railway.toml
railway service webhook-worker && railway up --service webhook-worker --detach
mv railway.toml.bak railway.toml
```

**One-time dashboard fix to avoid the webhook-worker swap forever:** Railway dashboard → webhook-worker service → Settings → Config File Path → set to `/webhook-worker/railway.toml`.

### Known gotchas (learned the hard way)

- **`DATABASE_URL` scheme**: Railway Postgres gives `postgresql://` but the backend requires `postgresql+psycopg://`. Always convert when setting the var.
- **Frontend build-time vars**: `NEXT_PUBLIC_API_URL` is baked into the Next.js bundle at build time. If the backend URL changes, you must redeploy the frontend too.
- **Frontend deploy path**: `railway up` from repo root sends the entire repo and `railway.toml` picks up `backend/Dockerfile`. Frontend **must** use `--path-as-root ./frontend`.
- **`PORT` env var**: Railway injects `PORT` dynamically. Backend defaults to 8000 (set `PORT=8000`). Next.js picks up whatever Railway injects (was 8080 in our deployment). Set `PORT=8080` on the frontend service after first deploy.
- **Healthcheck timeout**: The backend runs Alembic migrations on startup, which takes a few seconds. Default 60s healthcheck timeout is too short on cold starts — `railway.toml` sets it to 120s.
- **`startCommand` in `railway.toml` does not expand env vars** — you must wrap with `sh -c '...'` (e.g. `sh -c 'uvicorn ... --port ${PORT:-8000}'`).
- **Webhook-worker config path**: Railway reads `railway.toml` from the root of the uploaded archive. Since backend and worker both deploy from repo root, they'd share the same config. The swap trick above is the CLI workaround; the dashboard config path setting is the permanent fix.

## CI enforcement

- Max 1 Alembic migration per PR (enforced in `.github/workflows/ci.yml`)
- 100% statement + branch coverage required on `app.core.error_handling` and `app.services.mentions`
- mypy runs with `--strict` on `app/` and `scripts/`
- Pre-commit hooks: Black, isort, flake8, trailing whitespace
