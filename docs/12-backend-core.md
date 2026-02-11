# Backend core modules (auth/config/logging/errors)

> Evidence basis: repo https://github.com/abhi1693/openclaw-mission-control @ commit `c3490630a4503d9c8142aaa3abf542e0d00b5035`.

This page documents the backend “core” layer under `backend/app/core/*` plus the API dependency module `backend/app/api/deps.py`.

It’s written for maintainers who need to answer:

- “Where does configuration come from?”
- “How do user vs agent auth work?”
- “Where are authorization decisions enforced?”
- “What’s the error envelope / request-id behavior?”
- “How is logging structured and how do I get request-context in logs?”

## Start here (reading order)

1. `backend/app/core/config.py` — settings + env file loading
2. `backend/app/core/logging.py` — structured logging + request context
3. `backend/app/core/error_handling.py` — request-id middleware + exception envelope
4. `backend/app/core/auth.py` — Clerk/user auth resolution
5. `backend/app/core/agent_auth.py` — agent token auth resolution
6. `backend/app/api/deps.py` — how routes declare and enforce access

## Configuration: loading & precedence

**Primary file:** `backend/app/core/config.py`

Key facts:
- Uses `pydantic-settings` (`BaseSettings`) to load typed settings from environment.
- Env files are loaded regardless of current working directory:
  - `backend/.env` (via `DEFAULT_ENV_FILE`)
  - then `.env` (repo root) as an additional source
  - See `Settings.model_config.env_file=[DEFAULT_ENV_FILE, ".env"]`.
- Unknown env vars are ignored (`extra="ignore"`).

Notable settings (security-sensitive in **bold**):
- `DATABASE_URL` / `database_url`
- `CORS_ORIGINS` / `cors_origins`
- `DB_AUTO_MIGRATE` / `db_auto_migrate`
- **`CLERK_SECRET_KEY` / `clerk_secret_key`** (must be non-empty; validator enforces it)
- `CLERK_API_URL`, `CLERK_VERIFY_IAT`, `CLERK_LEEWAY`
- logging knobs: `LOG_LEVEL`, `LOG_FORMAT`, `LOG_USE_UTC`, `REQUEST_LOG_SLOW_MS`, `REQUEST_LOG_INCLUDE_HEALTH`

### Deployment implication

- If a deployment accidentally starts the backend with an empty/placeholder `CLERK_SECRET_KEY`, the backend will fail settings validation at startup.

## Auth model split

The backend supports two top-level actor types:

- **User** (human UI / admin) — resolved from the `Authorization: Bearer <token>` header via Clerk.
- **Agent** (automation) — resolved from `X-Agent-Token: <token>` (and optionally `Authorization: Bearer <token>` for agent callers).

### User auth (Clerk) — `backend/app/core/auth.py`

What it does:
- Uses the `clerk_backend_api` SDK to authenticate requests (`authenticate_request(...)`) using `CLERK_SECRET_KEY`.
- Resolves a `AuthContext` containing `actor_type="user"` and a `User` model instance.
- The module includes helpers to fetch user profile details from Clerk (`_fetch_clerk_profile`) and to delete a Clerk user (`delete_clerk_user`).

Security-sensitive notes:
- Treat `CLERK_SECRET_KEY` as a credential; never log it.
- This code calls Clerk API endpoints over the network (timeouts and error handling matter).

### Agent auth (token hash) — `backend/app/core/agent_auth.py`

What it does:
- Requires a token header for protected agent endpoints:
  - Primary header: `X-Agent-Token`
  - Optional parsing: `Authorization: Bearer ...` (only in `get_agent_auth_context`, and only if `accept_authorization=True`)
- Validates token by comparing it against stored `agent_token_hash` values in the DB (`verify_agent_token`).
- “Touches” agent presence (`last_seen_at`, `status`) on authenticated requests.
  - For safe methods (`GET/HEAD/OPTIONS`), it commits immediately so read-only polling still shows the agent as online.

Security-sensitive notes:
- Token verification iterates over agents with a token hash. If this grows large, consider indexing/lookup strategy.
- Never echo full tokens in logs; current code logs only a prefix on invalid tokens.

## Authorization enforcement: `backend/app/api/deps.py`

This module is the primary “policy wiring” for most routes.

Key concepts:

- `require_admin_auth(...)`
  - Requires an authenticated *admin user*.
- `require_admin_or_agent(...)` → returns `ActorContext`
  - Allows either:
    - admin user (user auth via Clerk), or
    - authenticated agent (agent auth via X-Agent-Token).

Board/task access patterns:
- `get_board_for_actor_read` / `get_board_for_actor_write`
  - Enforces that the caller (user or agent) has the correct access to the board.
  - Agent access is restricted if the agent is bound to a specific board (`agent.board_id`).
- `get_task_or_404`
  - Loads a task and ensures it belongs to the requested board.

Org access patterns (user callers):
- `require_org_member` and `require_org_admin`
  - Resolve/require active org membership.
  - Provide an `OrganizationContext` with `organization` + `member`.

Maintainer tip:
- When debugging a “why is this 403/401?”, start by checking the route’s dependency stack (in the route module) and trace through the relevant dependency in `deps.py`.

## Logging: structure + request context

**Primary file:** `backend/app/core/logging.py`

Highlights:
- Defines a custom TRACE level (`TRACE_LEVEL = 5`).
- Uses `contextvars` to carry `request_id`, `method`, and `path` across async tasks.
- `AppLogFilter` injects `app`, `version`, and request context into each log record.
- Supports JSON output (`JsonFormatter`) and key=value (`KeyValueFormatter`) formats.

Where request context gets set:
- `backend/app/core/error_handling.py` middleware calls:
  - `set_request_id(...)`
  - `set_request_route_context(method, path)`

## Error envelope + request-id

**Primary file:** `backend/app/core/error_handling.py`

Key behaviors:
- Installs a `RequestIdMiddleware` (ASGI) that:
  - Accepts client-provided `X-Request-Id` or generates one.
  - Adds `X-Request-Id` to the response.
  - Emits structured “http.request.*” logs, including “slow request” warnings.
- Error responses include `request_id` when available:
  - Validation errors (`422`) return `{detail: <errors>, request_id: ...}`.
  - Other HTTP errors are wrapped similarly.

Maintainer tip:
- When debugging incidents, ask for the `X-Request-Id` from the client and use it to locate backend logs quickly.
