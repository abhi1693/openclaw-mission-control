# Production deployment (production-ish)

This document describes **production-ish** deployment patterns for **OpenClaw Mission Control**.

Mission Control is a web app (frontend) + API (backend) + Postgres. The simplest reliable
baseline is Docker Compose plus a reverse proxy with TLS.

> This repo currently ships a developer-friendly `compose.yml`. For real production, you should:
> - put Postgres on a managed service or dedicated host when possible
> - terminate TLS at a reverse proxy
> - set up backups + upgrades
> - restrict network exposure (firewall)

## Recommended baseline

If you’re looking for the **dev-friendly self-host** path (single machine, Docker Compose defaults), start with the repo root README:
- [Quick start (self-host with Docker Compose)](../../README.md#quick-start-self-host-with-docker-compose)


- Docker Engine + Docker Compose v2
- Reverse proxy: **Caddy** (simplest) or **nginx**
- TLS via Let’s Encrypt
- Persistent storage for Postgres
- Centralized logs (or at least log rotation)

## Single VPS (all-in-one)

### Architecture

On one VM:

- Caddy/nginx (ports 80/443) → routes traffic to:
  - frontend container (internal port 3000)
  - backend container (internal port 8000)
- Postgres container (internal 5432)

### Ports / firewall

Expose to the internet:

- `80/tcp` and `443/tcp` only

Do **not** expose:

- Postgres 5432
- backend 8000
- frontend 3000

All of those should be reachable only on the docker network / localhost.

### Environment & secrets

Recommended approach:

- Keep a host-level directory (e.g. `/opt/mission-control/`)
- Store runtime env in **non-committed** files:
  - `/opt/mission-control/.env` (compose-level vars)
  - optionally `/opt/mission-control/backend.env` and `/opt/mission-control/frontend.env`

Secrets guidelines:

- Choose auth mode explicitly:
  - `AUTH_MODE=local`: set `LOCAL_AUTH_TOKEN` to a random value with at least 50 characters
  - `AUTH_MODE=clerk`: configure Clerk keys
- Never commit `LOCAL_AUTH_TOKEN` or Clerk secret key.
- Prefer passing secrets as environment variables from the host (or use Docker secrets if you later
  migrate to Swarm/K8s).
- Rotate secrets if they ever hit logs.

### Compose in production

Clone the repo on the VPS, then:

```bash
cd /opt
sudo git clone https://github.com/abhi1693/openclaw-mission-control.git mission-control
cd mission-control

cp .env.example .env
# edit .env with real values (domains, auth mode + secrets, etc.)

docker compose -f compose.yml --env-file .env up -d --build
```

### Reverse proxy (Caddy example)

Example `Caddyfile` (adjust domain):

```caddyfile
mission-control.example.com {
  encode gzip

  # Frontend
  reverse_proxy /* localhost:3000

  # (Optional) If you want to route API separately, use a path prefix:
  # reverse_proxy /api/* localhost:8000
}
```

Notes:
- If the frontend calls the backend directly, ensure `NEXT_PUBLIC_API_URL` points to the **public, browser-reachable** API
  URL, not `localhost`.
  - Example: `NEXT_PUBLIC_API_URL=https://api.mission-control.example.com`
- If you route the backend under a path prefix, ensure backend routing supports it (or put it on a
  subdomain like `api.mission-control.example.com`).

### Keep services running (systemd)

Docker restart policies are often enough, but for predictable boot/shutdown and easy ops, use
systemd.

Create `/etc/systemd/system/mission-control.service`:

```ini
[Unit]
Description=Mission Control (docker compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/mission-control

ExecStart=/usr/bin/docker compose -f compose.yml --env-file .env up -d
ExecStop=/usr/bin/docker compose -f compose.yml --env-file .env down

TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mission-control
sudo systemctl status mission-control
```

### Backups

Minimum viable:

- Nightly `pg_dump` to off-host storage
- Or filesystem-level backup of the Postgres volume (requires consistent snapshots)

Example dump:

```bash
docker exec -t openclaw-mission-control-db-1 pg_dump -U postgres mission_control > /opt/backups/mission_control.sql
```

## Multi-VPS (split services)

The main reason to split is reliability and blast-radius reduction.

### Option A: 2 hosts

- Host 1: reverse proxy + frontend + backend
- Host 2: Postgres (or managed)

### Option B: 3 hosts

- Host 1: reverse proxy + frontend
- Host 2: backend
- Host 3: Postgres (or managed)

### Networking / security groups

Minimum rules:

- Public internet → reverse proxy host: `80/443`
- Reverse proxy host → backend host: `8000` (or whatever you publish internally)
- Backend host → DB host: `5432`

Everything else: deny.

### Configuration considerations

- `DATABASE_URL` must point to the DB host (not `localhost`).
- `CORS_ORIGINS` must include the public frontend URL.
- `NEXT_PUBLIC_API_URL` should be the public API base URL.

### Database migrations

The backend currently runs Alembic migrations on startup (see logs). In multi-host setups:

- Decide if migrations should run automatically (one backend instance) or via a manual deploy step.
- Avoid multiple concurrent backend deploys racing on migrations.

## Operational checklist

- [ ] TLS is enabled, HTTP redirects to HTTPS
- [ ] Only 80/443 exposed publicly
- [ ] Postgres not publicly accessible
- [ ] Backups tested (restore drill)
- [ ] Log retention/rotation configured
- [ ] Regular upgrade process (pull latest, rebuild, restart)

## Troubleshooting (production)

- `docker compose ps` and `docker compose logs --tail=200` are your first stops.
- If the UI loads but API calls fail, check:
  - `NEXT_PUBLIC_API_URL`
  - backend CORS settings (`CORS_ORIGINS`)
  - firewall rules between proxy ↔ backend
