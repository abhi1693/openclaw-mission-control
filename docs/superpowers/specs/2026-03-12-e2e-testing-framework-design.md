# E2E Testing Framework Design — OCMC Dashboard

**Date:** 2026-03-12
**Status:** Approved
**Scope:** Two-tier E2E testing architecture with shared infrastructure, Docker-based integration environment, and parallel CI pipeline

---

## Context

The OCMC dashboard has an existing E2E setup: Cypress 14 with 9 test files, a few custom commands (`loginWithLocalAuth`, `waitForAppLoaded`), and a shared `setupCommonPageTestHooks()` helper. All tests stub every API call via `cy.intercept()` — the backend never runs during E2E.

This works for fast UI feedback, but the setup has gaps:

- Test data is hardcoded inline across all 9 files (no shared fixtures or factories)
- SSE stream stubs and auth setup are copy-pasted
- No ability to test against a real backend — frontend/backend contract drift is invisible
- No Docker-based E2E environment exists
- CI runs a single E2E job with no tier separation

This design addresses those gaps without replacing the existing tooling.

## Design Principles

1. **Seed the world around the test, but not the behavior under test** — prerequisite data is seeded for speed; the flow being validated goes through the real UI/API path
2. **Known inputs / UI behavior → stubbed tier; system seams / layer agreement → integration tier** — clean ownership boundary between the two tiers
3. **Deliberately small** — shared factories for ~5 core entities, 4 integration specs, no test DSL or generic framework
4. **Fix the architecture first, then judge the tools** — Cypress stays; tool evaluation happens only if flakiness persists after infrastructure improvements

---

## 1. Shared Fixture & Factory Layer

**Location:** `frontend/cypress/support/factories/`

```
factories/
├── user.ts        — buildUser(), buildCreateUserInput()
├── org.ts         — buildOrg(), buildOrgMember()
├── board.ts       — buildBoard(), buildCreateBoardInput(), buildBoardSnapshot()
├── task.ts        — buildTask(), buildCreateTaskInput(), buildTaskComment()
├── approval.ts    — buildApproval()
└── index.ts       — re-exports all builders
```

### Factory pattern

Plain functions with sensible defaults and spread overrides:

```ts
let counter = 0;

export function buildBoard(overrides?: Partial<Board>): Board {
  const id = `board-${++counter}`;
  return {
    id,
    name: `Test Board ${id}`,
    slug: `test-board-${id}`,
    type: "kanban",
    organization_id: "org-default",
    goal_confirmed: true,
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}
```

### Rules

- **Deterministic default timestamps** — use fixed values like `"2026-01-01T00:00:00.000Z"`, override only when time matters to the test
- **Separate request builders from entity builders** — `buildBoard()` returns a persisted entity shape (with `id`, `created_at`); `buildCreateBoardInput()` returns only fields valid for a create request
- **Domain-realistic defaults** — a board belongs to a default org, a task is attached to a board, an org member is tied to the same org/user defaults. Tests compose objects without manually repairing relationships.
- **Explicit factory reset** — expose `resetFactoryState()` and call it in test setup rather than relying on implicit per-spec-file resets
- **Shared by both tiers** — stubbed tests use factories for `cy.intercept()` response bodies; integration tests use them for request payloads and assertion shapes

### Light scenario helpers

Thin compositions of factories for multi-entity setups used by 3+ tests:

```ts
// cypress/support/scenarios/boardWithTasks.ts
export function buildBoardWithTasks(options?) {
  const board = buildBoard(options?.board);
  const tasks = (options?.tasks ?? [{}]).map(t =>
    buildTask({ board_id: board.id, ...t })
  );
  return { board, tasks };
}
```

Scenario helpers compose factories and intercept helpers. They do not introduce new endpoint logic.

---

## 2. Stubbed-Layer Cleanup

Refactor the existing 9 Cypress tests to use the shared factory layer. **Scope: test setup only — test assertions, DOM selectors, and interaction flows are unchanged.** Note: not all 9 tests have inline mock data (e.g., `activity_smoke.cy.ts` has no intercepts) — the refactor applies only to tests with duplicated setup to replace.

