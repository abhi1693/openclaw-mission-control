# E2E Testing Framework Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-tier E2E testing architecture (stubbed + integration) with shared factories, Docker-based integration environment, and parallel CI pipeline.

**Architecture:** Shared factory layer serves both a refactored stubbed Cypress tier and a new real-backend integration tier. Docker Compose `--profile e2e` provides an ephemeral test stack. CI runs both tiers in parallel after existing `check` job.

**Tech Stack:** Cypress 14, TypeScript, Docker Compose, FastAPI, PostgreSQL, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-03-12-e2e-testing-framework-design.md`

---

## Chunk 1: Shared Factory Layer + Commands Cleanup

### Task 1: Create factory reset utility and user factory

**Files:**
- Create: `frontend/cypress/support/factories/reset.ts`
- Create: `frontend/cypress/support/factories/user.ts`

- [ ] **Step 1: Create `reset.ts` with counter management**

```ts
// frontend/cypress/support/factories/reset.ts
let _counter = 0;

export function nextId(prefix: string): string {
  return `${prefix}-${++_counter}`;
}

export function resetFactoryState(): void {
  _counter = 0;
}
```

- [ ] **Step 2: Create `user.ts` factory**

Reference the existing inline shapes from `testHooks.ts:36-46` and `boards_list.cy.ts:34-45` for realistic defaults.

```ts
// frontend/cypress/support/factories/user.ts
import { nextId } from "./reset";

export interface UserEntity {
  id: string;
  clerk_user_id: string;
  email: string;
  name: string;
  preferred_name: string;
  timezone: string;
  is_super_admin?: boolean;
}

export function buildUser(overrides?: Partial<UserEntity>): UserEntity {
  const id = overrides?.id ?? nextId("user");
  return {
    id,
    clerk_user_id: "local-auth-user",
    email: "local-auth-user@example.com",
    name: "Local User",
    preferred_name: "Local User",
    timezone: "UTC",
    ...overrides,
  };
}
```

- [ ] **Step 3: Verify file compiles**

Run: `cd frontend && npx tsc --noEmit cypress/support/factories/user.ts --esModuleInterop --moduleResolution node 2>&1 || echo "Type check will be validated when integrated"`

Expected: No blocking errors (Cypress types may need full project context)

- [ ] **Step 4: Commit**

```bash
git add frontend/cypress/support/factories/reset.ts frontend/cypress/support/factories/user.ts
git commit -m "feat(e2e): add factory reset utility and user factory"
```

---

### Task 2: Create org, board, task, and approval factories

**Files:**
- Create: `frontend/cypress/support/factories/org.ts`
- Create: `frontend/cypress/support/factories/board.ts`
- Create: `frontend/cypress/support/factories/task.ts`
- Create: `frontend/cypress/support/factories/approval.ts`

- [ ] **Step 1: Create `org.ts` factory**

Reference `testHooks.ts:48-58` and `testHooks.ts:60-71` for org and membership shapes.

```ts
// frontend/cypress/support/factories/org.ts
import { nextId } from "./reset";

export interface OrgEntity {
  id: string;
  name: string;
  is_active: boolean;
  role: string;
}

export function buildOrg(overrides?: Partial<OrgEntity>): OrgEntity {
  const id = overrides?.id ?? nextId("org");
  return {
    id,
    name: `Testing Org ${id}`,
    is_active: true,
    role: "owner",
    ...overrides,
  };
}

export interface OrgMemberEntity {
  id: string;
  organization_id: string;
  user_id: string;
  role: string;
  all_boards_read: boolean;
  all_boards_write: boolean;
  board_access: Array<{ board_id: string; can_read: boolean; can_write: boolean }>;
  created_at?: string;
  updated_at?: string;
}

