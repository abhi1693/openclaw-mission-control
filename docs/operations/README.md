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
# uses values from .env
export POSTGRES_DB=mission_control
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres
export POSTGRES_PORT=5432

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

## Common issues

### Frontend loads but API calls fail

- Confirm `NEXT_PUBLIC_API_URL` is set and reachable from the browser.
- Confirm backend CORS includes the frontend origin (`CORS_ORIGINS`).

### Auth mismatch

- Backend: `AUTH_MODE` (`local` or `clerk`)
- Frontend: `NEXT_PUBLIC_AUTH_MODE` should match