### 2a. Replace inline mock data with factory calls

```ts
// Before (duplicated across files)
cy.intercept("GET", `${apiBase}/boards*`, {
  statusCode: 200,
  body: { items: [{ id: "b1", name: "Demo Board", slug: "demo", type: "kanban", ... }] },
});

// After
cy.intercept("GET", `${apiBase}/boards*`, {
  statusCode: 200,
  body: { items: [buildBoard({ name: "Demo Board", slug: "demo" })] },
});
```

Tests still explicitly override fields that are semantically important to their assertions, even if factory defaults happen to match.

### 2b. Extract composable intercept helpers

**Location:** `cypress/support/intercepts/`

```
intercepts/
├── auth.ts         — stubAuth(apiBase, overrides?)
├── boards.ts       — stubBoards(apiBase, options?)
├── sse.ts          — stubEmptySSEStreams(apiBase)
├── dashboard.ts    — stubDashboard(apiBase)
└── index.ts        — re-exports
```

Each helper stubs a clearly named slice of endpoints. Helpers accept structured option objects (not positional arrays) for forward compatibility:

```ts
stubBoards(apiBase, { boards: [buildBoard()], groups: [buildBoardGroup()] });
```

**Responsibility split:**
- **Factories** create data objects
- **Intercept helpers** stub endpoint families using factory-built data
- **Scenario helpers** compose the first two — no new endpoint logic

The existing `setupCommonPageTestHooks()` stays as a convenience wrapper that calls `stubAuth()` internally.

### 2c. Fail on unhandled API requests

Add a global rule in the stubbed tier that fails tests if an unexpected real network call escapes interception. This prevents silent leakage from "stubbed" into "sort of real."

---

## 3. Integration E2E Tier — Docker Environment

### 3a. Compose profile additions

Added to the existing `compose.yml` under `profiles: ["e2e"]`:

**Test database** — separate PostgreSQL instance, RAM-backed:

```yaml
db-test:
  profiles: ["e2e"]
  image: postgres:16-alpine
  environment:
    POSTGRES_DB: ocmc_test
    POSTGRES_USER: ocmc
    POSTGRES_PASSWORD: test
  ports:
    - "5433:5432"
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ocmc -d ocmc_test"]
  tmpfs:
    - /var/lib/postgresql/data
```

**Backend in test mode** — standalone stanza (no `extends`), meaningful healthcheck:

```yaml
backend-e2e:
  profiles: ["e2e"]
  build:
    context: .
    dockerfile: backend/Dockerfile
  depends_on:
    db-test:
      condition: service_healthy
    redis:
      condition: service_healthy
  environment:
    DATABASE_URL: "postgresql+psycopg://ocmc:test@db-test:5432/ocmc_test"
    AUTH_MODE: "local"
    LOCAL_AUTH_TOKEN: "e2e-local-auth-token-0123456789-0123456789-0123456789x"
    DB_AUTO_MIGRATE: "true"
    CORS_ORIGINS: "http://localhost:3000"
    RQ_REDIS_URL: "redis://redis:6379/0"
  ports:
    - "8001:8000"
  healthcheck:
    test: ["CMD-SHELL", "curl -sf http://localhost:8000/readyz || exit 1"]
    interval: 5s
    timeout: 10s
    retries: 12
```

The healthcheck uses `/readyz`. **Implementation prerequisite:** `/readyz` must be enhanced to verify DB connection and migration completion — the current implementation returns `ok: true` unconditionally. Until this is fixed, the healthcheck only confirms the process is listening.

**Seed runner** — one-shot service:

```yaml
e2e-seed:
  profiles: ["e2e"]
  build:
    context: .
    dockerfile: backend/Dockerfile
  depends_on:
    db-test:
      condition: service_healthy
  environment:
    DATABASE_URL: "postgresql+psycopg://ocmc:test@db-test:5432/ocmc_test"
  command: ["python", "-m", "scripts.e2e_seed"]
  restart: "no"
```

### 3b. Seed script

**Location:** `backend/scripts/e2e_seed.py`