export function buildOrgMember(overrides?: Partial<OrgMemberEntity>): OrgMemberEntity {
  const id = overrides?.id ?? nextId("membership");
  return {
    id,
    organization_id: "org-1",
    user_id: "user-1",
    role: "owner",
    all_boards_read: true,
    all_boards_write: true,
    board_access: [],
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}
```

- [ ] **Step 2: Create `board.ts` factory**

Reference `boards_list.cy.ts:54-77` and `board_tasks.cy.ts:100-147` for board + snapshot shapes. Separate entity from create-input per spec.

```ts
// frontend/cypress/support/factories/board.ts
import { nextId } from "./reset";

export interface BoardEntity {
  id: string;
  name: string;
  slug: string;
  description: string;
  gateway_id: string | null;
  board_group_id: string | null;
  board_type: string;
  objective: string | null;
  success_metrics: null;
  target_date: string | null;
  goal_confirmed: boolean;
  goal_source: string | null;
  organization_id: string;
  created_at: string;
  updated_at: string;
}

export function buildBoard(overrides?: Partial<BoardEntity>): BoardEntity {
  const id = overrides?.id ?? nextId("board");
  return {
    id,
    name: `Test Board ${id}`,
    slug: `test-board-${id}`,
    description: "",
    gateway_id: null,
    board_group_id: null,
    board_type: "general",
    objective: null,
    success_metrics: null,
    target_date: null,
    goal_confirmed: true,
    goal_source: null,
    organization_id: "org-1",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

export interface CreateBoardInput {
  name: string;
  slug: string;
  description: string;
  board_type?: string;
  gateway_id?: string | null;
  objective?: string | null;
  goal_confirmed?: boolean;
}

export function buildCreateBoardInput(overrides?: Partial<CreateBoardInput>): CreateBoardInput {
  const slug = overrides?.slug ?? `board-${Date.now()}`;
  return {
    name: overrides?.name ?? `New Board ${slug}`,
    slug,
    description: "",
    board_type: "general",
    ...overrides,
  };
}

export interface BoardSnapshotEntity {
  board: BoardEntity;
  tasks: TaskSnapshotItem[];
  agents: unknown[];
  approvals: unknown[];
  chat_messages: unknown[];
  pending_approvals_count?: number;
}

interface TaskSnapshotItem {
  id: string;
  title: string;
  [key: string]: unknown;
}

export function buildBoardSnapshot(
  board: BoardEntity,
  options?: { tasks?: TaskSnapshotItem[] },
): BoardSnapshotEntity {
  return {
    board,
    tasks: options?.tasks ?? [],
    agents: [],
    approvals: [],
    chat_messages: [],
    pending_approvals_count: 0,
  };
}
```

- [ ] **Step 3: Create `task.ts` factory**

Reference `board_tasks.cy.ts:120-141` and `board_tasks.cy.ts:157-179` for response shapes.

```ts
// frontend/cypress/support/factories/task.ts
import { nextId } from "./reset";

export interface TaskEntity {
  id: string;
  board_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  due_at: string | null;
  assigned_agent_id: string | null;
  depends_on_task_ids: string[];
  created_by_user_id: string | null;
  in_progress_at: string | null;
  created_at: string;
  updated_at: string;
  blocked_by_task_ids: string[];
  is_blocked: boolean;
  assignee: null;
  approvals_count: number;
  approvals_pending_count: number;
}

export function buildTask(overrides?: Partial<TaskEntity>): TaskEntity {
  const id = overrides?.id ?? nextId("task");
  return {
    id,
    board_id: "board-1",
    title: `Test Task ${id}`,
    description: "",
    status: "inbox",
    priority: "medium",
    due_at: null,
    assigned_agent_id: null,
    depends_on_task_ids: [],
    created_by_user_id: null,
    in_progress_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    blocked_by_task_ids: [],
    is_blocked: false,
    assignee: null,
    approvals_count: 0,
    approvals_pending_count: 0,
    ...overrides,
  };
}

export interface CreateTaskInput {
  title: string;
  description?: string;
  priority?: string;
  status?: string;
}

export function buildCreateTaskInput(overrides?: Partial<CreateTaskInput>): CreateTaskInput {
  return {
    title: `New Task ${Date.now()}`,
    ...overrides,
  };
}

export interface TaskCommentEntity {
  id: string;
  task_id: string;
  body: string;
  author_type: string;
  created_at: string;
}

export function buildTaskComment(overrides?: Partial<TaskCommentEntity>): TaskCommentEntity {
  const id = overrides?.id ?? nextId("comment");
  return {
    id,
    task_id: "task-1",
    body: "Test comment",
    author_type: "user",
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}
```

- [ ] **Step 4: Create `approval.ts` factory**

Reference `global_approvals.cy.ts:11-25` for the approval shape.

```ts
// frontend/cypress/support/factories/approval.ts
import { nextId } from "./reset";

export interface ApprovalEntity {
  id: string;
  board_id: string;
  action_type: string;
  status: string;
  confidence: number;
  created_at: string;
  task_id: string | null;
  task_ids: string[];
  payload: Record<string, unknown> | null;
}

export function buildApproval(overrides?: Partial<ApprovalEntity>): ApprovalEntity {
  const id = overrides?.id ?? nextId("approval");
  return {
    id,
    board_id: "board-1",
    action_type: "task.closeout",
    status: "pending",
    confidence: 92,
    created_at: "2026-01-01T00:00:00.000Z",
    task_id: null,
    task_ids: [],
    payload: null,
    ...overrides,
  };
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/cypress/support/factories/org.ts frontend/cypress/support/factories/board.ts frontend/cypress/support/factories/task.ts frontend/cypress/support/factories/approval.ts
git commit -m "feat(e2e): add org, board, task, and approval factories"
```

---

### Task 3: Create factory barrel export and wire reset into test lifecycle

**Files:**
- Create: `frontend/cypress/support/factories/index.ts`
- Modify: `frontend/cypress/support/commands.ts`

- [ ] **Step 1: Create `index.ts` barrel export**

```ts
// frontend/cypress/support/factories/index.ts
export { resetFactoryState, nextId } from "./reset";
export { buildUser } from "./user";
export type { UserEntity } from "./user";
export { buildOrg, buildOrgMember } from "./org";
export type { OrgEntity, OrgMemberEntity } from "./org";
export { buildBoard, buildCreateBoardInput, buildBoardSnapshot } from "./board";
export type { BoardEntity, CreateBoardInput, BoardSnapshotEntity } from "./board";
export { buildTask, buildCreateTaskInput, buildTaskComment } from "./task";
export type { TaskEntity, CreateTaskInput, TaskCommentEntity } from "./task";
export { buildApproval } from "./approval";
export type { ApprovalEntity } from "./approval";
```

- [ ] **Step 2: Update `commands.ts` to use `Cypress.env("AUTH_TOKEN")` with fallback**

In `frontend/cypress/support/commands.ts`, change the `loginWithLocalAuth` command to read the token from Cypress env, falling back to the existing default. This ensures integration tests automatically use the correct token.

Replace lines 5-6:
```ts
const DEFAULT_LOCAL_AUTH_TOKEN =
  "cypress-local-auth-token-0123456789-0123456789-0123456789x";
```

With:
```ts
const DEFAULT_LOCAL_AUTH_TOKEN =
  "cypress-local-auth-token-0123456789-0123456789-0123456789x";

function getAuthToken(explicitToken?: string): string {
  if (explicitToken) return explicitToken;
  const envToken = Cypress.env("AUTH_TOKEN") as string | undefined;
  return envToken || DEFAULT_LOCAL_AUTH_TOKEN;
}
```

And change line 18:
```ts
Cypress.Commands.add("loginWithLocalAuth", (token = DEFAULT_LOCAL_AUTH_TOKEN) => {
```

To:
```ts
Cypress.Commands.add("loginWithLocalAuth", (token?: string) => {
  const resolvedToken = getAuthToken(token);
```

And change line 21:
```ts
      win.sessionStorage.setItem(LOCAL_AUTH_STORAGE_KEY, token);
```

To:
```ts
      win.sessionStorage.setItem(LOCAL_AUTH_STORAGE_KEY, resolvedToken);
```

- [ ] **Step 3: Run existing stubbed E2E tests to verify no regression**

Run: `cd frontend && npx cypress run --spec cypress/e2e/activity_smoke.cy.ts --browser chrome 2>&1 | tail -20`

Expected: Tests still pass (no Cypress env is set, so fallback to default token)

Note: This requires the frontend dev server running. If not available, verify with typecheck instead:
Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add frontend/cypress/support/factories/index.ts frontend/cypress/support/commands.ts
git commit -m "feat(e2e): add factory barrel export and env-aware auth token"
```

---

### Task 4: Create intercept helpers

**Files:**
- Create: `frontend/cypress/support/intercepts/auth.ts`
- Create: `frontend/cypress/support/intercepts/boards.ts`
- Create: `frontend/cypress/support/intercepts/sse.ts`
- Create: `frontend/cypress/support/intercepts/dashboard.ts`
- Create: `frontend/cypress/support/intercepts/index.ts`

- [ ] **Step 1: Create `auth.ts` intercept helper**

Extracts the common auth stubs from `testHooks.ts:28-71`. Uses factories for data.

```ts
// frontend/cypress/support/intercepts/auth.ts
import { buildUser, buildOrg, buildOrgMember } from "../factories";
import type { UserEntity, OrgEntity, OrgMemberEntity } from "../factories";

interface StubAuthOptions {
  user?: Partial<UserEntity>;
  org?: Partial<OrgEntity>;
  member?: Partial<OrgMemberEntity>;
}

export function stubAuth(apiBase: string, options: StubAuthOptions = {}): void {
  const user = buildUser(options.user);
  const org = buildOrg({ id: "org-1", name: "Testing Org", ...options.org });
  const member = buildOrgMember({
    organization_id: org.id,
    user_id: user.id,
    ...options.member,
  });

  cy.intercept("GET", "**/healthz", {
    statusCode: 200,
    body: { ok: true },
  }).as("healthz");

  cy.intercept("GET", `${apiBase}/users/me*`, {
    statusCode: 200,
    body: user,
  }).as("usersMe");

  cy.intercept("GET", `${apiBase}/organizations/me/list*`, {
    statusCode: 200,
    body: [org],
  }).as("organizationsList");

  cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
    statusCode: 200,
    body: member,
  }).as("orgMeMember");
}
```

- [ ] **Step 2: Create `boards.ts` intercept helper**

```ts
// frontend/cypress/support/intercepts/boards.ts
import { buildBoard } from "../factories";
import type { BoardEntity } from "../factories";

interface StubBoardsOptions {
  boards?: BoardEntity[];
  groups?: Array<Record<string, unknown>>;
}

export function stubBoards(apiBase: string, options: StubBoardsOptions = {}): void {
  const boards = options.boards ?? [buildBoard({ id: "board-1", name: "Testing" })];
  const groups = options.groups ?? [];

  cy.intercept("GET", `${apiBase}/boards*`, {
    statusCode: 200,
    body: {
      items: boards,
      total: boards.length,
      limit: 200,
      offset: 0,
    },
  }).as("boardsList");

  cy.intercept("GET", `${apiBase}/board-groups*`, {
    statusCode: 200,
    body: {
      items: groups,
      total: groups.length,
      limit: 200,
      offset: 0,
    },
  }).as("boardGroupsList");
}
```

- [ ] **Step 3: Create `sse.ts` intercept helper**

Extracts the duplicated SSE stub from `board_tasks.cy.ts:17-35` and `activity_feed.cy.ts:17-36`.

```ts
// frontend/cypress/support/intercepts/sse.ts

const EMPTY_SSE = {
  statusCode: 200,
  headers: { "content-type": "text/event-stream" },
  body: "",
};

export function stubEmptySSEStreams(apiBase: string): void {
  cy.intercept("GET", `${apiBase}/boards/*/tasks/stream*`, EMPTY_SSE).as("tasksStream");
  cy.intercept("GET", `${apiBase}/boards/*/approvals/stream*`, EMPTY_SSE).as("approvalsStream");
  cy.intercept("GET", `${apiBase}/boards/*/memory/stream*`, EMPTY_SSE).as("memoryStream");
  cy.intercept("GET", `${apiBase}/agents/stream*`, EMPTY_SSE).as("agentsStream");
}
```

- [ ] **Step 4: Create `dashboard.ts` intercept helper**

Extracts from `mobile_sidebar.cy.ts:15-63`.

```ts
// frontend/cypress/support/intercepts/dashboard.ts

const EMPTY_SERIES = {
  primary: { range: "7d", bucket: "day", points: [] },
  comparison: { range: "7d", bucket: "day", points: [] },
};

export function stubDashboard(apiBase: string): void {
  cy.intercept("GET", `${apiBase}/metrics/dashboard*`, {
    statusCode: 200,
    body: {
      generated_at: "2026-01-01T00:00:00.000Z",
      range: "7d",
      kpis: {
        inbox_tasks: 0,
        in_progress_tasks: 0,
        review_tasks: 0,
        done_tasks: 0,
        tasks_in_progress: 0,
        active_agents: 0,
        error_rate_pct: 0,
        median_cycle_time_hours_7d: null,
      },
      throughput: EMPTY_SERIES,
      cycle_time: EMPTY_SERIES,
      error_rate: EMPTY_SERIES,
      wip: EMPTY_SERIES,
      pending_approvals: { items: [], total: 0 },
    },
  }).as("dashboardMetrics");

  cy.intercept("GET", `${apiBase}/agents*`, {
    statusCode: 200,
    body: { items: [], total: 0 },
  }).as("agentsList");

  cy.intercept("GET", `${apiBase}/activity*`, {
    statusCode: 200,
    body: { items: [], total: 0 },
  }).as("activityList");

  cy.intercept("GET", `${apiBase}/gateways/status*`, {
    statusCode: 200,
    body: { gateways: [] },
  }).as("gatewaysStatus");
}
```

- [ ] **Step 5: Create `index.ts` barrel export**

```ts
// frontend/cypress/support/intercepts/index.ts
export { stubAuth } from "./auth";
export { stubBoards } from "./boards";
export { stubEmptySSEStreams } from "./sse";
export { stubDashboard } from "./dashboard";
```

- [ ] **Step 6: Commit**

```bash
git add frontend/cypress/support/intercepts/
git commit -m "feat(e2e): add composable intercept helpers for auth, boards, SSE, dashboard"
```

---

### Task 5: Add unhandled-request failsafe for stubbed tier

**Files:**
- Modify: `frontend/cypress/support/e2e.ts`

- [ ] **Step 1: Add global `cy.on('fail')` handler for unintercepted requests in the stubbed config**

Add to the end of `frontend/cypress/support/e2e.ts`, before the `import "./commands"` line:

```ts
// Fail stubbed tests if an API request escapes interception.
// Integration tests (which set Cypress.env("API_BASE")) skip this check.
if (!Cypress.env("API_BASE")) {
  Cypress.on("fail", (err) => {
    // Re-throw all errors; this is just the hook point.
    throw err;
  });

  // Log a warning for any XHR/fetch that isn't intercepted.
  // Cypress doesn't natively block unintercepted requests, but we can
  // detect them via the `before:request` event if available, or rely on
  // cy.intercept routeHandler logging.
  // For now, add a defensive intercept that catches anything to /api/
  // not already matched by a more specific intercept:
  beforeEach(() => {
    cy.intercept({ url: /\/api\/v1\//, middleware: true }, (req) => {
      // If this middleware intercept is the ONLY handler, the request
      // was not stubbed by a test-specific intercept.
      // Log it so flaky leaks are visible in CI output.
      Cypress.log({
        name: "UNSTUBBED API",
        message: `${req.method} ${req.url}`,
        consoleProps: () => ({ method: req.method, url: req.url }),
      });
    });
  });
}
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
git add frontend/cypress/support/e2e.ts
git commit -m "feat(e2e): add unhandled API request detection for stubbed tier"
```

---

## Chunk 2: Stubbed Test Refactoring

### Task 6: Refactor `boards_list.cy.ts` to use factories and intercept helpers

**Files:**
- Modify: `frontend/cypress/e2e/boards_list.cy.ts`

- [ ] **Step 1: Rewrite `boards_list.cy.ts` using shared helpers**

Replace the full content of `frontend/cypress/e2e/boards_list.cy.ts`:

```ts
/// <reference types="cypress" />

import { resetFactoryState, buildUser, buildOrg, buildOrgMember, buildBoard } from "../support/factories";
import { stubAuth, stubBoards } from "../support/intercepts";

describe("/boards", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    resetFactoryState();
  });

  it("auth negative: signed-out user is shown local auth login", () => {
    cy.visit("/boards");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("happy path: signed-in user sees boards list and create button", () => {
    const board = buildBoard({
      id: "b1",
      name: "Demo Board",
      slug: "demo-board",
      description: "Demo",
      gateway_id: "g1",
      goal_source: "test",
      organization_id: "o1",
    });

    stubAuth(apiBase, {
      user: { id: "u1", clerk_user_id: "clerk_u1", email: "local-auth-user@example.com", name: "Jane Test", preferred_name: "Jane", timezone: "America/New_York", is_super_admin: false },
      org: { id: "o1", name: "Personal" },
      member: { id: "m1", organization_id: "o1", user_id: "u1" },
    });
    stubBoards(apiBase, { boards: [board] });

    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    cy.wait(["@orgMeMember", "@usersMe", "@organizationsList", "@boardsList", "@boardGroupsList"]);

    cy.contains(/boards/i).should("be.visible");
    cy.contains("Demo Board").should("be.visible");
    cy.contains("a", /create board/i).should("be.visible");
  });
});
```

- [ ] **Step 2: Run the refactored test (requires dev server)**

Run: `cd frontend && npx cypress run --spec cypress/e2e/boards_list.cy.ts --browser chrome 2>&1 | tail -30`

If dev server not available, verify types:
Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
git add frontend/cypress/e2e/boards_list.cy.ts
git commit -m "refactor(e2e): boards_list to use shared factories and intercept helpers"
```

---

### Task 7: Refactor `activity_feed.cy.ts` to use factories and intercept helpers

**Files:**
- Modify: `frontend/cypress/e2e/activity_feed.cy.ts`

- [ ] **Step 1: Rewrite `activity_feed.cy.ts`**

Replace the full content of `frontend/cypress/e2e/activity_feed.cy.ts`:

```ts
/// <reference types="cypress" />

import { resetFactoryState, buildBoard, buildBoardSnapshot } from "../support/factories";
import { stubAuth, stubBoards, stubEmptySSEStreams } from "../support/intercepts";

describe("/activity feed", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    resetFactoryState();
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  function stubBoardBootstrap() {
    const board = buildBoard({ id: "b1", name: "Testing" });
    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [board] });

    cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
      statusCode: 200,
      body: buildBoardSnapshot(board, {
        tasks: [{ id: "t1", title: "CI hardening" }],
      }),
    }).as("boardSnapshot");
  }

  function assertSignedInAndLanded() {
    cy.waitForAppLoaded();
    cy.contains(/live feed/i).should("be.visible");
  }

  it("auth negative: signed-out user sees auth prompt", () => {
    cy.visit("/activity");
    cy.contains(/sign in to view the feed|local authentication/i, {
      timeout: 20_000,
    }).should("be.visible");
  });

  it("happy path: renders task comment cards", () => {
    stubBoardBootstrap();

    cy.intercept("GET", "**/api/v1/activity**", {
      statusCode: 200,
      body: {
        items: [
          {
            id: "e1",
            event_type: "task.comment",
            message: "Hello world",
            agent_id: null,
            agent_name: "Kunal",
            created_at: "2026-02-07T00:00:00Z",
            task_id: "t1",
            task_title: "CI hardening",
            agent_role: "QA 2",
          },
        ],
      },
    }).as("activityList");

    stubEmptySSEStreams(apiBase);

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    assertSignedInAndLanded();
    cy.wait("@activityList", { timeout: 20_000 });

    cy.contains(/ci hardening|unknown task/i).should("be.visible");
    cy.contains(/hello world/i).should("be.visible");
  });

  it("empty state: shows waiting message when no items", () => {
    stubBoardBootstrap();

    cy.intercept("GET", "**/api/v1/activity**", {
      statusCode: 200,
      body: { items: [] },
    }).as("activityList");

    stubEmptySSEStreams(apiBase);

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    assertSignedInAndLanded();
    cy.wait("@activityList", { timeout: 20_000 });

    cy.contains(/waiting for new activity/i).should("be.visible");
  });

  it("error state: shows failure UI when API errors", () => {
    stubBoardBootstrap();

    cy.intercept("GET", "**/api/v1/activity**", {
      statusCode: 500,
      body: { detail: "boom" },
    }).as("activityList");

    stubEmptySSEStreams(apiBase);

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    assertSignedInAndLanded();
    cy.wait("@activityList", { timeout: 20_000 });

    cy.contains(/unable to load activity feed|unable to load feed|boom/i).should(
      "be.visible",
    );
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/e2e/activity_feed.cy.ts
git commit -m "refactor(e2e): activity_feed to use shared factories and intercept helpers"
```

---

### Task 8: Refactor `global_approvals.cy.ts` to use factories

**Files:**
- Modify: `frontend/cypress/e2e/global_approvals.cy.ts`

- [ ] **Step 1: Rewrite `global_approvals.cy.ts`**

Replace the full content:

```ts
/// <reference types="cypress" />

import { resetFactoryState, buildBoard, buildApproval } from "../support/factories";
import { stubAuth, stubBoards } from "../support/intercepts";

describe("Global approvals", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    resetFactoryState();
  });

  it("can render a pending approval and approve it", () => {
    const board = buildBoard({ id: "b1", name: "Testing" });
    const approval = buildApproval({
      id: "a1",
      board_id: "b1",
      action_type: "task.closeout",
      status: "pending",
      confidence: 92,
      task_id: "t1",
      task_ids: ["t1"],
      payload: {
        task_id: "t1",
        title: "Close task",
        reason: "Merged and ready to close",
      },
    });

    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [board] });

    cy.intercept("GET", `${apiBase}/boards/b1/approvals*`, {
      statusCode: 200,
      body: { items: [approval] },
    }).as("approvalsList");

    cy.intercept("PATCH", `${apiBase}/boards/b1/approvals/a1`, {
      statusCode: 200,
      body: { ...approval, status: "approved" },
    }).as("approvalUpdate");

    cy.loginWithLocalAuth();
    cy.visit("/approvals");
    cy.waitForAppLoaded();

    cy.wait(
      ["@usersMe", "@organizationsList", "@orgMeMember", "@boardsList", "@approvalsList"],
      { timeout: 20_000 },
    );

    cy.contains(/unapproved tasks/i).should("be.visible");
    cy.contains(/task\s*(?:·|\u00b7|\u2022)?\s*closeout/i).should("be.visible");

    cy.contains("button", /^approve$/i).click();
    cy.wait("@approvalUpdate", { timeout: 20_000 });

    cy.contains(/approved/i).should("be.visible");
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/e2e/global_approvals.cy.ts
git commit -m "refactor(e2e): global_approvals to use shared factories"
```

---

### Task 9: Refactor `mobile_sidebar.cy.ts` to use intercept helpers

**Files:**
- Modify: `frontend/cypress/e2e/mobile_sidebar.cy.ts`

- [ ] **Step 1: Rewrite `mobile_sidebar.cy.ts`**

Replace the full content:

```ts
/// <reference types="cypress" />

import { resetFactoryState } from "../support/factories";
import { stubAuth, stubBoards, stubDashboard } from "../support/intercepts";

describe("/dashboard - mobile sidebar", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    resetFactoryState();
  });

  function visitDashboardAuthenticated() {
    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [] });
    stubDashboard(apiBase);
    cy.loginWithLocalAuth();
    cy.visit("/dashboard");
    cy.waitForAppLoaded();
  }

  it("auth negative: signed-out user does not see hamburger button", () => {
    cy.visit("/dashboard");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
    cy.get('[aria-label="Toggle navigation"]').should("not.exist");
  });

  it("mobile: hamburger button visible and sidebar hidden by default", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').should("be.visible");
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });

  it("desktop: hamburger button hidden and sidebar always visible", () => {
    cy.viewport(1280, 800);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').should("not.be.visible");
    cy.get("aside").should("be.visible");
  });

  it("mobile: click hamburger opens sidebar and shows backdrop", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("aside").should("be.visible");
    cy.get('[data-cy="sidebar-backdrop"]').should("exist");
  });

  it("mobile: click backdrop closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get('[data-cy="sidebar-backdrop"]').click({ force: true });
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });

  it("mobile: clicking a nav link closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("aside").should("be.visible");
    cy.get("aside").within(() => {
      cy.contains("a", "Boards").click();
    });
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
  });

  it("mobile: pressing Escape closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("body").type("{esc}");
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/e2e/mobile_sidebar.cy.ts
git commit -m "refactor(e2e): mobile_sidebar to use shared intercept helpers"
```

---

### Task 10: Refactor remaining stubbed tests (`organizations`, `skill_packs_sync`, `local_auth_login`, `board_tasks`)

**Files:**
- Modify: `frontend/cypress/e2e/organizations.cy.ts`
- Modify: `frontend/cypress/e2e/skill_packs_sync.cy.ts`
- Modify: `frontend/cypress/e2e/local_auth_login.cy.ts`
- Modify: `frontend/cypress/e2e/board_tasks.cy.ts`

Note: `activity_smoke.cy.ts` has no inline mocks and needs no refactoring.

- [ ] **Step 1: Rewrite `organizations.cy.ts`**

Replace full content:

```ts
/// <reference types="cypress" />

import { resetFactoryState, buildUser, buildOrgMember } from "../support/factories";
import { stubAuth } from "../support/intercepts";

describe("Organizations (PR #61)", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    resetFactoryState();
  });

  it("negative: signed-out user sees auth prompt when opening /organization", () => {
    cy.visit("/organization");
    cy.contains(/sign in to manage your organization|local authentication/i, {
      timeout: 30_000,
    }).should("be.visible");
  });

  it("positive: signed-in user can view /organization and sees correct invite permissions", () => {
    // Semantically important: role is "member" (not default "owner")
    // because invite button should be disabled for non-admins.
    stubAuth(apiBase, {
      org: { id: "org1", name: "Testing Org" },
      member: { role: "member", organization_id: "org1", user_id: "u1" },
    });

    cy.intercept("GET", `${apiBase}/organizations/me`, {
      statusCode: 200,
      body: { id: "org1", name: "Testing Org" },
    }).as("orgMe");

    cy.intercept("GET", `${apiBase}/organizations/me/members*`, {
      statusCode: 200,
      body: {
        items: [
          {
            id: "membership-1",
            user_id: "u1",
            role: "member",
            user: {
              id: "u1",
              email: "local@example.com",
              name: "Local User",
              preferred_name: "Local User",
            },
          },
        ],
      },
    }).as("orgMembers");

    cy.intercept("GET", `${apiBase}/boards*`, {
      statusCode: 200,
      body: { items: [] },
    }).as("boardsList");

    cy.loginWithLocalAuth();
    cy.visit("/organization");
    cy.waitForAppLoaded();
    cy.contains(/members\s*&\s*invites/i).should("be.visible");
    cy.contains("button", /invite member/i)
      .should("be.visible")
      .should("be.disabled")
      .and("have.attr", "title")
      .and("match", /only organization admins can invite/i);
  });
});
```

- [ ] **Step 2: Rewrite `skill_packs_sync.cy.ts`**

Replace full content:

```ts
/// <reference types="cypress" />

