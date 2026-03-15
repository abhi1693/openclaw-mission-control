# Deployment

This section covers deploying Mission Control in self-hosted environments.

> **Goal**
> A simple, reproducible deploy that preserves the Postgres volume and supports safe upgrades.

## Deployment mode: single host (Docker Compose)

### Prerequisites

- Docker + Docker Compose v2 (`docker compose`)
- A host where the **browser** can reach the backend URL you configure (see `NEXT_PUBLIC_API_URL` below)

### 1) Configure environment

From repo root:

```bash
cp .env.example .env
```

Edit `.env`:

- `AUTH_MODE=local` (default)
- **Set** `LOCAL_AUTH_TOKEN` to a non-placeholder value (≥ 50 chars)
- Ensure `BASE_URL` matches the public backend origin if it is not `http://localhost:8000`
- Ensure `NEXT_PUBLIC_API_URL` is reachable from the browser (not a Docker-internal hostname)

Key variables (from `.env.example` / `compose.yml`):

- Frontend: `FRONTEND_PORT` (default `3000`)
- Backend: `BACKEND_PORT` (default `8000`)
- Postgres: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- Backend:
  - `DB_AUTO_MIGRATE` (default `true` in compose)
  - `CORS_ORIGINS` (default `http://localhost:3000`)
- Security headers (see [configuration reference](../reference/configuration.md)):
  - `SECURITY_HEADER_X_CONTENT_TYPE_OPTIONS` (default `nosniff`)
  - `SECURITY_HEADER_X_FRAME_OPTIONS` (default `DENY`)
  - `SECURITY_HEADER_REFERRER_POLICY` (default `strict-origin-when-cross-origin`)

### 2) Start the stack

```bash
docker compose -f compose.yml --env-file .env up -d --build
```

Open:

- Frontend: `http://localhost:${FRONTEND_PORT:-3000}`
- Backend health: `http://localhost:${BACKEND_PORT:-8000}/healthz`

To have containers restart on failure and after host reboot, add `restart: unless-stopped` to the `db`, `redis`, `backend`, and `frontend` services in `compose.yml`, and ensure Docker is configured to start at boot.

### 3) Verify

```bash
curl -f "http://localhost:${BACKEND_PORT:-8000}/healthz"
```

If the frontend loads but API calls fail, double-check:

- `NEXT_PUBLIC_API_URL` is set and reachable from the **browser**
- backend CORS includes the frontend origin (`CORS_ORIGINS`)

## Database persistence

The Compose stack uses a named volume:

- `postgres_data` → `/var/lib/postgresql/data`

This means:

- `docker compose ... down` preserves data
- `docker compose ... down -v` is **destructive** (deletes the DB volume)

## Migrations / upgrades

### Default behavior in Compose

In `compose.yml`, the backend container defaults:

- `DB_AUTO_MIGRATE=true`

So on startup the backend will attempt to run Alembic migrations automatically.

> **Warning**
> For zero/near-zero downtime, migrations must be **backward compatible** with the currently running app if you do rolling deploys.

### Safer operator pattern (manual migrations)

If you want more control, set `DB_AUTO_MIGRATE=false` and run migrations explicitly during deploy:

```bash
cd backend
uv run alembic upgrade head
```

## Container security

Both the backend and frontend Docker containers run as a **non-root user** (`appuser`). This is a security hardening measure.

If you bind-mount host directories into the containers, ensure the mounted paths are readable (and writable, if needed) by the container's non-root user. You can check the UID/GID with:

```bash
docker compose exec backend id
```

## Reverse proxy / TLS

Typical setup (outline):

- Put the frontend behind HTTPS (reverse proxy)
- Ensure the frontend can reach the backend over the configured `NEXT_PUBLIC_API_URL`

This section is intentionally minimal until we standardize a recommended proxy (Caddy/Nginx/Traefik).

## Run at boot (local install)

If you installed Mission Control **without Docker** (e.g. using `install.sh` with "local" mode, or inside a VM where Docker is not used), the installer does not configure run-at-boot. You can start the stack after each reboot manually, or configure the OS to start it for you.

### Linux (systemd)

Use the example systemd units and instructions in [systemd/README.md](./systemd/README.md). In short:

1. Copy the unit files from `docs/deployment/systemd/` and replace `REPO_ROOT`, `BACKEND_PORT`, and `FRONTEND_PORT` with your paths and ports.
2. Install the units under `~/.config/systemd/user/` (user) or `/etc/systemd/system/` (system).
3. Enable and start the backend, frontend, and RQ worker services.

The RQ queue worker is required for gateway lifecycle (wake/check-in) and webhook delivery; run it as a separate unit.

### macOS (launchd)

LaunchAgents run at **user login**, not at machine boot. Use LaunchAgents so the backend, frontend, and worker run under your user and restart on failure. For true boot-time startup you would need LaunchDaemons or other configuration (not covered here).

1. Create a plist for each process under `~/Library/LaunchAgents/`, e.g. `com.openclaw.mission-control.backend.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.openclaw.mission-control.backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>uv</string>
    <string>run</string>
    <string>uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>REPO_ROOT/backend</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:REPO_ROOT/backend/.venv/bin</string>
  </dict>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

Replace `REPO_ROOT` with the actual repo path. Ensure `uv` is on `PATH` (e.g. add `~/.local/bin` to the `PATH` in the plist). Load with:

```bash
launchctl load ~/Library/LaunchAgents/com.openclaw.mission-control.backend.plist
```

2. Add similar plists for the frontend (`npm run start -- --hostname 0.0.0.0 --port 3000` in `REPO_ROOT/frontend`) and for the RQ worker (`uv run python ../scripts/rq worker` with `WorkingDirectory=REPO_ROOT/backend` and `ProgramArguments` pointing at `uv`, `run`, `python`, `../scripts/rq`, `worker`).