A management command that writes prerequisite state directly via app models (not through product API endpoints). The seed runner assumes migrations have already been applied by `backend-e2e` — this is enforced by the Makefile orchestration (`e2e-up` waits for `backend-e2e` healthy before `e2e-seed` runs) and by the `depends_on: db-test` in the compose definition.

Seeds only:

1. Test user (known ID, email, name)
2. Test organization (known ID, name)
3. Organization membership (user → org, owner role)

Individual tests create their own boards/tasks/approvals through the UI or API as part of the test flow.

The seed path should be stable and boring — it must not break because an unrelated user-facing API changed.

### 3c. Frontend configuration

The frontend dev server must be started with `NEXT_PUBLIC_API_URL=http://localhost:8001` so it talks to `backend-e2e`, not the normal backend.

### 3d. Integration Cypress config

**Location:** `frontend/cypress.integration.config.ts`

```ts
export default defineConfig({
  e2e: {
    baseUrl: "http://localhost:3000",
    specPattern: "cypress/e2e-integration/**/*.cy.ts",
    supportFile: "cypress/support/e2e.ts",
    defaultCommandTimeout: 30_000,
    retries: { runMode: 2, openMode: 0 },
    env: {
      API_BASE: "http://localhost:8001",
      AUTH_TOKEN: "e2e-local-auth-token-0123456789-0123456789-0123456789x",
    },
  },
});
```

Shares the same support file as the stubbed tier (same factories, same auth commands). The longer `defaultCommandTimeout` (30s vs 20s) reflects the overhead of real API calls versus stubs.

**Auth token handling:** The stubbed tier uses a default token (`cypress-local-auth-token-...`) hardcoded in `loginWithLocalAuth()`. The integration tier uses a different token (`e2e-local-auth-token-...`) matching the `backend-e2e` environment. To avoid mismatches, update `loginWithLocalAuth()` to read from `Cypress.env('AUTH_TOKEN')` with a fallback to the current default. This way both tiers use the correct token without explicit per-call arguments.

**Clerk setup:** The shared support file (`e2e.ts`) currently imports `@clerk/testing/cypress` and calls `addClerkCommands()`. Since both tiers use `AUTH_MODE=local`, verify that Clerk's command registration is inert when Clerk publishable keys are absent. If it has side effects (API calls, timeouts), gate the import behind an `AUTH_MODE` check.

### 3e. Orchestration

**Makefile targets:**

```makefile
e2e-up:
	docker compose --profile e2e up -d --wait db-test backend-e2e redis

e2e-seed:
	docker compose --profile e2e run --rm e2e-seed

e2e-down:
	docker compose --profile e2e down -v

e2e-integration:
	cd frontend && npx cypress run --config-file cypress.integration.config.ts --browser chrome

e2e-full:
	$(MAKE) e2e-up
	$(MAKE) e2e-seed || ($(MAKE) e2e-down && exit 1)
	$(MAKE) e2e-integration || ($(MAKE) e2e-down && exit 1)
	$(MAKE) e2e-down
```

Lifecycle is deterministic: `up --wait` → `run --rm seed` → Cypress → `down -v`. Each run starts with a blank tmpfs database.

---

## 4. Integration Test Structure & Critical Flows

### 4a. Directory structure

```
cypress/
├── e2e/                        # Stubbed tests (existing, refactored)
├── e2e-integration/            # Integration tests (new)
│   ├── board-lifecycle.cy.ts
│   ├── task-lifecycle.cy.ts
│   ├── approval-flow.cy.ts     # Conditional — may defer (see below)
│   └── auth-protected-access.cy.ts
├── support/
│   ├── commands.ts             # Shared commands (both tiers)
│   ├── e2e.ts                  # Shared setup (both tiers)
│   ├── testHooks.ts            # Stubbed-tier helpers (refactored)
│   ├── factories/              # Shared factories (both tiers)
│   ├── intercepts/             # Stubbed-tier intercept helpers
│   ├── scenarios/              # Thin multi-entity composers
│   └── integration/            # Integration-tier helpers
│       ├── api.ts              # Real API client (setup + verification)
│       └── assertions.ts       # Minimal repeated shape checks
```

### 4b. Integration API helper

**Location:** `cypress/support/integration/api.ts`

