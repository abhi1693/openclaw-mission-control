# Development

This section is for contributors developing Mission Control locally.

## Recommended workflow (fast loop)

Run Postgres in Docker, run backend + frontend on your host.

### 1) Start Postgres

From repo root:

```bash
cp .env.example .env
docker compose -f compose.yml --env-file .env up -d db
```

### 2) Run the backend (dev)

```bash
cd backend
cp .env.example .env

uv sync --extra dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl -f http://localhost:8000/healthz
```

### 3) Run the frontend (dev)

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000.

## Useful repo-root commands

```bash
make help
make setup
make check
```

- `make setup`: sync backend + frontend deps
- `make check`: lint + typecheck + tests + build (closest CI parity)

## Related docs

- [Testing](../testing/README.md)
- [Release checklist](../release/README.md)
