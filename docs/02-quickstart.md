# Quickstart (self-host with Docker Compose)

This page is a pointer to the canonical quickstart in the repo root README.

- Canonical quickstart: [`README.md#quick-start-self-host-with-docker-compose`](../README.md#quick-start-self-host-with-docker-compose)

## Verify it works
After `docker compose up`:
- Backend health: `http://localhost:8000/healthz` returns `{ "ok": true }`
- Frontend: `http://localhost:3000`

## Common gotchas
- `NEXT_PUBLIC_API_URL` must be reachable from your browser (host), not just from inside Docker.
- Clerk auth is required; ensure Clerk keys are configured (see [Deployment guide](deployment/README.md)).
