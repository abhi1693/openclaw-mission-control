# API / auth

This page documents how Mission Control’s API surface is organized and how authentication works.

For deeper backend architecture context, see:
- [Architecture](05-architecture.md)

## Base path

Evidence: `backend/app/main.py`.

- All API routes are mounted under: `/api/v1/*`

## OpenAPI / Swagger UI

Mission Control is a FastAPI app, so it serves its OpenAPI schema and interactive docs:

- OpenAPI JSON: `GET /openapi.json`
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`

### Exporting OpenAPI to a versioned artifact

Evidence: `backend/scripts/export_openapi.py`, `backend/README.md`.

From repo root:

```bash
cd backend
uv sync --extra dev
uv run python scripts/export_openapi.py
# writes: backend/openapi.json
```

## Auth model (two callers)

Mission Control has two primary actor types:

1) **User (Clerk)** — human UI/admin
2) **Agent (`X-Agent-Token`)** — automation

### User auth (Clerk)

Evidence:
- backend: `backend/app/core/auth.py`
- config: `backend/app/core/config.py`

- Frontend calls backend using `Authorization: Bearer <token>`.
- Backend validates requests using the Clerk Backend API SDK with `CLERK_SECRET_KEY`.

### Agent auth (`X-Agent-Token`)

Evidence:
- `backend/app/core/agent_auth.py`
- agent API surface: `backend/app/api/agent.py`

- Agents authenticate with `X-Agent-Token: <token>`.
- Token is verified against the agent’s stored `agent_token_hash`.

OpenAPI note:
- The OpenAPI schema models this as an `apiKey` security scheme named `AgentToken`.
- Some endpoints allow **either** `Authorization: Bearer ...` (admin user) **or** `X-Agent-Token` (agent).

## Route groups (modules)

Evidence: `backend/app/main.py` includes routers from `backend/app/api/*`.

| Module | Prefix (under `/api/v1`) | Purpose |
|---|---|---|
| `activity.py` | `/activity` | Activity listing and task-comment feed endpoints. |
| `agent.py` | `/agent` | Agent-scoped API routes for board operations and gateway coordination. |
| `agents.py` | `/agents` | Thin API wrappers for async agent lifecycle operations. |
| `approvals.py` | `/boards/{board_id}/approvals` | Approval listing, streaming, creation, and update endpoints. |
| `auth.py` | `/auth` | Authentication bootstrap endpoints for the Mission Control API. |
| `board_group_memory.py` | `/board-groups/{group_id}/memory` and `/boards/{board_id}/group-memory` | Board-group memory CRUD and streaming endpoints. |
| `board_groups.py` | `/board-groups` | Board group CRUD, snapshot, and heartbeat endpoints. |
| `board_memory.py` | `/boards/{board_id}/memory` | Board memory CRUD and streaming endpoints. |
| `board_onboarding.py` | `/boards/{board_id}/onboarding` | Board onboarding endpoints for user/agent collaboration. |
| `boards.py` | `/boards` | Board CRUD and snapshot endpoints. |
| `gateway.py` | `/gateways` | Thin gateway session-inspection API wrappers. |
| `gateways.py` | `/gateways` | Thin API wrappers for gateway CRUD and template synchronization. |
| `metrics.py` | `/metrics` | Dashboard metric aggregation endpoints. |
| `organizations.py` | `/organizations` | Organization management endpoints and membership/invite flows. |
| `souls_directory.py` | `/souls-directory` | API routes for searching and fetching souls-directory markdown entries. |
| `tasks.py` | `/boards/{board_id}/tasks` | Task API routes for listing, streaming, and mutating board tasks. |
| `users.py` | `/users` | User self-service API endpoints for profile retrieval and updates. |

## Backend API layer notes (how modules are organized)

Evidence: `backend/app/main.py`, `backend/app/api/*`, `backend/app/api/deps.py`.

### Conventions

- Each file under `backend/app/api/*` typically declares an `APIRouter` (`router = APIRouter(...)`) and defines endpoints with decorators like `@router.get(...)`, `@router.post(...)`, etc.
- Board-scoped modules embed `{board_id}` in the prefix (e.g. `/boards/{board_id}/tasks`).
- Streaming endpoints usually expose **SSE** endpoints at `.../stream` (see `sse-starlette` usage).

### Where key behaviors live

- **Router wiring / base prefix**: `backend/app/main.py` mounts these routers under `/api/v1/*`.
- **Auth / access control** is mostly expressed through dependencies (see `backend/app/api/deps.py`):
  - `require_admin_auth` — require an authenticated *admin user*.
  - `require_admin_or_agent` — allow either an admin user or an authenticated agent.
  - `get_board_for_actor_read` / `get_board_for_actor_write` — enforce board access for the calling actor.
  - `require_org_member` / `require_org_admin` — enforce org membership/admin for user callers.
- **Agent-only surface**: `backend/app/api/agent.py` uses `get_agent_auth_context` (X-Agent-Token) and contains board/task/memory endpoints specifically for automation.

### Module-by-module map (prefix, key endpoints, and pointers)

This is a “where to look” index, not a full OpenAPI dump. For exact parameters and response shapes, see:
- route module file (`backend/app/api/<module>.py`)
- schemas (`backend/app/schemas/*`)
- models (`backend/app/models/*`)
- services (`backend/app/services/*`)

| Module | Prefix (under `/api/v1`) | Key endpoints (examples) | Main deps / auth | Pointers (schemas/models/services) |
|---|---|---|---|---|
| `activity.py` | `/activity` | `GET /activity` (events); `GET /activity/task-comments` + `/stream` | `require_admin_or_agent`, `require_org_member` | `app/models/activity_events.py`, `app/schemas/activity_events.py` |
| `agent.py` | `/agent` | agent automation surface: boards/tasks/memory + gateway coordination | `get_agent_auth_context` (X-Agent-Token) | `backend/app/core/agent_auth.py`, `backend/app/services/openclaw/*` |
| `agents.py` | `/agents` | agent lifecycle + SSE stream + heartbeat | org-admin gated for user callers; some endpoints allow agent access via deps | `app/schemas/agents.py`, `app/services/openclaw/provisioning_db.py` |
| `approvals.py` | `/boards/{board_id}/approvals` | list/create/update approvals + `/stream` | `require_admin_or_agent` + board access deps | `app/models/approvals.py`, `app/schemas/approvals.py` |

## Where authorization is enforced

Evidence: `backend/app/api/deps.py`.

Most route modules don’t “hand roll” access checks; they declare dependencies:

- `require_admin_auth` — admin user only.
- `require_admin_or_agent` — admin user OR authenticated agent.
- `get_board_for_actor_read` / `get_board_for_actor_write` — board access for user/agent.
- `require_org_member` / `require_org_admin` — org membership/admin for user callers.

## “Start here” pointers for maintainers

- Router wiring: `backend/app/main.py`
- Access dependencies: `backend/app/api/deps.py`
- User auth: `backend/app/core/auth.py`
- Agent auth: `backend/app/core/agent_auth.py`
- Agent automation surface: `backend/app/api/agent.py`