A thin wrapper around `cy.request()` for prerequisite setup and persistence verification:

```ts
export const api = {
  // Setup helpers — create prerequisites
  createBoard(input: CreateBoardInput) { ... },
  createTask(boardId: string, input: CreateTaskInput) { ... },

  // Verification helpers — confirm persisted state
  getBoards() { ... },
  getTask(taskId: string) { ... },
};
```

Used **only for setup and verification** — the behavior under test always goes through the UI. Input types come from the factory layer (`buildCreateBoardInput()`, etc.).

`assertions.ts` stays minimal — only for repeated shape checks that are genuinely annoying to inline. Not a generic schema validation layer.

### 4c. Critical flows

**1. `board-lifecycle.cy.ts`** — Create board through UI, verify persistence

- Seed state: user + org (from e2e-seed)
- Test: navigate to /boards → create board via UI → verify it appears in list
- Verify: `api.getBoards()` confirms board exists in database
- Entity names include run-scoped suffix for debuggability

**2. `task-lifecycle.cy.ts`** — Create and update task on a board

- Seed state: user + org (from e2e-seed)
- Setup: `api.createBoard()` in `before()` — board is a prerequisite, not the behavior under test
- Test: navigate to board → create task via UI → edit status → verify update
- Verify: API confirms persisted state matches

**3. `approval-flow.cy.ts`** — Submit and approve a request *(conditional for v1)*

- Seed state: user + org (from e2e-seed)
- Setup: `api.createBoard()` + `api.createTask()` in `before()`
- Test: navigate to approvals → approve pending item → verify resolution
- **Note:** This spec is conditional. If creating a realistic pending approval requires unnatural backend setup (approvals may be system-generated), defer or narrow this test in v1. Include it in the target set but do not force it.

**4. `auth-protected-access.cy.ts`** — Verify auth gate end-to-end

- Test: visit /boards without token → verify redirect to sign-in; inject token → verify content loads with real API data
- This validates auth/session wiring — one of the primary reasons the integration tier exists

### 4d. Test isolation

- Tests assert on **specific entity identity** (board named X, task Y with status Z), not global counts or list lengths
- No per-test DB cleanup — the tmpfs database is destroyed on `e2e-down`
- Integration-created entities get **unique names per run** (e.g., spec-scoped prefix) for debugging
- `cy.intercept()` is **forbidden** in `e2e-integration/` except for truly external dependencies not under our control
- If cross-test interference becomes a problem, add per-test DB truncation via a backend endpoint — defer until needed

---

## 5. CI Pipeline

### 5a. Job structure

```
ci.yml:

  check (existing)           ← format, lint, typecheck, unit tests, build
       │
       ├── e2e-stubbed       ← Cypress stubbed (no Docker)     [budget: 1–3 min]
       │
       └── e2e-integration   ← Docker stack + Cypress           [budget: 3–6 min]
```

Both E2E jobs depend on `check` and run in parallel with each other.

### 5b. Stubbed job

- Node 22, `npm ci`, Next.js build cache
- Start frontend dev server with `NEXT_PUBLIC_AUTH_MODE=local`
- `NEXT_PUBLIC_API_URL` set to a value the frontend requires, but tests should never hit it (all requests intercepted)
- Run `npx cypress run --browser chrome`
- On failure: upload Cypress screenshots/videos + frontend server logs
- Timeout: 10 minutes (budget: 1–3 min actual)

### 5c. Integration job

```
Steps (sequential, deterministic):
1. Checkout + setup Node 22
2. Docker Compose --profile e2e up -d --wait (db-test, backend-e2e, redis)
3. docker compose --profile e2e run --rm e2e-seed
4. npm ci (frontend)
5. Start frontend dev server (NEXT_PUBLIC_API_URL=http://localhost:8001)
6. Wait for frontend ready
7. Run Cypress with cypress.integration.config.ts
8. On failure: dump compose logs (backend-e2e, db-test, redis) + upload Cypress artifacts + frontend logs
9. Always: docker compose --profile e2e down -v
```

- Docker layer caching via standard GitHub Actions Docker cache integration
- Timeout: 15 minutes (budget: 3–6 min actual)

