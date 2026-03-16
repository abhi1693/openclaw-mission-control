# Policy: one DB migration per PR

## Rule
If a pull request adds migration files under:

- `backend/migrations/versions/*.py`

…then it must add **no more than one** migration file.

## Why
- Makes review and rollback simpler.
- Reduces surprise Alembic multiple-head situations.
- Keeps CI/installer failures easier to debug.

## Common exceptions / guidance
- If you have multiple Alembic heads, prefer creating **one** merge migration.
- If changes are unrelated, split into multiple PRs.

## CI enforcement
CI runs `scripts/ci/one_migration_per_pr.sh` on PRs and fails if >1 migration file is added.

## Notes
This policy does not replace the existing migration integrity gate (`make backend-migration-check`). It is a lightweight guardrail to prevent multi-migration PRs.
