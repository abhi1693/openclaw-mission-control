# Mission Control — Architecture

Mission Control is the **web UI + HTTP API** for operating OpenClaw. It’s where you manage boards, tasks, agents, approvals, and (optionally) gateway connections.

> Auth note: **Clerk is required for now** (current product direction). The codebase includes gating so CI/local can run with placeholders, but real deployments should configure Clerk.

At a high level:
- The **frontend** is a Next.js app used by humans.
- The **backend** is a FastAPI service that exposes REST endpoints under `/api/v1/*`.
- **Postgres** stores core state (boards/tasks/agents/etc.).

## Components

### Diagram (conceptual)

```mermaid
flowchart LR
  U[User / Browser] -->|HTTP| FE[Next.js Frontend :3000]
  FE -->|HTTP /api/v1/*| BE[FastAPI Backend :8000]

  BE -->|SQL| PG[(Postgres :5432)]

  BE -->|WebSocket (optional integration)| GW[OpenClaw Gateway]
  GW --> OC[OpenClaw runtime]
```

### Frontend (Next.js)
- Location: `frontend/`
- Routes/pages: `frontend/src/app/*` (Next.js App Router)
- API utilities: `frontend/src/lib/*` and `frontend/src/api/*`

**Auth (Clerk, required)**
- Clerk is required for real deployments and currently required by backend config (see `backend/app/core/config.py`).
- Frontend uses Clerk when keys are configured; see `frontend/src/auth/clerkKey.ts` and `frontend/src/auth/clerk.tsx`.
- Backend authenticates requests using the Clerk SDK and `CLERK_SECRET_KEY`; see `backend/app/core/auth.py`.


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
  - Migrations: `backend/migrations/*`
  - DB/migrations doc: [Backend DB layer & migrations](db-and-migrations.md)

### Gateway integration (optional)
Mission Control can call into an OpenClaw Gateway over WebSockets.
- Client + protocol: `backend/app/services/openclaw/gateway_rpc.py`
- Protocol doc: [Gateway WebSocket protocol](../openclaw_gateway_ws.md)
- Base gateway config (getting started): [Gateway base config](../openclaw_gateway_base_config.md)

## Request flows

### UI → API
1. Browser loads the Next.js frontend.
2. Frontend calls backend endpoints under `/api/v1/*`.
3. Backend reads/writes Postgres.

### Auth (Clerk — required)
- **Frontend** uses Clerk when keys are configured (see `frontend/src/auth/*`).
- **Backend** authenticates requests using the Clerk SDK and `CLERK_SECRET_KEY` (see `backend/app/core/auth.py`).
### Agent access (X-Agent-Token)
Automation/agents can use the “agent” API surface:
- Endpoints under `/api/v1/agent/*` (router: `backend/app/api/agent.py`).
- Auth via `X-Agent-Token` (see `backend/app/core/agent_auth.py`, referenced from `backend/app/api/deps.py`).

### Background jobs
There is currently no queue runtime configured in this repo.

## Key directories

Repo root:
- `compose.yml` — local/self-host stack
- `.env.example` — compose/local defaults
- `backend/templates/` — shared templates

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
3. `frontend/src/auth/*` — Clerk integration (gated for CI/local)

## Related docs
- Self-host (Docker Compose): see repo root README: [Quick start (self-host with Docker Compose)](../../README.md#quick-start-self-host-with-docker-compose)
- Production-ish deployment: [Production notes](../production/README.md)
- Testing (Cypress/Clerk): [Testing guide](../testing/README.md)
- Troubleshooting: [Troubleshooting](../troubleshooting/README.md)

## Notes / gotchas
- Mermaid rendering depends on the markdown renderer.
- `NEXT_PUBLIC_API_URL` must be reachable from the browser (host), not just from within Docker.
- If Compose loads `frontend/.env.example` directly, placeholder Clerk keys can accidentally enable Clerk; prefer user-managed env files.
