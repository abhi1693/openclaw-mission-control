# Deployment / Self-hosting (Docker Compose)

This guide covers how to self-host **OpenClaw Mission Control** using the repository’s `compose.yml`.

> Scope
> - This is a **dev-friendly self-host** setup intended for local or single-host deployments.
> - For production hardening (TLS, backups, external Postgres, observability), see **Production notes** below.

## What you get

When running Compose, you get:

- **Postgres** database (persistent volume)
- **Backend API** (FastAPI) on `http://localhost:${BACKEND_PORT:-8000}`
  - Health check: `GET /healthz`
- **Frontend UI** (Next.js) on `http://localhost:${FRONTEND_PORT:-3000}`

Auth is configurable per deployment:
- `AUTH_MODE=local` (self-host default; shared bearer token)
- `AUTH_MODE=clerk` (Clerk JWT auth; backend requires `CLERK_SECRET_KEY`)

## Requirements

- Docker Engine
- Docker Compose **v2** (`docker compose ...`)
- Recommended: **4GB+ RAM** (frontend build can be memory/CPU intensive)

## Quick start (self-host)

From repo root:

```bash
cp .env.example .env

# REQUIRED for local mode:
# set LOCAL_AUTH_TOKEN in .env to a non-placeholder value with at least 50 characters.

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
- `backend` (FastAPI)
- `frontend` (Next.js)

### Ports

By default:

- Postgres: `5432` (`POSTGRES_PORT`)
- Backend: `8000` (`BACKEND_PORT`)
- Frontend: `3000` (`FRONTEND_PORT`)

Ports are sourced from `.env` (passed via `--env-file .env`) and wired into `compose.yml`.

### Volumes (data persistence)

Compose creates named volumes:

- `postgres_data` → Postgres data directory

These persist across `docker compose down`.

## Environment strategy

### Root `.env` (Compose)

- Copy the template: `cp .env.example .env`
- Edit values as needed (ports, auth mode, tokens, API URL, etc.)

Compose is invoked with:

```bash
docker compose -f compose.yml --env-file .env ...
```

### Backend env

The backend container loads `./backend/.env.example` via `env_file` and then overrides the DB URL for container networking.

If you need backend customization, prefer creating a real `backend/.env` and updating compose to use it (optional improvement).

### Frontend env

`compose.yml` intentionally **does not** load `frontend/.env.example` at runtime, because it may contain non-empty placeholders.

Instead, it supports an optional user-managed env file:

- `frontend/.env` (not committed)

If present, Compose will load it.

## Authentication modes

Mission Control supports two deployment auth modes:

- `AUTH_MODE=local`: shared bearer token auth (self-host default)
- `AUTH_MODE=clerk`: Clerk JWT auth

### Local mode (self-host default)

Set in `.env` (repo root):

```env
AUTH_MODE=local
LOCAL_AUTH_TOKEN=replace-with-random-token-at-least-50-characters
```

Set frontend mode (optional override in `frontend/.env`):

```env
NEXT_PUBLIC_AUTH_MODE=local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Users enter `LOCAL_AUTH_TOKEN` in the local login screen.

### Clerk mode

Set in `.env` (repo root):

```env
AUTH_MODE=clerk
```

Create `backend/.env` with at least:

```env
CLERK_SECRET_KEY=sk_test_your_real_key
CLERK_API_URL=https://api.clerk.com
CLERK_VERIFY_IAT=true
CLERK_LEEWAY=10.0
```

Create `frontend/.env` with at least:

```env
NEXT_PUBLIC_AUTH_MODE=clerk
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_real_key
```

**Security:** treat `LOCAL_AUTH_TOKEN` and `CLERK_SECRET_KEY` like passwords. Do not commit them.

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

## Reset / start fresh

Safe (keeps volumes/data):

```bash
docker compose -f compose.yml --env-file .env down
```

Destructive (removes volumes; deletes Postgres data):

```bash
docker compose -f compose.yml --env-file .env down -v
```

## Production notes (future)

If you’re running this beyond local dev, consider:

- Run Postgres as a managed service (or on a separate host)
- Add TLS termination (reverse proxy)
- Configure backups for Postgres volume
- Set explicit resource limits and healthchecks
- Pin image versions/tags and consider multi-arch builds