### 5d. Runtime budgets

These are enforced, not aspirational:
- If stubbed consistently exceeds **3 minutes**, review test count and setup cost
- If integration consistently exceeds **6 minutes**, review scope or Docker build time
- Total wall-clock for both tiers: target **under 6 minutes**, hard ceiling **10 minutes**

---

## 6. Coverage Strategy

### 6a. Tier ownership

| Scenario | Tier | Rationale |
|----------|------|-----------|
| UI renders correctly given data | Stubbed | Fast, factories control shapes |
| Form interaction / dialog flow | Stubbed | No backend needed |
| Responsive / viewport behavior | Stubbed | Pure frontend |
| Error state rendering (4xx/5xx) | Stubbed | Intercept controls response |
| Empty state rendering | Stubbed | Intercept returns empty list |
| Data persists after user action | Integration | Needs real DB |
| Auth gate blocks/allows | Integration | Needs real auth middleware |
| Frontend/backend contract holds | Integration | Real API response shapes |
| Multi-step workflow completes | Integration | State transitions across requests |
| SSE: UI reaction to event | Stubbed | Intercept delivers synthetic event |
| SSE: delivery pipeline works | Integration (later) | Needs real event emission |

### 6b. Stubbed expansion priorities

After refactoring the existing 9 tests, add coverage in order of criticality, bug history, and interaction complexity:

1. Gateway management (list, detail, edit)
2. Board groups (list, create, assign)
3. Custom fields (create definition, assign to task)
4. Tags (create, assign, bulk edit)
5. Settings / user preferences
6. Dashboard / metrics charts
7. Onboarding wizard

Each new spec covers the **primary happy path** plus the **most important alternate state(s)** for that page (error, empty, loading, or permission — whichever is most relevant).

### 6c. Integration expansion criteria

The integration tier stays small. Add a new integration test only when:

1. A production bug was caused by frontend/backend contract drift → regression test
2. A new critical flow ships (e.g., gateway provisioning) → happy-path seam test
3. A flow depends on cross-service or background behavior that unit/backend tests don't cover
4. An existing flow's backend behavior changes significantly → verify the seam

**Cap:** 4–8 specs total. Review at ~10 — some may need demotion to stubbed or backend API tests.

### 6d. When to add or remove tests

**Add:**
- New page/route → stubbed spec (render + primary interaction)
- Complex interaction added → stubbed coverage
- UI bug fixed → stubbed regression test
- New critical workflow → consider integration coverage
- Contract broke in production → mandatory integration regression test

**Remove:**
- Route or interaction deleted/redesigned → remove or rewrite tests promptly
- Stale tests that no longer reflect app behavior → delete rather than carry forward

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Keep Cypress | Yes | Already in place, evaluate tool swap only if flakiness persists after infra fixes |
| Two tiers | Stubbed + Integration | Different signals, different infrastructure needs, different runtime profiles |
| Shared factories | Yes | Single source of truth for entity shapes across both tiers |
| Docker profile | `--profile e2e` on existing compose.yml | Reuses existing stack, reduces config drift |
| Test DB | tmpfs PostgreSQL | Fast, ephemeral, no cleanup needed |
| Seed approach | Management command via models | Stable, doesn't depend on product API surface |
| Data strategy | Hybrid — seed world, test behavior | Speed for prerequisites, real validation for flows under test |
| CI structure | Parallel jobs | Fast feedback (stubbed) + real validation (integration), clean failure isolation |
| Integration cap | 4–8 specs, review at 10 | Prevents suite bloat, keeps integration tier focused on seams |
| `approval-flow` | Conditional for v1 | Include in target set, defer if setup is unnatural |

## Implementation Prerequisites

These items must be completed before or as part of this work:

1. **Enhance `/readyz` endpoint** — must verify DB connection and migration completion, not just return `ok: true`
2. **Verify CI workflow exists** — the spec assumes `.github/workflows/ci.yml` with an existing `check` job. If CI does not yet exist, creating the workflow is part of this work.
3. **Verify Clerk `addClerkCommands` is inert** — confirm no side effects when Clerk keys are absent, or gate the import
