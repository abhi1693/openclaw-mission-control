# Systemd unit files (local install, run at boot)

Example systemd units for running Mission Control at boot when installed **without Docker** (e.g. local install in a VM).

## Prerequisites

- **Backend**: `uv`, Python 3.12+, and `backend/.env` configured (including `DATABASE_URL`, `RQ_REDIS_URL` if using the queue worker).
- **Frontend**: Node.js 22+ and `frontend/.env` (e.g. `NEXT_PUBLIC_API_URL`).
- **RQ worker**: Redis must be running and reachable; `backend/.env` must set `RQ_REDIS_URL` and `RQ_QUEUE_NAME` to match the backend API.

If you use Docker only for Postgres and/or Redis, start those first (e.g. `docker compose up -d db` and optionally Redis) or add `After=docker.service` and start the stack via a separate unit or script.

## Placeholders

Before installing, replace in each unit file:

- `REPO_ROOT` — absolute path to the Mission Control repo (e.g. `/home/user/openclaw-mission-control`). Must not contain spaces (systemd unit values do not support shell-style quoting).
- `BACKEND_PORT` — backend port (default `8000`).
- `FRONTEND_PORT` — frontend port (default `3000`).

Example (from repo root):

```bash
REPO_ROOT="$(pwd)"
for f in docs/deployment/systemd/openclaw-mission-control-*.service; do
  sed -e "s|REPO_ROOT|$REPO_ROOT|g" -e "s|BACKEND_PORT|8000|g" -e "s|FRONTEND_PORT|3000|g" "$f" \
    > "$(basename "$f")"
done
# Then copy the generated .service files to ~/.config/systemd/user/ or /etc/systemd/system/
```

**User units** start at **user login** by default. To have services start at **machine boot** without logging in, enable lingering for your user: `loginctl enable-linger $USER`. Alternatively, use system-wide units in `/etc/systemd/system/` (see below).

## Install and enable

**User units** (recommended for single-user / VM):

```bash
cp openclaw-mission-control-backend.service openclaw-mission-control-frontend.service openclaw-mission-control-rq-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable openclaw-mission-control-backend openclaw-mission-control-frontend openclaw-mission-control-rq-worker
systemctl --user start openclaw-mission-control-backend openclaw-mission-control-frontend openclaw-mission-control-rq-worker
```

**System-wide** (e.g. under `/etc/systemd/system/`):

```bash
sudo cp openclaw-mission-control-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-mission-control-backend openclaw-mission-control-frontend openclaw-mission-control-rq-worker
```

## Order

Start order is not strict between backend, frontend, and worker; all use `After=network-online.target`. Ensure Postgres (and Redis, if used) are running before or with the backend/worker (e.g. start Docker services first, or use system units for Postgres/Redis with the Mission Control units depending on them).

## Logs

- `journalctl --user -u openclaw-mission-control-backend -f` (or `sudo journalctl -u openclaw-mission-control-backend -f` for system units)
- Same for `openclaw-mission-control-frontend` and `openclaw-mission-control-rq-worker`.
