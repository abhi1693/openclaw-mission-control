# OpenClaw Mission Control

[![CI](https://github.com/abhi1693/openclaw-mission-control/actions/workflows/ci.yml/badge.svg)](https://github.com/abhi1693/openclaw-mission-control/actions/workflows/ci.yml)

Mission Control is the **web UI and HTTP API** for operating OpenClaw. It’s designed for teams that want a clear control plane for managing **boards**, **tasks**, **agents**, **approvals**, and (optionally) **gateway connections**.

<img width="1878" height="870" alt="image" src="https://github.com/user-attachments/assets/b432d66f-8c9b-4c5e-b7e5-81c86a73aa7d" />

## Active development

OpenClaw Mission Control is under active development. Expect breaking changes and incomplete features as we iterate.

- Use at your own risk for production workloads.
- We welcome **bug reports**, **feature requests**, and **PRs** — see GitHub Issues: https://github.com/abhi1693/openclaw-mission-control/issues

## Architecture (high level)

Mission Control is a small, service-oriented stack:

- **Frontend:** Next.js (default http://localhost:3000)
- **Backend:** FastAPI (default http://localhost:8000)
- **Database:** Postgres
- **Gateway integration (optional):** WebSocket protocol documented in [Gateway WebSocket protocol](./docs/openclaw_gateway_ws.md)

## Documentation

Start with the docs landing page:
- [Docs landing](./docs/README.md)

Operational deep dives:
- Deployment: [Deployment guide](./docs/deployment/README.md)
- Production notes: [Production notes](./docs/production/README.md)
- Troubleshooting: [Troubleshooting](./docs/troubleshooting/README.md)

## Authentication

Mission Control supports two auth modes via `AUTH_MODE`:

- `local`: shared bearer token auth for self-hosted deployments
- `clerk`: Clerk JWT auth

`local` mode requires:
- backend: `AUTH_MODE=local`, `LOCAL_AUTH_TOKEN=<token>`
- frontend: `NEXT_PUBLIC_AUTH_MODE=local`, then enter the token in the login screen

`clerk` mode requires:
- backend: `AUTH_MODE=clerk`, `CLERK_SECRET_KEY=<secret>`
- frontend: `NEXT_PUBLIC_AUTH_MODE=clerk`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<key>`

## Deployment modes

### 1) Self-host (Docker Compose)

**Prerequisites:** Docker + Docker Compose v2 (`docker compose`)

```bash
cp .env.example .env

# REQUIRED for local auth mode:
# set LOCAL_AUTH_TOKEN to a non-placeholder value with at least 50 characters.

# REQUIRED: the browser must be able to reach the backend.
# NEXT_PUBLIC_API_URL must be reachable from the *browser* (host), not an internal Docker network name.
# Missing/blank NEXT_PUBLIC_API_URL will break frontend API calls (e.g. Activity feed).

# Auth defaults in .env.example are local mode.
# For production, set LOCAL_AUTH_TOKEN to a random value with at least 50 characters.
# For Clerk mode, set AUTH_MODE=clerk and provide Clerk keys.

docker compose -f compose.yml --env-file .env up -d --build
```

Open:
- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/healthz

Stop:

```bash
docker compose -f compose.yml --env-file .env down
```

Useful ops:

```bash
# Tail logs
docker compose -f compose.yml --env-file .env logs -f --tail=200

# Rebuild a single service
docker compose -f compose.yml --env-file .env up -d --build backend

# Reset data (DESTRUCTIVE: deletes Postgres volume)
docker compose -f compose.yml --env-file .env down -v
```

### 2) Contributor local dev loop (DB in Docker, apps on host)

This is the fastest workflow for contributors: run Postgres via Docker, and run the backend + frontend in dev mode.

See: [Development workflow](./docs/03-development.md)

## Testing and CI parity

- Testing guide: [Testing guide](./docs/testing/README.md)
- Coverage policy: [Coverage policy](./docs/coverage-policy.md)

From repo root:

```bash
make help
make setup
make check
```

## License

This project is licensed under the MIT License. See [`LICENSE`](./LICENSE).
