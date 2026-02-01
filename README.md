# OpenClaw Agency — Pilot (Kanban)

MVP: **Next.js (frontend)** + **FastAPI (backend)** + **PostgreSQL**.

No auth (yet). The goal is simple visibility: everyone can see what exists and who owns it.

## Repo layout

- `frontend/` — Next.js App Router (TypeScript)
- `backend/` — FastAPI + SQLAlchemy + Alembic

## Database

Uses local Postgres:

- user: `postgres`
- password: `REDACTED`
- db: `openclaw_agency`

Backend config is in `backend/.env`.

## Run backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Run frontend

```bash
cd frontend
npm run dev
```

Open: http://localhost:3000

## API

- `GET /tasks`
- `POST /tasks`
- `PATCH /tasks/{id}`
- `DELETE /tasks/{id}`
