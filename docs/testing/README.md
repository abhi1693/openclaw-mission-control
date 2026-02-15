# Testing

This guide describes how to run Mission Control tests locally.

## Quick start (repo root)

```bash
make setup
make check
```

`make check` is the closest thing to “CI parity”:

- backend: lint + typecheck + unit tests (with scoped coverage gate)
- frontend: lint + typecheck + unit tests (Vitest) + production build

## Backend tests

From repo root:

```bash
make backend-test
make backend-coverage
```

Or from `backend/`:

```bash
cd backend
uv run pytest
```

Notes:

- Some tests may require a running Postgres (see root `compose.yml`).
- `make backend-coverage` enforces a strict coverage gate on a scoped set of modules.

## Frontend tests

From repo root:

```bash
make frontend-test
```

Or from `frontend/`:

```bash
cd frontend
npm run test
npm run test:watch
```

## End-to-end (Cypress)

The frontend has Cypress configured in `frontend/cypress/`.

Typical flow:

1) Start the stack (or start backend + frontend separately)
2) Run Cypress

Example (two terminals):

```bash
# terminal 1
cp .env.example .env
docker compose -f compose.yml --env-file .env up -d --build
```

```bash
# terminal 2
cd frontend
npm run e2e
```

Or run interactively:

```bash
cd frontend
npm run e2e:open
```
