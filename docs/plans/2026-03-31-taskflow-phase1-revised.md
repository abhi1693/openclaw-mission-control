# TaskFlow Phase 1 (Revised) — API Bridge + Auth + Frontend CRUD

> **Key insight:** The engine (taskflow-engine.ts, 7,816 lines) already supports ALL features. The gap is the API and frontend. Phase 1 is about building the bridge.

## Strategy: API Bridge Pattern

Instead of reimplementing business logic in the API, **bridge the API to the engine**. The engine runs inside NanoClaw containers — we need a way for the REST API to call engine operations.

### Option A: Direct SQLite (current approach)
The API reads/writes taskflow.db directly. Works for reads. For mutations, we'd duplicate engine validation logic in Python — bad.

### Option B: Engine as Library (recommended)
Import `TaskflowEngine` in a lightweight Node.js API layer alongside the Python API. The Node layer handles mutations via the engine; Python handles reads + auth.

### Option C: IPC Bridge
API writes mutation requests to IPC directory. NanoClaw picks them up and runs them through the engine. Async, eventual consistency.

### Option D: HTTP Gateway on Engine
Add a thin HTTP server inside the NanoClaw process that exposes engine operations as REST endpoints. The dashboard calls this directly (with auth proxy).

**Recommended: Option D** — least code, uses the existing engine, avoids duplication. Add a `/api/v2/` route handler in NanoClaw's main process that instantiates TaskflowEngine and exposes mutations.

---

## Phase 1A: Expose Engine as REST API

### New endpoints (on NanoClaw, not the Python API)

**Task mutations (bridge to engine):**
```
POST   /api/v2/boards/:id/tasks/create       → taskflow_create
PATCH  /api/v2/boards/:id/tasks/:tid/move     → taskflow_move
PATCH  /api/v2/boards/:id/tasks/:tid/update   → taskflow_update
PATCH  /api/v2/boards/:id/tasks/:tid/reassign → taskflow_reassign
POST   /api/v2/boards/:id/tasks/:tid/undo     → taskflow_undo
DELETE /api/v2/boards/:id/tasks/:tid           → taskflow_admin (cancel)

POST   /api/v2/boards/:id/tasks/:tid/dependency → taskflow_dependency
POST   /api/v2/boards/:id/admin                 → taskflow_admin
POST   /api/v2/boards/:id/hierarchy              → taskflow_hierarchy
GET    /api/v2/boards/:id/report/:type           → taskflow_report
```

**Task queries (bridge to engine):**
```
GET    /api/v2/boards/:id/query?type=board_view
GET    /api/v2/boards/:id/query?type=my_tasks&person=Miguel
GET    /api/v2/boards/:id/query?type=task_detail&task_id=T40
GET    /api/v2/boards/:id/query?type=due_soon
GET    /api/v2/boards/:id/query?type=search&text=SEMA
GET    /api/v2/boards/:id/query?type=history&task_id=T40
```

This maps 1:1 to the 10 MCP tools. The API is a thin HTTP wrapper around the engine.

### Implementation
- Add to NanoClaw's main process (src/index.ts or a new src/api-gateway.ts)
- Import TaskflowEngine, instantiate per request with the board's DB
- Auth: JWT middleware (Phase 1B)
- Part of the TaskFlow skill, not NanoClaw core

---

## Phase 1B: WhatsApp OTP Authentication

Same as the original spec, but simpler now:
- OTP sent via NanoClaw's existing WhatsApp channel
- JWT issued by the API
- User table in taskflow.db
- Session management

**Key change:** Auth lives in the NanoClaw API gateway (Option D), not the Python API. The Python API becomes redundant or serves as a read-only cache.

---

## Phase 1C: Frontend CRUD

With the API bridge in place, the frontend can:

### Task Management (biggest impact)
- **Task detail panel:** Edit title, description, priority, assignee, due date, labels, notes (calls /api/v2/tasks/:tid/update)
- **Drag-and-drop move:** Between columns (calls /api/v2/tasks/:tid/move)
- **Task creation:** Full form with type selector (simple/project/recurring/meeting), not just simple inbox
- **Subtask management:** Add/check/remove subtasks within project tasks
- **Reassignment:** Change assignee from task detail or drag to person

### Board Management
- **Create board:** Name, template, timezone, language (calls engine admin)
- **Board settings:** Edit columns, WIP limits, schedules (uses board_config + board_runtime_config)
- **People management:** Add/remove members, set roles, WIP limits (calls taskflow_admin)

### Views (using engine queries)
- **My Tasks:** Cross-board personal view (query type=my_tasks)
- **Calendar:** Tasks by due_date
- **Reports:** Standup/digest/weekly rendered in browser (query type=report)

---

## Phase 1D: Organization Layer

Lightweight multi-tenancy on top of existing board structure:
- Organizations group boards
- Users belong to organizations
- Board access scoped by org membership
- Invite flow via WhatsApp

This is the ONLY new business logic — everything else bridges existing engine capabilities.

---

## Revised Priority

| Item | Effort | Impact | Why |
|------|--------|--------|-----|
| API Bridge (1A) | Medium | Critical | Unlocks ALL frontend CRUD without duplicating logic |
| Auth (1B) | Medium | Critical | Required for multi-user |
| Task editing UI (1C) | Medium | High | Highest user-visible improvement |
| Drag-and-drop (1C) | Low | High | Natural kanban interaction |
| Board creation UI (1C) | Low | High | Self-service, currently requires SKILL.md wizard |
| Organization layer (1D) | Medium | Medium | Multi-tenancy |
| Landing page | Low | Medium | Growth |

**Start with 1A** — the API bridge. Once engine operations are accessible via REST, everything else flows naturally.

---

## What Does NOT Need to Change

- **taskflow-engine.ts** — already complete, battle-tested via WhatsApp
- **task-scheduler.ts** — standup/digest/review already work
- **CLAUDE.md.template** — WhatsApp agent already handles everything
- **Database schema** — only additions (users, orgs), no changes to existing tables
- **Board provisioning** — SKILL.md wizard continues to work for WhatsApp-first setup

The product expansion is an **additive layer** on top of a working system, not a rewrite.
