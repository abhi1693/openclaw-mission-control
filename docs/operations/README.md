# Operations

Runbooks and operational notes for running Mission Control.

## Health checks

Backend exposes:

- `/healthz` — liveness
- `/readyz` — readiness

Example:

```bash
curl -f http://localhost:8000/healthz
curl -f http://localhost:8000/readyz
```

## Logs

### Docker Compose

```bash
# tail everything
docker compose -f compose.yml --env-file .env logs -f --tail=200

# tail just backend
docker compose -f compose.yml --env-file .env logs -f --tail=200 backend
```

The backend supports slow-request logging via `REQUEST_LOG_SLOW_MS`.

## Backups

The DB runs in Postgres (Compose `db` service) and persists to the `postgres_data` named volume.

### Minimal backup (logical)

Example with `pg_dump` (run on the host):

```bash
# load variables from .env (trusted file only)
set -a
. ./.env
set +a

: "${POSTGRES_DB:?set POSTGRES_DB in .env}"
: "${POSTGRES_USER:?set POSTGRES_USER in .env}"
: "${POSTGRES_PORT:?set POSTGRES_PORT in .env}"
: "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env (strong, unique value; not \"postgres\")}"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
  -h 127.0.0.1 -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom > mission_control.backup
```

> **Note**
> For real production, prefer automated backups + retention + periodic restore drills.

## Upgrades / rollbacks

### Upgrade (Compose)

```bash
docker compose -f compose.yml --env-file .env up -d --build
```

### Rollback

Rollback typically means deploying a previous image/commit.

> **Warning**
> If you applied non-backward-compatible DB migrations, rolling back the app may require restoring the database.

## Rate limiting

The backend applies per-IP rate limits on sensitive endpoints:

| Endpoint | Limit | Window |
| --- | --- | --- |
| Agent authentication | 20 requests | 60 seconds |
| Webhook ingest | 60 requests | 60 seconds |

Rate-limited requests receive HTTP `429 Too Many Requests`.

Set `RATE_LIMIT_BACKEND` to choose the storage backend:

| Backend | Value | Operational notes |
| --- | --- | --- |
| In-memory (default) | `memory` | Per-process limits; each worker tracks independently. No external dependencies. |
| Redis | `redis` | Limits are shared across all workers. Set `RATE_LIMIT_REDIS_URL` or it falls back to `RQ_REDIS_URL`. Connectivity is validated at startup; transient Redis failures fail open (requests allowed, warning logged). |

When using the in-memory backend in multi-process deployments, also apply rate limiting at the reverse proxy layer (nginx `limit_req`, Caddy rate limiting, etc.).

## Common issues

### Frontend loads but API calls fail

- Confirm `NEXT_PUBLIC_API_URL` is set and reachable from the browser.
- Confirm backend CORS includes the frontend origin (`CORS_ORIGINS`).

### Auth mismatch

- Backend: `AUTH_MODE` (`local` or `clerk`)
- Frontend: `NEXT_PUBLIC_AUTH_MODE` should match

### Webhook signature errors (403)

If a webhook has a `secret` configured, inbound payloads must include a valid HMAC-SHA256 signature in one of these headers:

- `X-Hub-Signature-256: sha256=<hex-digest>` (GitHub-style)
- `X-Webhook-Signature: sha256=<hex-digest>`

Missing or invalid signatures return `403 Forbidden`. If you see unexpected 403s on webhook ingest, verify that the sending service is computing the HMAC correctly using the webhook's secret.

### Webhook payload too large (413)

Webhook ingest enforces a **1 MB** payload size limit. Payloads exceeding this return `413 Content Too Large`. If you need to send larger payloads, consider sending a URL reference instead of inline content.
