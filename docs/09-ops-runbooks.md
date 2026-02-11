# Operations

This is the ops/SRE entrypoint.

It aims to answer, quickly:
- “Is the system up?”
- “What changed?”
- “What should I check next?”

Deep dives:
- [Deployment](deployment/README.md)
- [Production](production/README.md)
- [Troubleshooting deep dive](troubleshooting/README.md)

## First 30 minutes (incident checklist)

### 0) Stabilize communications

- Identify incident lead and comms channel.
- Capture last deploy SHA/tag and time window.
- Do not paste secrets into chat/tickets.

### 1) Confirm impact

- UI broken vs API broken vs auth vs DB vs gateway integration.
- All users or subset?

### 2) Health checks

- Backend:
  - `curl -f http://<backend-host>:8000/healthz`
  - `curl -f http://<backend-host>:8000/readyz`
- Frontend:
  - can the UI load?
  - in browser devtools, are `/api/v1/*` requests failing?

### 3) Configuration sanity

Common misconfigs that look like outages:

- `NEXT_PUBLIC_API_URL` wrong → UI loads but API calls fail.
- `CORS_ORIGINS` missing frontend origin → browser CORS errors.
- Clerk misconfig → auth redirects/401s.

### 4) Database

- If backend is 5xx’ing broadly, DB is a top suspect.
- Verify `DATABASE_URL` points at the correct host.

### 5) Logs

Compose:

```bash
docker compose -f compose.yml --env-file .env logs -f --tail=200
```

Targeted:

```bash
docker compose -f compose.yml --env-file .env logs -f --tail=200 backend
```

### 6) Rollback / isolate

- If there was a recent deploy and symptoms align, rollback to last known good.
- If gateway integration is implicated, isolate by disabling gateway-dependent flows.

## Common failure modes

- UI loads, Activity feed blank → `NEXT_PUBLIC_API_URL` wrong/unreachable.
- Repeated auth redirects/errors → Clerk keys/redirects misconfigured.
- Backend 5xx → DB outage/misconfig; migration failure.
- Backend won’t start → config validation failure (e.g. empty `CLERK_SECRET_KEY`).

## Backups

Evidence: `docs/production/README.md`.

- Minimum viable: periodic `pg_dump` to off-host storage.
- Treat restore as a drill (quarterly), not a one-time checklist.
