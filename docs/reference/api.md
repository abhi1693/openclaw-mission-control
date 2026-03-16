# API reference (notes + conventions)

Mission Control exposes a JSON HTTP API (FastAPI) under `/api/v1/*`.

- Default backend base URL (local): `http://localhost:8000`
- Health endpoints:
  - `GET /health` (liveness)
  - `GET /healthz` (liveness alias)
  - `GET /readyz` (readiness)

## OpenAPI / Swagger

- OpenAPI schema: `GET /openapi.json`
- Swagger UI (FastAPI default): `GET /docs`

> If you are building clients, prefer generating from `openapi.json`.

## API versioning

- Current prefix: `/api/v1`
- Backwards compatibility is **best-effort** while the project is under active development.

## Authentication

All protected endpoints expect a bearer token:

```http
Authorization: Bearer <token>
```

Auth mode is controlled by `AUTH_MODE`:

- `local`: shared bearer token auth (token is `LOCAL_AUTH_TOKEN`)
- `clerk`: Clerk JWT auth

Notes:
- The frontend uses the same bearer token scheme in local mode (users paste the token into the UI).
- Many “agent” endpoints use an agent token header instead (see below).

### Agent auth (Mission Control agents)

Some endpoints are designed for autonomous agents and use an agent token header:

```http
X-Agent-Token: <agent-token>
```

On shared user/agent routes, the backend also accepts `Authorization: Bearer <agent-token>` after user auth does not resolve. When in doubt, consult the route’s dependencies (e.g., `require_user_or_agent`).

Agent authentication is rate-limited to **20 requests per 60 seconds per IP**. Exceeding this limit returns `429 Too Many Requests`.

## Authorization / permissions model (high level)

The backend distinguishes between:

- **users** (humans) authenticated via `AUTH_MODE`
- **agents** authenticated via agent tokens

Common patterns:

- **User-only** endpoints: require an authenticated human user (not an agent). Organization-level admin checks are enforced separately where needed (`require_org_admin`).
- **User or agent** endpoints: allow either an authenticated human user or an authenticated agent.
- **Board-scoped access**: user/agent access may be restricted to a specific board.

> SOC2 note: the API produces an audit-friendly request id (see below), but role/permission policy should be documented per endpoint as we stabilize.

## Security headers

All API responses include the following security headers by default:

| Header | Default |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | _(disabled)_ |

Each header is configurable via `SECURITY_HEADER_*` environment variables. Set a variable to blank to disable the corresponding header (see [configuration reference](configuration.md)).

## Rate limits

The following per-IP rate limits are enforced on sensitive endpoints:

| Endpoint | Limit | Window |
| --- | --- | --- |
| Agent authentication (`X-Agent-Token` or agent bearer fallback on shared routes) | 20 requests | 60 seconds |
| Webhook ingest (`POST .../webhooks/{id}`) | 60 requests | 60 seconds |

When a rate limit is exceeded, the API returns `429 Too Many Requests`.

Set `RATE_LIMIT_BACKEND` to choose the storage backend:

| Backend | Value | Behavior |
| --- | --- | --- |
| In-memory (default) | `memory` | Per-process limits; no external dependencies. |
| Redis | `redis` | Shared across all workers. Set `RATE_LIMIT_REDIS_URL` or it falls back to `RQ_REDIS_URL`. Connectivity is validated at startup; transient failures fail open. |

> **Note:** When using the in-memory backend, limits are per-process. Multi-process deployments should either switch to the Redis backend or apply rate limiting at the reverse proxy layer (nginx `limit_req`, Caddy, etc.).

## Request IDs

Every response includes an `X-Request-Id` header.

- Clients may supply their own `X-Request-Id`; otherwise the server generates one.
- Use this id to correlate client reports with server logs.

## Errors

Errors are returned as JSON with a stable top-level shape:

```json
{
  "detail": "...",
  "request_id": "..."
}
```

Common status codes:

- `401 Unauthorized`: missing/invalid credentials
- `403 Forbidden`: authenticated but not allowed
- `404 Not Found`: resource missing (or not visible)
- `413 Content Too Large`: request payload exceeds size limit (e.g. webhook ingest 1 MB cap)
- `422 Unprocessable Entity`: request validation error
- `429 Too Many Requests`: per-IP rate limit exceeded
- `500 Internal Server Error`: unhandled server errors

Validation errors (`422`) typically return `detail` as a list of structured field errors (FastAPI/Pydantic style).

## Pagination

List endpoints commonly return an `items` array with paging fields (varies by endpoint). If you’re implementing new list endpoints, prefer consistent parameters:

- `limit`
- `offset`

…and return:

- `items: []`
- `total`
- `limit`
- `offset`

## Examples (curl)

### Health

```bash
curl -f http://localhost:8000/healthz
```

### Agent heartbeat check-in

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/heartbeat \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Tessa","board_id":"<board-id>","status":"online"}'
```

### List tasks for a board

```bash
curl -s "http://localhost:8000/api/v1/agent/boards/<board-id>/tasks?status=inbox&limit=10" \
  -H "X-Agent-Token: $AUTH_TOKEN"
```

## Gaps / follow-ups

- Per-endpoint documentation of:
  - required auth header (`Authorization` vs `X-Agent-Token`)
  - required role (admin vs member vs agent)
  - common error responses per endpoint
- Rate limits are documented above; consider exposing them via OpenAPI `x-ratelimit-*` extensions.
- Add canonical examples for:
  - creating/updating tasks + comments
  - board memory streaming
  - approvals workflow
