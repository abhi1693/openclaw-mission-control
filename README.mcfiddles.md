# Mission Control Integration for mcfiddles.ai

This document describes how to deploy OpenClaw Mission Control alongside the existing OpenClaw platform at mcfiddles.ai.

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │                mcfiddles.ai                   │
                    │         (OpenClaw Platform - VM/Cloud Run)    │
                    │                                               │
    Browser ───────►│  /gui/*      → Control Deck (built-in)       │
                    │  /control/*  → Mission Control (proxied)      │
                    │  /api/*      → Platform API                   │
                    │                                               │
                    │  Auth Middleware validates all /control/* ─┐  │
                    └──────────────────────────────────────────┼──┘
                                                                │
                    ┌──────────────────────────────────────────┼──┐
                    │              VM (35.193.148.179)          │  │
                    │                                           ▼  │
                    │  ┌─────────────────┐   ┌─────────────────────┐
                    │  │   PostgreSQL    │   │   Mission Control   │
                    │  │  (OpenClaw DB)  │   │   (Docker Compose)  │
                    │  │                 │   │                     │
                    │  │  Port: 5432     │   │  Backend: 8100      │
                    │  │                 │   │  Frontend: 3100     │
                    │  │                 │   │  Postgres: 5433     │
                    │  └─────────────────┘   │  Redis: 6380        │
                    │                        └─────────────────────┘
                    └───────────────────────────────────────────────┘
```

## Authentication Flow

1. User navigates to `https://mcfiddles.ai/control/`
2. Platform auth middleware checks for valid session
3. If not authenticated → redirects to `/login?next=/control/`
4. User logs in (with TOTP if enabled)
5. Platform proxies authenticated requests to Mission Control
6. Mission Control backend receives requests with `Authorization: Bearer <internal-token>`
7. User identity forwarded via `X-OpenClaw-*` headers

## Deployment Steps

### 1. Configure Mission Control Environment

Copy and edit the environment file:

```bash
cd /Users/justinkline/Sites/openclaw_skills/mission-control
cp .env.mcfiddles .env.mcfiddles.local

# Edit with secure values
vim .env.mcfiddles.local
```

Required changes:
- `POSTGRES_PASSWORD`: Generate secure password
- `LOCAL_AUTH_TOKEN`: Generate 64+ character token

```bash
# Generate secure password
openssl rand -base64 32

# Generate auth token (must be 50+ chars)
openssl rand -base64 64 | tr -d '\n' | head -c 64
```

### 2. Deploy to VM

SSH to the VM and set up Mission Control:

```bash
# SSH to VM
gcloud compute ssh openclaw-vm --zone=us-central1-a --project=hellojustinkline

# Create directory
sudo mkdir -p /opt/mission-control
sudo chown $USER:$USER /opt/mission-control
cd /opt/mission-control
```

Copy files from your local machine:

```bash
# From local machine
scp -r backend frontend compose.mcfiddles.yml .env.mcfiddles.local \
    justinkline@35.193.148.179:/opt/mission-control/
```

Start Mission Control on the VM:

```bash
# On VM
cd /opt/mission-control
mv .env.mcfiddles.local .env
docker compose -f compose.mcfiddles.yml up -d --build
```

Verify deployment:

```bash
# Check containers
docker compose -f compose.mcfiddles.yml ps

# Check backend health
curl http://localhost:8100/healthz

# Check frontend
curl -I http://localhost:3100
```

### 3. Configure Platform Connection

Add Mission Control settings to the platform's environment.

For VM-based platform (`/etc/openclaw/.env`):

```bash
# Add to /etc/openclaw/.env
OPENCLAW_MISSION_CONTROL_URL=http://localhost:8100
OPENCLAW_MISSION_CONTROL_FRONTEND_URL=http://localhost:3100
OPENCLAW_MISSION_CONTROL_AUTH_TOKEN=<same-token-from-mission-control-env>
```

For Cloud Run deployment (add to deployment profile):

```bash
# Add to infra/gcp/profiles/justinkline.env
MISSION_CONTROL_URL=http://35.193.148.179:8100
MISSION_CONTROL_FRONTEND_URL=http://35.193.148.179:3100
MISSION_CONTROL_SECRET=mission-control-auth-token  # Secret Manager reference
```

### 4. Create Secret in GCP (if using Cloud Run)

```bash
# Create secret for Mission Control token
gcloud secrets create mission-control-auth-token \
    --project=justinkline-openclaw \
    --replication-policy=automatic

# Add secret value
echo -n "<your-64-char-token>" | gcloud secrets versions add mission-control-auth-token \
    --project=justinkline-openclaw \
    --data-file=-

# Grant access to Cloud Run service account
gcloud secrets add-iam-policy-binding mission-control-auth-token \
    --project=justinkline-openclaw \
    --member="serviceAccount:openclaw-platform@justinkline-openclaw.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### 5. Restart Platform

Restart the platform to pick up Mission Control settings:

For VM:
```bash
sudo systemctl restart openclaw
```

For Cloud Run:
```bash
cd infra/gcp
./deploy_platform.sh justinkline
```

### 6. Verify Integration

1. Navigate to `https://mcfiddles.ai/control/`
2. Should redirect to login if not authenticated
3. After login, should see Mission Control dashboard
4. Check proxy status: `https://mcfiddles.ai/control/status`

## Environment Variables Reference

### Mission Control (.env)

| Variable | Description | Example |
|----------|-------------|---------|
| `FRONTEND_PORT` | Frontend container port | `3100` |
| `BACKEND_PORT` | Backend container port | `8100` |
| `POSTGRES_DB` | Mission Control database name | `mission_control` |
| `POSTGRES_USER` | Database username | `mission_control` |
| `POSTGRES_PASSWORD` | Database password | (secure random) |
| `AUTH_MODE` | Authentication mode | `local` |
| `LOCAL_AUTH_TOKEN` | Shared auth token (50+ chars) | (secure random) |
| `CORS_ORIGINS` | Allowed origins | `https://mcfiddles.ai` |
| `NEXT_PUBLIC_API_URL` | Frontend API URL | `https://mcfiddles.ai/control/api` |

### Platform (OPENCLAW_* prefix)

| Variable | Description | Example |
|----------|-------------|---------|
| `MISSION_CONTROL_URL` | Backend URL | `http://localhost:8100` |
| `MISSION_CONTROL_FRONTEND_URL` | Frontend URL | `http://localhost:3100` |
| `MISSION_CONTROL_AUTH_TOKEN` | Shared auth token | (same as Mission Control) |

## Troubleshooting

### Mission Control not reachable

```bash
# Check if containers are running
docker compose -f compose.mcfiddles.yml ps

# Check container logs
docker compose -f compose.mcfiddles.yml logs backend
docker compose -f compose.mcfiddles.yml logs frontend

# Test connectivity
curl http://localhost:8100/healthz
curl -I http://localhost:3100
```

### Authentication errors

1. Verify `LOCAL_AUTH_TOKEN` matches between Mission Control and platform
2. Check platform logs for auth errors
3. Verify proxy is forwarding Authorization header

### CORS errors

1. Check `CORS_ORIGINS` in Mission Control env
2. Verify requests go through platform proxy (not direct)

### Database connection errors

```bash
# Check PostgreSQL container
docker compose -f compose.mcfiddles.yml logs db

# Verify database exists
docker compose -f compose.mcfiddles.yml exec db psql -U mission_control -d mission_control -c '\dt'
```

## Updating Mission Control

```bash
# On VM
cd /opt/mission-control

# Pull latest changes (if using git)
git pull

# Rebuild and restart
docker compose -f compose.mcfiddles.yml up -d --build
```

## Security Considerations

1. **Internal only**: Mission Control ports (8100, 3100) should only be accessible from localhost
2. **Auth token**: Use a strong, random token (64+ characters)
3. **Database password**: Use a unique, strong password
4. **HTTPS**: All external traffic goes through HTTPS via platform proxy
5. **Session security**: Platform validates TOTP and session before proxying