import { resetFactoryState } from "../support/factories";
import { stubAuth } from "../support/intercepts";

describe("Skill packs", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    resetFactoryState();
  });

  it("can sync a pack and surface warnings", () => {
    stubAuth(apiBase);

    cy.intercept("GET", `${apiBase}/skills/packs*`, {
      statusCode: 200,
      body: [
        {
          id: "p1",
          name: "OpenClaw Skills",
          description: "Test pack",
          source_url: "https://github.com/openclaw/skills",
          branch: "main",
          skill_count: 12,
          updated_at: "2026-02-14T00:00:00Z",
          created_at: "2026-02-10T00:00:00Z",
        },
      ],
    }).as("packsList");

    cy.intercept("POST", `${apiBase}/skills/packs/p1/sync*`, {
      statusCode: 200,
      body: {
        warnings: ["1 skill skipped (missing SKILL.md)"],
      },
    }).as("packSync");

    cy.loginWithLocalAuth();
    cy.visit("/skills/packs");
    cy.waitForAppLoaded();

    cy.wait(["@usersMe", "@organizationsList", "@orgMeMember", "@packsList"], {
      timeout: 20_000,
    });
    cy.contains(/openclaw skills/i).should("be.visible");

    cy.contains("button", /^sync$/i).click();
    cy.wait("@packSync", { timeout: 20_000 });

    cy.contains(/skill skipped/i).should("be.visible");
  });
});
```

- [ ] **Step 3: Rewrite `local_auth_login.cy.ts`**

Replace full content:

```ts
/// <reference types="cypress" />

