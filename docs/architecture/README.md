# Mission Control — Architecture

Mission Control is the **web UI + HTTP API** for operating OpenClaw. It’s where you manage boards, tasks, agents, approvals, and (optionally) gateway connections.

At a high level:
- The **frontend** is a Next.js app used by humans.
- The **backend** is a FastAPI service that exposes REST endpoints under `/api/v1/*`.
- **Postgres** stores core state (boards/tasks/agents/etc.).
- **Redis** supports async/background primitives (RQ queue scaffolding exists).

## Components

### Diagram (conceptual)

```mermaid
flowchart LR
  U[User / Browser] -->|HTTP| FE[Next.js Frontend :3000]
  FE -->|HTTP /api/v1/*| BE[FastAPI Backend :8000]

  BE -->|SQL| PG[(Postgres :5432)]
  BE -->|Redis protocol| R[(Redis :6379)]

  BE -->|WebSocket| GW[OpenClaw Gateway]
  GW --> OC[OpenClaw runtime]
```

### Frontend (Next.js)
- Location: `frontend/`
- Routes/pages: `frontend/src/app/*` (Next.js App Router)
- API utilities: `frontend/src/lib/*` and `frontend/src/api/*`

**Auth (Clerk, optional)**
- Clerk is gated so CI/local can run without secrets.
- See `frontend/src/auth/clerkKey.ts`, `frontend/src/auth/clerk.tsx`, and `frontend/src/proxy.ts`.

### Backend (FastAPI)
- Location: `backend/`
- App wiring: `backend/app/main.py`
  - Health: `/health`, `/healthz`, `/readyz`
  - API prefix: `/api/v1`
  - Routers: `backend/app/api/*`

**Config**
- Settings: `backend/app/core/config.py`
- Env loading: always reads `backend/.env` (and optionally `.env`) so running from repo root still works.

### Data stores
- **Postgres**: persistence for boards/tasks/agents/approvals/etc.
  - Models: `backend/app/models/*`
  - Migrations: `backend/alembic/*`
- **Redis**: used for background primitives.
  - RQ helper: `backend/app/workers/queue.py`

### Gateway integration (optional)
Mission Control can call into an OpenClaw Gateway over WebSockets.
- Client: `backend/app/integrations/openclaw_gateway.py`
- Known methods/events: `backend/app/integrations/openclaw_gateway_protocol.py`
- Protocol doc: `docs/openclaw_gateway_ws.md`

## Request flows

### UI → API
1. Browser loads the Next.js frontend.
2. Frontend calls backend endpoints under `/api/v1/*`.
3. Backend reads/writes Postgres and may use Redis depending on the operation.

### Auth (Clerk — optional)
- **Frontend** enables Clerk only when a publishable key is present/valid.
- **Backend** uses `fastapi-clerk-auth` when `CLERK_JWKS_URL` is configured.
  - See `backend/app/core/auth.py`.

### Agent access (X-Agent-Token)
Automation/agents can use the “agent” API surface:
- Endpoints under `/api/v1/agent/*` (router: `backend/app/api/agent.py`).
- Auth via `X-Agent-Token` (see `backend/app/core/agent_auth.py`, referenced from `backend/app/api/deps.py`).

### Background jobs (RQ / Redis)
The codebase includes RQ/Redis dependencies and a queue helper (`backend/app/workers/queue.py`).
If/when background jobs are added, the expected shape is:
- API enqueues work to Redis.
- A separate RQ worker process executes queued jobs.

## Key directories

Repo root:
- `compose.yml` — local/self-host stack
- `.env.example` — compose/local defaults
- `templates/` — shared templates

Backend:
- `backend/app/api/` — REST routers
- `backend/app/core/` — config/auth/logging/errors
- `backend/app/models/` — SQLModel models
- `backend/app/services/` — domain logic
- `backend/app/integrations/` — gateway client/protocol

Frontend:
- `frontend/src/app/` — Next.js routes
- `frontend/src/components/` — UI components
- `frontend/src/auth/` — Clerk gating/wrappers
- `frontend/src/lib/` — utilities + API base

## Where to start reading code

Backend:
1. `backend/app/main.py` — app + routers
2. `backend/app/core/config.py` — env + defaults
3. `backend/app/core/auth.py` — auth behavior
4. `backend/app/api/tasks.py` and `backend/app/api/agent.py` — core flows

Frontend:
1. `frontend/src/app/*` — main UI routes
2. `frontend/src/lib/api-base.ts` — backend calls
3. `frontend/src/auth/*` — “Clerk optional” behavior

## Notes / gotchas
- Mermaid rendering depends on the markdown renderer.
- If Compose loads `frontend/.env.example` directly, placeholder Clerk keys can accidentally enable Clerk; prefer user-managed env files.
