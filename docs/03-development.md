# Development workflow

## Migration integrity gate (CI)

CI enforces a migration integrity gate to prevent merge-time schema breakages.

### What it validates

- Alembic migrations can apply from a clean Postgres database (`upgrade head`)
- Alembic revision graph resolves to a head revision after migration apply
- On migration-relevant PRs, CI also checks that model changes are accompanied by migration updates

If any of these checks fails, CI fails and the PR is blocked.

### Local reproduction

From repo root:

```bash
make backend-migration-check
```

This command starts a temporary Postgres container, runs migration checks, and cleans up the container.
