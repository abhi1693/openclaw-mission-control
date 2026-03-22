# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

OpenClaw Mission Control — a full-stack operations platform for agent orchestration, governance, approval workflows, and gateway management. FastAPI backend, Next.js frontend, PostgreSQL, Redis.

## Architecture

- **Backend**: FastAPI + SQLAlchemy/SQLModel + Alembic migrations + RQ background workers
- **Frontend**: Next.js 16 (app router) + React 19 + React Query + Tailwind CSS
- **API Client**: Auto-generated via Orval from the backend's OpenAPI schema into `frontend/src/api/generated/` — **never edit by hand**
- **Auth**: Two modes — `local` (shared bearer token, min 50 chars) or `clerk` (Clerk JWT)
- **Docker services**: `db` (Postgres 16), `redis` (Redis 7), `backend`, `frontend`, `webhook-worker`

### Backend (`backend/app/`)

- `api/` — FastAPI route handlers. All routes mounted under `/api/v1/`.
- `models/` — SQLAlchemy/SQLModel ORM models
- `schemas/` — Pydantic request/response schemas
- `services/` — Business logic (activity logging, webhooks, queue workers, board lifecycle, mentions)
- `core/` — Config (Pydantic BaseSettings), auth, error handling, rate limiting, security headers, logging
- `db/` — Database session management
- `templates/` — Backend-shipped templates for gateway flows

### Frontend (`frontend/src/`)

- `app/` — Next.js app router pages (dashboard, agents, boards, board-groups, approvals, gateways, tags, settings, etc.)
- `api/generated/` — Orval-generated React Query hooks (tags-split mode). Custom fetch mutator at `src/api/mutator.ts`.
- `components/` — Shared UI components (Radix UI primitives, Lucide icons)
- `hooks/` — Custom React hooks
- `lib/` — Utilities
- `auth/` — Auth provider and helpers

### Migrations

- Location: `backend/migrations/versions/`
- **Policy: one migration per PR.** CI enforces this. If you have multiple Alembic heads, create a merge migration.
- Validate with `make backend-migration-check` (spins up a temp Postgres, tests upgrade→downgrade→upgrade)

## Commands

All from repo root:

```bash
# Setup
make setup                     # Install backend (uv sync) + frontend (npm install) deps

# Full CI parity
make check                     # lint + typecheck + scoped coverage + frontend tests + build

# Docker
make docker-up                 # Start full stack (db, redis, backend, frontend, webhook-worker)
make docker-down               # Stop
make docker-watch              # Start with auto-rebuild on frontend changes

# Fast local dev loop
docker compose -f compose.yml --env-file .env up -d db    # Postgres only
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev                                  # http://localhost:3000

# Backend
make backend-test              # pytest
make backend-coverage          # pytest with 100% coverage gate on error_handling + mentions
make backend-lint              # isort/black check + flake8 + mypy
make backend-typecheck         # mypy --strict
make backend-migrate           # alembic upgrade head
make backend-migration-check   # Full migration graph + reversible path validation

# Frontend
make frontend-test             # vitest with coverage
make frontend-lint             # eslint
make frontend-typecheck        # tsc --noEmit
make frontend-build            # next build

# API client regeneration (backend must be running on 127.0.0.1:8000)
make api-gen

# Single backend test
cd backend && uv run pytest tests/test_foo.py -k "test_name"

# Single frontend test
cd frontend && npx vitest run src/path/to/test.test.ts

# E2E (Cypress)
cd frontend && npm run e2e          # headless
cd frontend && npm run e2e:open     # interactive

# Formatting
make format                    # Auto-format backend (isort+black) + frontend (prettier)

# Docs
make docs-check                # Lint markdown + check links
```

## Coding Conventions

- **Python**: Black + isort + flake8 + mypy strict. Max line length **100**. `snake_case`. Target Python 3.12. Black and isort exclude `migrations/versions/`.
- **TypeScript/React**: ESLint + Prettier. `PascalCase` components, `camelCase` variables/functions. Prefix intentionally unused destructured variables with `_`.
- **Commits**: Conventional Commits — `feat:`, `fix:`, `docs:`, `test(core):`, etc.
- **Branches**: Feature branches from latest `origin/master`.
- **PRs**: Small and focused. Include what changed, why, test evidence (`make check`), linked issue, screenshots for UI changes.

## Coverage Policy

`make backend-coverage` enforces **100% statement + branch coverage** on a scoped set of modules (`app.core.error_handling`, `app.services.mentions`). Overall backend coverage is not gated yet — scope expands as tests are added.

## Pre-commit Hooks

Configured in `.pre-commit-config.yaml`: end-of-file-fixer, trailing-whitespace, check-yaml, check-added-large-files, Black, isort, flake8 (all scoped to `backend/**/*.py`).

## Environment

- Copy `.env.example` → `.env` at repo root (and optionally `backend/.env.example` → `backend/.env`, `frontend/.env.example` → `frontend/.env.local`)
- `LOCAL_AUTH_TOKEN` must be set (min 50 chars) when `AUTH_MODE=local`
- `BASE_URL` must match the public backend origin
- `NEXT_PUBLIC_API_URL=auto` resolves to `http(s)://<current-host>:8000`; set explicitly behind a reverse proxy

## CI

GitHub Actions (`ci.yml`) runs three jobs:
1. **check** — lint, typecheck, scoped coverage, frontend tests + build, migration validation, docs lint
2. **installer** — tests `install.sh` on macOS + Linux (docker and local modes)
3. **e2e** — Cypress with Chrome
