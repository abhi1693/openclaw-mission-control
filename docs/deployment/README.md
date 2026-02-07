# Deployment / Self-hosting (Docker Compose)

This guide covers how to self-host **OpenClaw Mission Control** using the repository’s `compose.yml`.

> Scope
> - This is a **dev-friendly self-host** setup intended for local or single-host deployments.
> - For production hardening (TLS, backups, external Postgres/Redis, observability), see **Production notes** below.

## What you get

When running Compose, you get:

- **Postgres** database (persistent volume)
- **Redis** (persistent volume)
- **Backend API** (FastAPI) on `http://localhost:${BACKEND_PORT:-8000}`
  - Health check: `GET /healthz`
- **Frontend UI** (Next.js) on `http://localhost:${FRONTEND_PORT:-3000}`

Auth (Clerk) is **optional**. If you don’t configure Clerk, the UI should behave as “auth disabled”.

## Requirements

- Docker Engine
- Docker Compose **v2** (`docker compose ...`)
- Recommended: **4GB+ RAM** (frontend build can be memory/CPU intensive)

## Quick start (self-host)

From repo root:

```bash
cp .env.example .env

docker compose -f compose.yml --env-file .env up -d --build
```

Check containers:

```bash
docker compose -f compose.yml ps
```

## Sanity checks

Backend health:

```bash
curl -f http://localhost:${BACKEND_PORT:-8000}/healthz
```

Frontend serving:

```bash
curl -I http://localhost:${FRONTEND_PORT:-3000}/
```

## Compose overview

### Services

`compose.yml` defines:

- `db` (Postgres 16)
- `redis` (Redis 7)
- `backend` (FastAPI)
- `frontend` (Next.js)

### Ports

By default:

- Postgres: `5432` (`POSTGRES_PORT`)
- Redis: `6379` (`REDIS_PORT`)
- Backend: `8000` (`BACKEND_PORT`)
- Frontend: `3000` (`FRONTEND_PORT`)

Ports are sourced from `.env` (passed via `--env-file .env`) and wired into `compose.yml`.

### Volumes (data persistence)

Compose creates named volumes:

- `postgres_data` → Postgres data directory
- `redis_data` → Redis data directory

These persist across `docker compose down`.

## Environment strategy

### Root `.env` (Compose)

- Copy the template: `cp .env.example .env`
- Edit values as needed (ports, Clerk URLs/keys, etc.)

Compose is invoked with:

```bash
docker compose -f compose.yml --env-file .env ...
```

### Backend env

The backend container loads `./backend/.env.example` via `env_file` and then overrides DB/Redis URLs for container networking.

If you need backend customization, prefer creating a real `backend/.env` and updating compose to use it (optional improvement).

### Frontend env

`compose.yml` intentionally **does not** load `frontend/.env.example` at runtime, because it may contain non-empty placeholders.

Instead, it supports an optional user-managed env file:

- `frontend/.env` (not committed)

If present, Compose will load it.

## Clerk (auth) notes

Mission Control can be configured with Clerk by setting env vars.

Common env vars (names may vary by deployment tooling):

- `MISSION_CONTROL_CLERK_SECRET_KEY`
- `MISSION_CONTROL_NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- `MISSION_CONTROL_CLERK_JWKS_URL`

**Security:** treat the secret key like a password. Do not commit it.

## Troubleshooting

### 1) Check container status

```bash
docker compose -f compose.yml ps
```

### 2) Tail logs

```bash
docker compose -f compose.yml --env-file .env logs -f --tail=200
```

### 3) Common issues

- **Docker permission denied** (`/var/run/docker.sock`)
  - Ensure your user is in the `docker` group and your session picked it up (re-login), or use a root/sudo-capable host.
- **Frontend build fails because of missing `public/`**
  - If the repo doesn’t have `frontend/public`, the Dockerfile should not `COPY public/`.
- **Backend build fails looking for `uv.lock`**
  - If backend build context is repo root, Dockerfile must copy `backend/uv.lock` not `uv.lock`.
- **Redis warning about `vm.overcommit_memory`**
  - Usually non-fatal for dev; for stability under load, set `vm.overcommit_memory=1` on the host.

## Reset / start fresh

Safe (keeps volumes/data):

```bash
docker compose -f compose.yml --env-file .env down
```

Destructive (removes volumes; deletes Postgres/Redis data):

```bash
docker compose -f compose.yml --env-file .env down -v
```

## Production notes (future)

If you’re running this beyond local dev, consider:

- Run Postgres and Redis as managed services (or on separate hosts)
- Add TLS termination (reverse proxy)
- Configure backups for Postgres volume
- Set explicit resource limits and healthchecks
- Pin image versions/tags and consider multi-arch builds
