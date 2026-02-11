# Repo tour

High-level map of the codebase so you can quickly find where to change things.

## Top-level
- `backend/` — FastAPI backend (API server)
- `frontend/` — Next.js frontend (web UI)
- `docs/` — documentation
- `compose.yml` — local/self-host stack (db + backend + frontend)
- `scripts/` — helper scripts

## Backend: where to look
- App entrypoint + router wiring: `backend/app/main.py`
- Routers: `backend/app/api/*`
- Settings/config: `backend/app/core/config.py`
- Auth (Clerk + agent token): `backend/app/core/auth.py`, `backend/app/core/agent_auth.py`
- Models: `backend/app/models/*`
- Services/domain logic: `backend/app/services/*`

## Frontend: where to look
- Routes (App Router): `frontend/src/app/*`
- Components: `frontend/src/components/*`
- API utilities: `frontend/src/lib/*` and `frontend/src/api/*`
- Auth (Clerk gating/wrappers): `frontend/src/auth/*`

## Where to change X

| You want to… | Start here |
|---|---|
| Add/modify an API endpoint | `backend/app/api/*` + `backend/app/main.py` |
| Change auth behavior | `backend/app/core/auth.py` + `frontend/src/auth/*` |
| Change a UI page | `frontend/src/app/*` |
| Update Compose topology | `compose.yml` |

Next: see [Architecture](05-architecture.md) for system-level flows.