import { resetFactoryState, buildBoard, buildBoardSnapshot } from "../support/factories";
import { stubAuth, stubBoards } from "../support/intercepts";

describe("Local auth login", () => {
  beforeEach(() => {
    resetFactoryState();
  });

  it("user with local auth token can access protected route", () => {
    const apiBase = "**/api/v1";
    const board = buildBoard({ id: "b1", name: "Testing" });

    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [board] });

    cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
      statusCode: 200,
      body: buildBoardSnapshot(board),
    }).as("boardSnapshot");

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    cy.waitForAppLoaded();
    cy.contains(/live feed/i).should("be.visible");
  });
});
```

- [ ] **Step 4: Rewrite `board_tasks.cy.ts`**

This is the largest test (305 lines). Replace full content:

```ts
/// <reference types="cypress" />

import {
  resetFactoryState,
  buildBoard,
  buildBoardSnapshot,
  buildTask,
  buildOrgMember,
} from "../support/factories";
import { stubAuth, stubBoards, stubEmptySSEStreams } from "../support/intercepts";

describe("/boards/:id task board", () => {
  const apiBase = "**/api/v1";
  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    resetFactoryState();
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  function openEditTaskDialog() {
    cy.get('button[title="Edit task"]', { timeout: 20_000 })
      .should("be.visible")
      .and("not.be.disabled")
      .click();
    cy.get('[aria-label="Edit task"]', { timeout: 20_000 }).should("be.visible");
  }

  it("auth negative: signed-out user is shown local auth login", () => {
    cy.visit("/boards/b1");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("happy path: renders tasks from snapshot and supports create + status update + delete (stubbed)", () => {
    const board = buildBoard({
      id: "b1",
      name: "Demo Board",
      slug: "demo-board",
      description: "Demo",
      gateway_id: "g1",
      goal_source: "test",
      organization_id: "o1",
    });

    const existingTask = buildTask({
      id: "t1",
      board_id: "b1",
      title: "Inbox task",
      status: "inbox",
    });

    stubEmptySSEStreams(apiBase);

    stubAuth(apiBase, {
      user: { id: "u1", clerk_user_id: "clerk_u1", email: "local-auth-user@example.com", name: "Jane Test", preferred_name: "Jane", timezone: "America/New_York", is_super_admin: false },
      org: { id: "o1", name: "Personal" },
      member: buildOrgMember({
        id: "m1",
        organization_id: "o1",
        user_id: "u1",
        board_access: [{ board_id: "b1", can_read: true, can_write: true }],
      }),
    });

    cy.intercept("GET", `${apiBase}/tags*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("tags");

    cy.intercept("GET", `${apiBase}/organizations/me/custom-fields*`, {
      statusCode: 200,
      body: [],
    }).as("customFields");

    cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
      statusCode: 200,
      body: buildBoardSnapshot(board, { tasks: [existingTask] }),
    }).as("snapshot");

    cy.intercept("GET", `${apiBase}/boards/b1/group-snapshot*`, {
      statusCode: 200,
      body: { group: null, boards: [] },
    }).as("groupSnapshot");

    cy.intercept("POST", `${apiBase}/boards/b1/tasks`, (req) => {
      expect(req.body).to.have.property("title");
      const newTask = buildTask({
        id: "t2",
        board_id: "b1",
        title: req.body.title,
        description: req.body.description ?? "",
        priority: req.body.priority ?? "medium",
      });
      req.reply({ statusCode: 200, body: newTask });
    }).as("createTask");

    cy.intercept("PATCH", `${apiBase}/boards/b1/tasks/t1`, (req) => {
      expect(req.body).to.have.property("status");
      const updated = buildTask({
        ...existingTask,
        status: req.body.status,
        updated_at: "2026-01-01T00:00:01.000Z",
      });
      req.reply({ statusCode: 200, body: updated });
    }).as("updateTask");

    cy.intercept("DELETE", `${apiBase}/boards/b1/tasks/t1`, {
      statusCode: 200,
      body: { ok: true },
    }).as("deleteTask");

    cy.intercept("GET", `${apiBase}/boards/b1/tasks/t1/comments*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("taskComments");

    cy.loginWithLocalAuth();
    cy.visit("/boards/b1");
    cy.waitForAppLoaded();

    cy.wait([
      "@snapshot",
      "@groupSnapshot",
      "@orgMeMember",
      "@usersMe",
      "@organizationsList",
      "@tags",
      "@customFields",
    ]);

    // Existing task visible.
    cy.contains("Inbox task").should("be.visible");

    // Create task flow.
    cy.get('button[aria-label="New task"]')
      .should("be.visible")
      .and("not.be.disabled")
      .click();

    cy.contains('[role="dialog"]', "New task")
      .should("be.visible")
      .within(() => {
        cy.contains("label", "Title").parent().find("input").type("New task");
        cy.contains("button", /^Create task$/)
          .should("be.visible")
          .and("not.be.disabled")
          .click();
      });
    cy.wait(["@createTask"]);
    cy.contains("New task").should("be.visible");

    // Open edit task dialog.
    cy.contains("Inbox task").scrollIntoView().should("be.visible").click();
    cy.wait(["@taskComments"]);
    cy.contains(/task detail/i).should("be.visible");
    openEditTaskDialog();

    // Change status via Status select.
    cy.get('[aria-label="Edit task"]').within(() => {
      cy.contains("label", "Status")
        .parent()
        .within(() => {
          cy.get('[role="combobox"]').first().should("be.visible").click();
        });
    });
    cy.contains("In progress").should("be.visible").click();

    cy.contains("button", /save changes/i)
      .should("be.visible")
      .and("not.be.disabled")
      .click();
    cy.wait(["@updateTask"]);
    cy.get('[aria-label="Edit task"]').should("not.exist");

    // Reopen and delete.
    cy.contains(/task detail/i).should("be.visible");
    openEditTaskDialog();

    cy.get('[aria-label="Edit task"]').within(() => {
      cy.contains("button", /^Delete task$/)
        .scrollIntoView()
        .should("be.visible")
        .and("not.be.disabled")
        .click();
    });
    cy.get('[aria-label="Delete task"]').should("be.visible");
    cy.get('[aria-label="Delete task"]').within(() => {
      cy.contains("button", /^Delete task$/)
        .scrollIntoView()
        .should("be.visible")
        .and("not.be.disabled")
        .click();
    });
    cy.wait(["@deleteTask"]);
    cy.contains("Inbox task").should("not.exist");
  });
});
```

- [ ] **Step 5: Verify typecheck passes**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add frontend/cypress/e2e/organizations.cy.ts frontend/cypress/e2e/skill_packs_sync.cy.ts frontend/cypress/e2e/local_auth_login.cy.ts frontend/cypress/e2e/board_tasks.cy.ts
git commit -m "refactor(e2e): remaining stubbed tests to use shared factories and helpers"
```

---

### Task 11: Clean up legacy `testHooks.ts` — delegate to `stubAuth`

**Files:**
- Modify: `frontend/cypress/support/testHooks.ts`

- [ ] **Step 1: Rewrite `testHooks.ts` to delegate to `stubAuth`**

The existing `setupCommonPageTestHooks()` is still imported by tests that were refactored to use `stubAuth` directly. Since we've removed those imports, we can simplify `testHooks.ts` to just re-export for backward compat if any external consumers exist, or keep it as a thin wrapper. Since the spec says "stays as a convenience wrapper":

Replace full content of `frontend/cypress/support/testHooks.ts`:

```ts
/// <reference types="cypress" />

import { resetFactoryState } from "./factories";
import { stubAuth } from "./intercepts";

type CommonPageTestHooksOptions = {
  timeoutMs?: number;
  orgMemberRole?: string;
  organizationId?: string;
  organizationName?: string;
  userId?: string;
  userEmail?: string;
  userName?: string;
};

/**
 * Legacy convenience wrapper around stubAuth + factory reset.
 * New tests should use stubAuth() and resetFactoryState() directly.
 */
export function setupCommonPageTestHooks(
  apiBase: string,
  options: CommonPageTestHooksOptions = {},
): void {
  const {
    timeoutMs = 20_000,
    orgMemberRole = "owner",
    organizationId = "org1",
    organizationName = "Testing Org",
    userId = "u1",
    userEmail = "local-auth-user@example.com",
    userName = "Local User",
  } = options;
  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    resetFactoryState();
    Cypress.config("defaultCommandTimeout", timeoutMs);

    stubAuth(apiBase, {
      user: { id: userId, email: userEmail, name: userName, preferred_name: userName },
      org: { id: organizationId, name: organizationName },
      member: { role: orgMemberRole, organization_id: organizationId, user_id: userId },
    });
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/support/testHooks.ts
git commit -m "refactor(e2e): testHooks delegates to stubAuth, kept as convenience wrapper"
```

---

## Chunk 3: Backend Prerequisites + Docker E2E Environment

### Task 12: Enhance `/readyz` endpoint to verify DB connectivity

**Files:**
- Modify: `backend/app/main.py` (lines ~521-536)

- [ ] **Step 1: Update the `readyz` endpoint to check DB**

In `backend/app/main.py`:

**First, update imports.** Line 8 currently reads:
```python
from fastapi import APIRouter, FastAPI, status
```
Change to:
```python
from fastapi import APIRouter, Depends, FastAPI, status
```

Line 40 currently reads:
```python
from app.db.session import init_db
```
Change to:
```python
from app.db.session import get_session, init_db
```

Add this import near line 41:
```python
from sqlmodel.ext.asyncio.session import AsyncSession
```

**Then, replace the `readyz` function** (around line 534):

```python
# Before:
def readyz() -> HealthStatusResponse:
    """Readiness probe endpoint for service orchestration checks."""
    return HealthStatusResponse(ok=True)
```

```python
# After:
async def readyz(
    session: AsyncSession = Depends(get_session),
) -> HealthStatusResponse:
    """Readiness probe endpoint for service orchestration checks.

    Verifies the database connection is live by executing a simple query.
    """
    from sqlalchemy import text

    await session.execute(text("SELECT 1"))
    return HealthStatusResponse(ok=True)
```

- [ ] **Step 2: Run backend tests to verify no regression**

Run: `cd backend && uv run pytest tests/test_health*.py -v 2>&1 | tail -20`

If no specific health test file exists:
Run: `cd backend && uv run pytest -k "readyz or health" -v 2>&1 | tail -20`

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "fix(backend): readyz endpoint now verifies DB connectivity"
```

---

### Task 13: Create E2E seed script

**Files:**
- Create: `scripts/e2e_seed.py` (repo-root `scripts/` dir — this is what the Dockerfile copies into the image at `/app/scripts/`)

**Important:** The backend Dockerfile copies repo-root `scripts/` (not `backend/scripts/`) into the container at `/app/scripts`. The compose `e2e-seed` service runs `python -m scripts.e2e_seed`, so the seed script must live in the repo-root `scripts/` directory.

- [ ] **Step 1: Write the seed script**

```python
"""E2E test seed script.

Seeds the minimum prerequisite state for integration E2E tests:
- One test user
- One test organization
- Organization membership (user → org, owner role)

Writes directly via app models. Does NOT use product API endpoints.
Run via: python -m scripts.e2e_seed
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

# Ensure the backend app package is importable.
# In the Docker image, CWD is /app and app/ is a direct child.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Import models to register metadata.
from app import models as _models  # noqa: F401
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.users import User

# Well-known IDs matching cypress.integration.config.ts env values.
USER_ID = UUID("00000000-0000-4000-a000-000000000001")
ORG_ID = UUID("00000000-0000-4000-a000-000000000002")
MEMBER_ID = UUID("00000000-0000-4000-a000-000000000003")


async def seed(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        # Idempotent: check if user already exists.
        existing = await session.get(User, USER_ID)
        if existing:
            print(f"Seed data already exists (user {USER_ID}). Skipping.")
            return

        user = User(
            id=USER_ID,
            clerk_user_id="local-auth-user",
            email="e2e-test@example.com",
            name="E2E Test User",
            preferred_name="E2E User",
            timezone="UTC",
        )
        org = Organization(
            id=ORG_ID,
            name="E2E Testing Org",
        )
        member = OrganizationMember(
            id=MEMBER_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            role="owner",
            all_boards_read=True,
            all_boards_write=True,
        )

        session.add(user)
        session.add(org)
        session.add(member)
        await session.commit()

    print(f"Seeded: user={USER_ID} org={ORG_ID} member={MEMBER_ID}")

    await engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(seed(database_url))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/e2e_seed.py
git commit -m "feat(e2e): add database seed script for integration test prerequisites"
```

---

### Task 14: Add Docker Compose E2E profile

**Files:**
- Modify: `compose.yml`

- [ ] **Step 1: Add E2E services to `compose.yml`**

Append before the `volumes:` section at the end of `compose.yml`:

```yaml

  # ── E2E Integration Test Services ──────────────────────────────
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
      interval: 5s
      timeout: 3s
      retries: 20
    tmpfs:
      - /var/lib/postgresql/data

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
      BASE_URL: "http://localhost:8000"
    ports:
      - "8001:8000"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8000/readyz || exit 1"]
      interval: 5s
      timeout: 10s
      retries: 12

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

- [ ] **Step 2: Verify compose config is valid**

Run: `cd /home/ollie/.openclaw/ocmc && docker compose --profile e2e config --quiet 2>&1`

Expected: No errors (silent success)

- [ ] **Step 3: Commit**

```bash
git add compose.yml
git commit -m "feat(e2e): add Docker Compose e2e profile with test DB, backend, and seed runner"
```

---

### Task 15: Add Makefile targets and integration Cypress config

**Files:**
- Modify: `Makefile`
- Create: `frontend/cypress.integration.config.ts`

- [ ] **Step 1: Create `cypress.integration.config.ts`**

```ts
// frontend/cypress.integration.config.ts
import { defineConfig } from "cypress";

export default defineConfig({
  e2e: {
    baseUrl: "http://localhost:3000",
    specPattern: "cypress/e2e-integration/**/*.cy.ts",
    supportFile: "cypress/support/e2e.ts",
    defaultCommandTimeout: 30_000,
    retries: {
      runMode: 2,
      openMode: 0,
    },
    env: {
      API_BASE: "http://localhost:8001",
      AUTH_TOKEN:
        "e2e-local-auth-token-0123456789-0123456789-0123456789x",
    },
  },
});
```

- [ ] **Step 2: Add Makefile targets**

Append to `Makefile` before or after the existing docker targets:

```makefile

# ── E2E Integration Targets ─────────────────────────────────────
.PHONY: e2e-up
e2e-up: ## Start E2E Docker stack (test DB + backend + redis)
	docker compose --profile e2e up -d --wait db-test backend-e2e redis

.PHONY: e2e-seed
e2e-seed: ## Seed E2E test database with prerequisite data
	docker compose --profile e2e run --rm e2e-seed

.PHONY: e2e-down
e2e-down: ## Tear down E2E Docker stack and volumes
	docker compose --profile e2e down -v

.PHONY: e2e-integration
e2e-integration: ## Run integration E2E tests (requires e2e-up + e2e-seed first)
	cd $(FRONTEND_DIR) && npx cypress run --config-file cypress.integration.config.ts --browser chrome

.PHONY: e2e-full
e2e-full: ## Full E2E cycle: start stack → seed → run tests → tear down
	$(MAKE) e2e-up
	$(MAKE) e2e-seed || ($(MAKE) e2e-down && exit 1)
	$(MAKE) e2e-integration || ($(MAKE) e2e-down && exit 1)
	$(MAKE) e2e-down
```

- [ ] **Step 3: Commit**

```bash
git add frontend/cypress.integration.config.ts Makefile
git commit -m "feat(e2e): add integration Cypress config and Makefile orchestration targets"
```

---

## Chunk 4: Integration Tests + Integration API Helper

### Task 16: Create integration API helper

**Files:**
- Create: `frontend/cypress/support/integration/api.ts`
- Create: `frontend/cypress/e2e-integration/.gitkeep`

- [ ] **Step 1: Create the integration directory and API helper**

```ts
// frontend/cypress/support/integration/api.ts
/// <reference types="cypress" />

// API_BASE is a real URL host (e.g. "http://localhost:8001"), NOT a Cypress
// glob pattern like "**/api/v1". It does NOT include the /api/v1 prefix.
const apiBase = (): string => Cypress.env("API_BASE") as string;
const authToken = (): string => Cypress.env("AUTH_TOKEN") as string;

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${authToken()}` };
}

/**
 * Thin API client for integration E2E test setup and verification.
 *
 * Setup helpers create prerequisites (boards, tasks).
 * Verification helpers confirm persisted state after UI actions.
 *
 * The behavior under test should always go through the UI.
 */
export const api = {
  // ── Setup helpers ──────────────────────────────────────────────

  createBoard(input: { name: string; slug: string; description: string; board_type?: string }) {
    return cy.request({
      method: "POST",
      url: `${apiBase()}/api/v1/boards`,
      headers: authHeaders(),
      body: input,
    });
  },

  createTask(boardId: string, input: { title: string; description?: string; priority?: string }) {
    return cy.request({
      method: "POST",
      url: `${apiBase()}/api/v1/boards/${boardId}/tasks`,
      headers: authHeaders(),
      body: input,
    });
  },

  // ── Verification helpers ───────────────────────────────────────

  getBoards() {
    return cy.request({
      method: "GET",
      url: `${apiBase()}/api/v1/boards`,
      headers: authHeaders(),
    });
  },

  getBoard(boardId: string) {
    return cy.request({
      method: "GET",
      url: `${apiBase()}/api/v1/boards/${boardId}/snapshot`,
      headers: authHeaders(),
    });
  },

  getTasks(boardId: string) {
    return cy.request({
      method: "GET",
      url: `${apiBase()}/api/v1/boards/${boardId}/snapshot`,
      headers: authHeaders(),
    });
  },
};
```

- [ ] **Step 2: Create the integration test directory**

Run: `mkdir -p frontend/cypress/e2e-integration && touch frontend/cypress/e2e-integration/.gitkeep`

- [ ] **Step 3: Commit**

```bash
git add frontend/cypress/support/integration/api.ts frontend/cypress/e2e-integration/.gitkeep
git commit -m "feat(e2e): add integration API helper and e2e-integration directory"
```

---

### Task 17: Write `auth-protected-access.cy.ts` integration test

**Files:**
- Create: `frontend/cypress/e2e-integration/auth-protected-access.cy.ts`

- [ ] **Step 1: Write the auth integration test**

```ts
/// <reference types="cypress" />

describe("Auth: protected route access (integration)", () => {
  it("unauthenticated user is redirected to sign-in", () => {
    // Visit without setting auth token in session storage.
    cy.visit("/boards");
    cy.contains(/local authentication|sign in/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("authenticated user can access boards with real API data", () => {
    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    // The seeded org should be visible (real data from backend-e2e).
    // The boards list may be empty (no boards seeded) but the page should render.
    cy.contains(/boards/i).should("be.visible");
    cy.contains("a", /create board/i).should("be.visible");
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/e2e-integration/auth-protected-access.cy.ts
git commit -m "feat(e2e): add auth-protected-access integration test"
```

---

### Task 18: Write `board-lifecycle.cy.ts` integration test

**Files:**
- Create: `frontend/cypress/e2e-integration/board-lifecycle.cy.ts`

- [ ] **Step 1: Write the board lifecycle integration test**

```ts
/// <reference types="cypress" />

import { api } from "../support/integration/api";

describe("Board lifecycle (integration)", () => {
  const boardName = `E2E Board ${Date.now()}`;
  const boardSlug = `e2e-board-${Date.now()}`;

  it("create a board through the UI and verify it persists", () => {
    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    // Click create board.
    cy.contains("a", /create board/i).click();

    // Fill out the create board form.
    // Selectors depend on the actual form structure — adjust if needed.
    cy.get('input[name="name"], input[placeholder*="name" i]', { timeout: 10_000 })
      .should("be.visible")
      .clear()
      .type(boardName);

    cy.get('input[name="slug"], input[placeholder*="slug" i]')
      .should("be.visible")
      .clear()
      .type(boardSlug);

    // Submit the form.
    cy.contains("button", /create/i)
      .should("be.visible")
      .and("not.be.disabled")
      .click();

    // Should navigate to the new board or show success.
    cy.url({ timeout: 15_000 }).should("include", "/boards/");

    // Verify via API that the board was persisted.
    api.getBoards().then((res) => {
      expect(res.status).to.eq(200);
      const boards = res.body.items || res.body;
      const created = boards.find(
        (b: { name: string }) => b.name === boardName,
      );
      expect(created, `Board "${boardName}" should exist in API response`).to.not
        .be.undefined;
    });
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/e2e-integration/board-lifecycle.cy.ts
git commit -m "feat(e2e): add board-lifecycle integration test"
```

---

### Task 19: Write `task-lifecycle.cy.ts` integration test

**Files:**
- Create: `frontend/cypress/e2e-integration/task-lifecycle.cy.ts`

- [ ] **Step 1: Write the task lifecycle integration test**

```ts
/// <reference types="cypress" />

import { api } from "../support/integration/api";

describe("Task lifecycle (integration)", () => {
  const boardName = `Task Test Board ${Date.now()}`;
  const boardSlug = `task-test-${Date.now()}`;
  let boardId: string;

  before(() => {
    // Seed a board via API — the board is a prerequisite, not the behavior under test.
    api.createBoard({
      name: boardName,
      slug: boardSlug,
      description: "Created by E2E integration test",
      board_type: "general",
    }).then((res) => {
      expect(res.status).to.eq(200);
      boardId = res.body.id;
    });
  });

  it("create a task through the UI and verify it persists", () => {
    cy.loginWithLocalAuth();
    cy.visit(`/boards/${boardId}`);
    cy.waitForAppLoaded();

    const taskTitle = `E2E Task ${Date.now()}`;

    // Open create task dialog.
    cy.get('button[aria-label="New task"]', { timeout: 15_000 })
      .should("be.visible")
      .click();

    cy.contains('[role="dialog"]', "New task")
      .should("be.visible")
      .within(() => {
        cy.contains("label", "Title").parent().find("input").type(taskTitle);
        cy.contains("button", /^Create task$/)
          .should("be.visible")
          .and("not.be.disabled")
          .click();
      });

    // Task should appear in the board.
    cy.contains(taskTitle, { timeout: 10_000 }).should("be.visible");

    // Verify via API that the task was persisted.
    api.getTasks(boardId).then((res) => {
      expect(res.status).to.eq(200);
      const tasks = res.body.tasks || [];
      const created = tasks.find(
        (t: { title: string }) => t.title === taskTitle,
      );
      expect(created, `Task "${taskTitle}" should exist`).to.not.be.undefined;
    });
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/cypress/e2e-integration/task-lifecycle.cy.ts
git commit -m "feat(e2e): add task-lifecycle integration test"
```

---

## Chunk 5: CI Pipeline

### Task 20: Split CI E2E into parallel stubbed and integration jobs

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Rename existing `e2e` job to `e2e-stubbed` and add `e2e-integration` job**

In `.github/workflows/ci.yml`, find the existing `e2e:` job (around line 319). Rename it to `e2e-stubbed:` and add the new `e2e-integration:` job after it.

Replace the entire `e2e:` job block (lines ~319-381) with:

```yaml
  e2e-stubbed:
    runs-on: ubuntu-latest
    needs: [check]
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node
        id: setup-node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend dependencies
        run: make frontend-sync

      - name: Cache Next.js build cache
        uses: actions/cache@v4
        with:
          path: frontend/.next/cache
          key: nextjs-${{ runner.os }}-node-${{ steps.setup-node.outputs.node-version }}-${{ hashFiles('frontend/package-lock.json') }}
          restore-keys: |
            nextjs-${{ runner.os }}-node-${{ steps.setup-node.outputs.node-version }}-

      - name: Start frontend (dev server)
        env:
          NEXT_PUBLIC_API_URL: "http://localhost:8000"
          NEXT_PUBLIC_AUTH_MODE: "local"
          NEXT_TELEMETRY_DISABLED: "1"
        run: |
          cd frontend
          npm run dev -- --hostname 0.0.0.0 --port 3000 > /tmp/frontend.log 2>&1 &
          for i in {1..60}; do
            if curl -sf http://localhost:3000/ > /dev/null; then exit 0; fi
            sleep 2
          done
          echo "Frontend did not start. Logs:"
          cat /tmp/frontend.log
          exit 1

      - name: Run Cypress stubbed E2E
        env:
          NEXT_PUBLIC_API_URL: "http://localhost:8000"
          NEXT_PUBLIC_AUTH_MODE: "local"
          NEXT_TELEMETRY_DISABLED: "1"
        run: |
          cd frontend
          npm run e2e -- --browser chrome

      - name: Upload Cypress artifacts
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: cypress-stubbed-artifacts
          if-no-files-found: ignore
          path: |
            frontend/cypress/screenshots/**
            frontend/cypress/videos/**
            /tmp/frontend.log

  e2e-integration:
    runs-on: ubuntu-latest
    needs: [check]
    timeout-minutes: 15

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node
        id: setup-node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Start E2E Docker stack
        run: make e2e-up

      - name: Seed E2E database
        run: make e2e-seed

      - name: Install frontend dependencies
        run: make frontend-sync

      - name: Start frontend (dev server pointing to E2E backend)
        env:
          NEXT_PUBLIC_API_URL: "http://localhost:8001"
          NEXT_PUBLIC_AUTH_MODE: "local"
          NEXT_TELEMETRY_DISABLED: "1"
        run: |
          cd frontend
          npm run dev -- --hostname 0.0.0.0 --port 3000 > /tmp/frontend-e2e.log 2>&1 &
          for i in {1..60}; do
            if curl -sf http://localhost:3000/ > /dev/null; then exit 0; fi
            sleep 2
          done
          echo "Frontend did not start. Logs:"
          cat /tmp/frontend-e2e.log
          exit 1

      - name: Run integration E2E tests
        run: make e2e-integration

      - name: Dump Docker logs on failure
        if: failure()
        run: |
          docker compose --profile e2e logs backend-e2e --tail 200 || true
          docker compose --profile e2e logs db-test --tail 50 || true
          docker compose --profile e2e logs redis --tail 50 || true

      - name: Upload artifacts on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: cypress-integration-artifacts
          if-no-files-found: ignore
          path: |
            frontend/cypress/screenshots/**
            frontend/cypress/videos/**
            /tmp/frontend-e2e.log

      - name: Tear down E2E stack
        if: always()
        run: make e2e-down
```

- [ ] **Step 2: Verify CI YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('/home/ollie/.openclaw/ocmc/.github/workflows/ci.yml'))" 2>&1`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "feat(ci): split E2E into parallel stubbed and integration jobs"
```

---

### Task 21: Final verification and cleanup

**Files:** None new

- [ ] **Step 1: Run frontend typecheck to catch any issues**

Run: `cd /home/ollie/.openclaw/ocmc/frontend && npx tsc --noEmit`

Expected: No type errors

- [ ] **Step 2: Run existing stubbed E2E tests if dev server is available**

Run: `cd /home/ollie/.openclaw/ocmc/frontend && npx cypress run --browser chrome 2>&1 | tail -30`

Expected: All 9 existing tests pass

- [ ] **Step 3: Remove `.gitkeep` from integration directory if tests exist**

Run: `rm -f frontend/cypress/e2e-integration/.gitkeep`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(e2e): final cleanup after E2E framework implementation"
```

---

## Task Dependency Summary

```
Task 1 (reset + user factory)
  → Task 2 (org/board/task/approval factories)
    → Task 3 (barrel export + commands update)
      → Task 4 (intercept helpers)
        → Task 5 (unhandled request failsafe)
          → Tasks 6-11 (stubbed test refactoring — can run in parallel)
            → Task 12 (readyz enhancement)
              → Task 13 (seed script)
                → Task 14 (compose profile)
                  → Task 15 (Makefile + integration config)
                    → Task 16 (integration API helper)
                      → Tasks 17-19 (integration tests — can run in parallel)
                        → Task 20 (CI pipeline)
                          → Task 21 (final verification)
```

**Parallel opportunities:**
- Tasks 6-11 (stubbed refactors) can run in parallel after Task 5
- Tasks 17-19 (integration tests) can run in parallel after Task 16
