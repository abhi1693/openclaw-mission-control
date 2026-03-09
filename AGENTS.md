# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI service. Main app code lives in `backend/app/` with API routes in `backend/app/api/`, data models in `backend/app/models/`, schemas in `backend/app/schemas/`, and service logic in `backend/app/services/`.
- `backend/migrations/`: Alembic migrations (`backend/migrations/versions/` for generated revisions).
- `backend/tests/`: pytest suite (`test_*.py` naming).
- `backend/templates/`: backend-shipped templates used by gateway flows.
- `frontend/`: Next.js app. Routes under `frontend/src/app/`, shared components under `frontend/src/components/`, utilities under `frontend/src/lib/`.
- `frontend/src/api/generated/`: generated API client; regenerate instead of editing by hand.
- `docs/`: contributor and operations docs (start at `docs/README.md`).

## Build, Test, and Development Commands
- `make setup`: install/sync backend and frontend dependencies.
- `make check`: closest CI parity run (lint, typecheck, tests/coverage, frontend build).
- `docker compose -f compose.yml --env-file .env up -d --build`: run full stack.
- Fast local loop:
  - `docker compose -f compose.yml --env-file .env up -d db`
  - `cd backend && uv run uvicorn app.main:app --reload --port 8000`
  - `cd frontend && npm run dev`
- `make api-gen`: regenerate frontend API client (backend must be on `127.0.0.1:8000`).

## Coding Style & Naming Conventions
- Python: Black + isort + flake8 + strict mypy. Max line length is 100. Use `snake_case`.
- TypeScript/React: ESLint + Prettier. Components use `PascalCase`; variables/functions use `camelCase`.
- For intentionally unused destructured TS variables, prefix with `_` to satisfy lint config.

## Testing Guidelines
- Backend: pytest via `make backend-test`; coverage policy via `make backend-coverage` (writes `backend/coverage.xml` and `backend/coverage.json`).
- Frontend: vitest + Testing Library via `make frontend-test` (coverage in `frontend/coverage/`).
- Add or update tests whenever behavior changes.

## Commit & Pull Request Guidelines
- Follow Conventional Commits (seen in history), e.g. `feat: ...`, `fix: ...`, `docs: ...`, `test(core): ...`.
- Keep PRs focused and based on latest `master`.
- Include: what changed, why, test evidence (`make check` or targeted commands), linked issue, and screenshots/logs when UI or operator workflow changes.

## Security & Configuration Tips
- Never commit secrets. Copy from `.env.example` and keep real values in local `.env`.
- Report vulnerabilities privately via GitHub security advisories, not public issues.

---

## Mission Control Quick Reference

### Core API Endpoints

| Resource | Endpoint | Methods |
|----------|----------|---------|
| Gateways | `/api/v1/gateways` | GET, POST |
| Boards | `/api/v1/boards` | GET, POST, PATCH, DELETE |
| Tasks | `/api/v1/boards/{board_id}/tasks` | GET, POST, PATCH |
| Agents | `/api/v1/agents` | GET, POST |
| Tags | `/api/v1/tags` | GET, POST |
| Approvals | `/api/v1/approvals` | GET, POST |

### Authentication

```bash
# User auth (local mode)
Authorization: Bearer <LOCAL_AUTH_TOKEN>

# Agent auth
X-Agent-Token: <agent-token>
```

### Task Lifecycle

```
inbox → in_progress → review → done
```

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `AUTH_MODE` | `local` or `clerk` |
| `LOCAL_AUTH_TOKEN` | Bearer token (≥50 chars) |
| `CORS_ORIGINS` | Allowed frontend origins |
| `NEXT_PUBLIC_API_URL` | Backend URL (browser-reachable) |

### Gateway Connection Checklist

1. OpenClaw gateway running: `openclaw gateway`
2. `gateway.controlUi.allowedOrigins` includes Mission Control origin
3. `gateway.bind` set to `lan` for network access
4. Device pairing approved: `openclaw devices approve <id>`
5. Docker: `extra_hosts: ["host.docker.internal:host-gateway"]`

### Common API Examples

```bash
# Create board
curl -X POST http://localhost:8000/api/v1/boards \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Board","slug":"board","gateway_id":"<uuid>","description":"Desc"}'

# Create task
curl -X POST http://localhost:8000/api/v1/boards/{board_id}/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Task","status":"inbox"}'

# Update task status
curl -X PATCH http://localhost:8000/api/v1/boards/{board_id}/tasks/{task_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"done"}'

# Create agent
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Agent","board_id":"<uuid>","interval":"10m"}'
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "origin not allowed" | Add origin to `gateway.controlUi.allowedOrigins` |
| "pairing required" | `openclaw devices approve <request-id>` |
| Frontend can't reach backend | Check `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` |
| Task can't be marked done | Board has `require_approval_for_done: true` |

### Documentation

- [Gateway Connection Troubleshooting](./docs/troubleshooting/gateway-connection.md)
- [API Reference](./docs/reference/api.md)
- [Configuration Reference](./docs/reference/configuration.md)
- [OpenClaw Baseline Config](./docs/openclaw_baseline_config.md)
