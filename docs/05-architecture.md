# Architecture

## Deep dives

- [Architecture deep dive](architecture/README.md)
- [Gateway protocol](openclaw_gateway_ws.md)

Mission Control is the **web UI + HTTP API** for operating OpenClaw. It’s where you manage boards, tasks, agents, approvals, and (optionally) gateway connections.

> Auth note: **Clerk is required for production**. The codebase includes gating so CI/local can run without “real” keys, but real deployments should configure Clerk.

## Components

- **Frontend**: Next.js app used by humans
  - Location: `frontend/`
  - Routes/pages: `frontend/src/app/*` (Next.js App Router)
  - API client: generated + custom fetch (see `frontend/src/api/*`, `frontend/src/lib/api-base.ts`)
- **Backend**: FastAPI service exposing REST endpoints
  - Location: `backend/`
  - Entrypoint: `backend/app/main.py`
  - API prefix: `/api/v1/*`
- **Database**: Postgres (see `compose.yml`)
- **Gateway integration (optional)**: backend may call into OpenClaw Gateways over WebSockets
  - Client/protocol list: `backend/app/services/openclaw/gateway_rpc.py`

## Diagram (conceptual)

```mermaid
flowchart LR
  U[User / Browser] -->|HTTP| FE[Next.js Frontend :3000]
  FE -->|HTTP /api/v1/*| BE[FastAPI Backend :8000]

  BE -->|SQL| PG[(Postgres :5432)]

  BE -->|WebSocket (optional)| GW[OpenClaw Gateway]
  GW --> OC[OpenClaw runtime]
```

## How requests flow

### 1) A human uses the UI

1. Browser loads the Next.js frontend (`frontend/`).
2. Frontend calls backend endpoints using `NEXT_PUBLIC_API_URL`.
3. Backend routes under `/api/v1/*` (`backend/app/main.py`) and reads/writes Postgres.

Common UI-driven data shapes:
- “boards/tasks” views → board/task CRUD + streams.
- “activity feed” → activity/events endpoints.

### 2) Authentication (Clerk)

- **Frontend**: Clerk is enabled only when a publishable key is present/valid.
  - Gating/wrappers: `frontend/src/auth/clerkKey.ts`, `frontend/src/auth/clerk.tsx`.
- **Frontend → backend**: API calls attach `Authorization: Bearer <token>` when available.
  - Token injection: `frontend/src/api/mutator.ts` (uses `window.Clerk.session.getToken()`).
- **Backend**: validates inbound auth and resolves a user context.
  - Implementation: `backend/app/core/auth.py` (uses `clerk_backend_api` SDK with `CLERK_SECRET_KEY`).

### 3) Agent automation surface (`/api/v1/agent/*`)

Agents can call a dedicated API surface:

- Router: `backend/app/api/agent.py` (prefix `/agent` → mounted under `/api/v1/agent/*`).
- Authentication: `X-Agent-Token` header (or agent-only Authorization bearer parsing).
  - Implementation: `backend/app/core/agent_auth.py`.

Typical agent flows:
- Heartbeat/presence updates
- Task comment posting (evidence)
- Board memory updates
- Lead coordination actions (if board-lead agent)

### 4) Streaming/feeds (server-sent events)

Some endpoints support streaming via SSE (`text/event-stream`).
Notes:
- Uses `sse-starlette` in backend routes (e.g. task/activity/memory routers).

### 5) Gateway integration (optional)

Mission Control can coordinate with OpenClaw Gateways over WebSockets.

- Protocol methods/events list: `backend/app/services/openclaw/gateway_rpc.py`.
- Operator-facing protocol docs: [Gateway WebSocket protocol](openclaw_gateway_ws.md).

## Where to start reading code

- Backend entrypoint + router wiring: `backend/app/main.py`
- Auth dependencies + access enforcement: `backend/app/api/deps.py`
- User auth: `backend/app/core/auth.py`
- Agent auth: `backend/app/core/agent_auth.py`
- Agent API surface: `backend/app/api/agent.py`
