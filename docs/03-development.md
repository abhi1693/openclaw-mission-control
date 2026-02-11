# Development

This page is the contributor workflow for Mission Control.

It’s intentionally **CI-aligned**: if you can run these commands locally, you should not be surprised by CI.

## Prerequisites

- Docker + Docker Compose v2 (`docker compose`)
- Python **3.12+** + [`uv`](https://github.com/astral-sh/uv)
- Node.js + npm
  - CI pins **Node 20** via `.github/workflows/ci.yml` (`actions/setup-node@v4`, `node-version: "20"`).

## Repo layout

- Backend: `backend/` (FastAPI)
- Frontend: `frontend/` (Next.js)
- Canonical commands: `Makefile`

## Setup (one command)

From repo root:

```bash
make setup
```

What it does (evidence: `Makefile`):
- `make backend-sync`: `cd backend && uv sync --extra dev`
- `make frontend-sync`: verifies node tooling (`scripts/with_node.sh --check`), then `npm install` in `frontend/`

## Run the stack (two recommended loops)

### Loop A (recommended): DB via Compose, app in dev mode

1) Start Postgres:

```bash
cp .env.example .env

docker compose -f compose.yml --env-file .env up -d db
```

2) Backend dev server:

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

3) Frontend dev server:

```bash
cd frontend
cp .env.example .env.local
# ensure this is correct for the browser:
# NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev
```

### Loop B: all-in-one Compose

```bash
cp .env.example .env

docker compose -f compose.yml --env-file .env up -d --build
```

## Checks (CI parity)

### Run everything

```bash
make check
```

Evidence: `Makefile`.

### Common targeted commands

Backend:
```bash
make backend-lint       # flake8
make backend-typecheck  # mypy --strict
make backend-test       # pytest
make backend-coverage   # pytest + scoped 100% coverage gate
make backend-migrate    # alembic upgrade head
```

Frontend:
```bash
make frontend-lint      # eslint
make frontend-typecheck # tsc
make frontend-test      # vitest
make frontend-build     # next build
```

## Cypress E2E

Evidence: `docs/testing/README.md`, `.github/workflows/ci.yml`.

- E2E uses Clerk’s official Cypress integration (`@clerk/testing`).
- Local run pattern:

```bash
# terminal 1
cd frontend
npm run dev -- --hostname 0.0.0.0 --port 3000

# terminal 2
cd frontend
npm run e2e -- --browser chrome
```

## Deep dives

- [Testing guide](testing/README.md)
- [Troubleshooting deep dive](troubleshooting/README.md)
