# Release checklist

This is a lightweight, operator-friendly checklist for releasing Mission Control.

> Goal: **no data loss** and **near-zero (ideally zero) user-visible downtime**.

## Before you release

- [ ] Confirm the target version/commit SHA.
- [ ] Review merged PRs since last release (especially DB schema/auth changes).
- [ ] Ensure CI is green on the target SHA.
- [ ] Confirm you have:
  - [ ] access to the host(s)
  - [ ] access to Postgres backups (or snapshots)
  - [ ] a rollback plan

## Database safety

- [ ] Verify migrations are **backward compatible** with the current running app (if doing rolling deploys).
- [ ] Take a backup / snapshot.
- [ ] If migrations are risky or not backward compatible, schedule a maintenance window.

## Deploy (Docker Compose)

- [ ] Pull / build the new images (or update the repo checkout).
- [ ] Apply migrations (if you run them manually):

```bash
# example: if running backend locally on the host
cd backend
uv run alembic upgrade head
```

- [ ] Restart services with minimal disruption:

```bash
docker compose -f compose.yml --env-file .env up -d --build
```

## Post-deploy verification

- [ ] Backend health: `GET /healthz` returns 200
- [ ] Backend readiness: `GET /readyz` returns 200
- [ ] Frontend loads (no console spam)
- [ ] Login works (local/clerk mode)
- [ ] Core flows work end-to-end:
  - [ ] View board
  - [ ] Create/update a task
  - [ ] Post a comment
  - [ ] Heartbeat check-in succeeds

## Rollback (if needed)

- [ ] Roll back the app version (compose / images).
- [ ] If migrations were applied and are not reversible, rollbacks may require a DB restore.

## Notes to keep this honest

- If you add a new operational dependency (e.g., redis), update:
  - `README.md` (overview + quickstart)
  - `docs/deployment/README.md`
  - this checklist
