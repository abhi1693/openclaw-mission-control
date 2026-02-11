# Backend DB layer & migrations

This page documents the backend database layer (SQLModel/SQLAlchemy) and Alembic migrations.

**Audience**
- Operators: how schema changes are applied safely.
- Maintainers: where to add models/schemas and how to generate migrations.

## TL;DR

- DB config is in `backend/app/core/config.py`.
- Engine/session/migrations startup logic is in `backend/app/db/session.py`.
- Alembic env + revision scripts are in `backend/migrations/*`.
- SQLModel models live in `backend/app/models/*`.
- Pydantic / API schemas live in `backend/app/schemas/*`.

## Database URL + engine/session setup

**Source of truth:** `DATABASE_URL` env var → `settings.database_url`.

- Settings: `backend/app/core/config.py`
- Engine + session maker: `backend/app/db/session.py`

The backend uses an **async SQLAlchemy engine**:
- `create_async_engine(..., pool_pre_ping=True)`
- `async_sessionmaker(..., expire_on_commit=False)`

### Database URL normalization

Both the runtime DB layer and Alembic normalize the URL:
- If you set `postgresql://...`, it is converted to `postgresql+psycopg://...`.

Why: SQLAlchemy needs the explicit driver scheme.

## `DB_AUTO_MIGRATE` behavior (and why it’s risky)

`DB_AUTO_MIGRATE` controls whether the backend attempts to apply Alembic migrations **automatically on startup**.

**Where implemented**
- Defaulting logic: `backend/app/core/config.py`
  - `db_auto_migrate` default is `False`.
  - In `ENVIRONMENT=dev`, if `DB_AUTO_MIGRATE` is not explicitly set, it defaults to `true`.
- Startup behavior: `backend/app/db/session.py:init_db()`

**Startup flow (simplified)**
1. If `settings.db_auto_migrate` is true:
   - If `backend/migrations/versions/` contains any `*.py` revisions:
     - run `alembic upgrade head` (in a thread via `asyncio.to_thread()`)
   - else:
     - log a warning and fall back to `SQLModel.metadata.create_all`
2. If `settings.db_auto_migrate` is false:
   - run `SQLModel.metadata.create_all`

### Operator guidance (safe defaults)

Auto-migrations are convenient in dev, but risky in production-like environments:
- Migrations can be destructive.
- Rollbacks are not always possible.
- Long-running backfills can cause downtime.

**Recommended production posture**
- Set `DB_AUTO_MIGRATE=false`.
- Apply migrations explicitly during deploy using a controlled step (see below).

## Alembic structure

- Alembic config: `backend/alembic.ini`
- Alembic environment: `backend/migrations/env.py`
- Revisions: `backend/migrations/versions/*.py`

### How Alembic finds models

`backend/migrations/env.py`:
- Adds `backend/` to `sys.path`.
- Imports `app.models` so `SQLModel.metadata` includes all tables.
- Uses `target_metadata = SQLModel.metadata`.

### Online vs offline mode

Alembic supports:
- **offline** migrations (generates SQL without connecting)
- **online** migrations (connects and runs against the DB)

This repo’s `env.py` configures:
- `compare_type=True` (type changes show up in autogenerate diffs)
- `pool.NullPool` for migration connections

## Downgrades (operator caution)

`alembic downgrade` is **not** guaranteed to be safe in production.

Why:
- Many migrations are not logically reversible (data drops/transforms/backfills).
- Even when a downgrade script exists, the *application* may not be compatible with the old schema.

Recommended rollback posture:
- Prefer **restore-from-backup** (or managed DB PITR) to a known-good point.
- Prefer **forward-fix** migrations over downgrades when feasible.
- Only use `alembic downgrade` in production if you have explicitly tested it for that migration chain and understand the data impact.

## How to apply migrations

From `backend/README.md`:

```bash
cd backend

# apply migrations
uv run alembic upgrade head
```

## First 30 minutes: migrations failed on startup (operator triage)

Symptoms:
- Backend crashloops on startup.
- Logs show Alembic errors / schema mismatch.

Checklist:
1) **Confirm config**
- `DATABASE_URL` points to the intended DB (host, dbname, credentials).
- Confirm whether `DB_AUTO_MIGRATE` is enabled (and whether it *should* be).

2) **Read the failing revision**
- Check backend logs for the revision id it was trying to apply.
- If running migrations manually:

```bash
cd backend
uv run alembic current
uv run alembic heads
```

3) **Inspect DB revision state (if needed)**
- Look at the `alembic_version` table in the DB to confirm the current revision.

4) **Stabilize**
- If this is production and you’re unsure: stop automated migration attempts, take a backup, and apply a controlled migration step (or restore to a known-good point).

## Safe migration workflow (maintainers)

### 1) Plan the change
- Prefer **additive** migrations (new tables/columns, nullable columns first).
- Avoid destructive changes without a clear data-migration + rollback plan.

### 2) Generate migration

```bash
cd backend
uv run alembic revision --autogenerate -m "<short message>"
```

### 3) Review the migration script
Autogenerate can be wrong.
- Confirm indexes/constraints.
- Confirm nullable/default semantics.
- Confirm destructive operations are intentional.

### 4) Apply locally + run tests

```bash
cd backend
uv run alembic upgrade head
uv run pytest
```

### 5) Production application strategy (do not guess)

Pick one:
- **Manual step during deploy**: run `alembic upgrade head` before starting new app version.
- **Job/one-off task** (k8s/etc): a single migration job.

Avoid relying on `DB_AUTO_MIGRATE=true` in production until you’ve proven:
- migrations are backward compatible,
- you have observability,
- you have a tested restore procedure.

## Models vs schemas (where to add things)

### SQLModel models (`backend/app/models/*`)

- Each file groups DB tables for a domain area.
- Models typically inherit from shared mixins (see `backend/app/models/base.py`).
- Import side effects matter: the app imports `app.models` at startup so metadata is registered.

**Add a new table/model**
1. Create/update a module under `backend/app/models/`.
2. Ensure it’s imported by `backend/app/models/__init__.py` (or otherwise imported when `app.models` is imported).
3. Generate an Alembic migration and review it.

### API/Pydantic schemas (`backend/app/schemas/*`)

Schemas define request/response shapes and validation for API endpoints.
- Keep them separate from DB models to avoid coupling persistence with public API.

**Add a new endpoint schema**
- Add to `backend/app/schemas/<domain>.py` and export from `backend/app/schemas/__init__.py` as needed.

## Where the DB session is injected

FastAPI dependency:
- `backend/app/api/deps.py` defines `SESSION_DEP = Depends(get_session)`
- `backend/app/db/session.py:get_session()` yields a request-scoped `AsyncSession`

The session dependency includes a safety net:
- if a request errors while a transaction is open, it attempts to rollback.

## References

- Backend config: `backend/app/core/config.py`
- DB engine/session/migrations: `backend/app/db/session.py`
- Alembic env: `backend/migrations/env.py`
- Alembic revisions: `backend/migrations/versions/*`
- Backend README (migration commands): `backend/README.md`
