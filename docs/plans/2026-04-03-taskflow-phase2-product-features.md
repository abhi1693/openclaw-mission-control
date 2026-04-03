# TaskFlow Phase 2 — Product Features

> Engine inventory: 7,827 lines, 10 MCP tools, 44 query types, 25+ actions.
> **Codex validation (2026-04-03):** Not all features are "just SQL wrappers" — engine has JS aggregation, BFS cycle detection, embedding search. PB must port logic, not just SQL.

## Validated Reality (Codex gpt-5.4 audit on live DB)

| Feature | Codex Verdict | Notes |
|---------|--------------|-------|
| Engine queries | **44 types** (not 50+) | Still rich |
| Same DB (engine + API) | ✅ REAL | Both hit taskflow.db |
| `/tasks/search` | **ID-only** — doesn't search title/description | Needs real implementation |
| `/tasks/overdue` | ✅ REAL — 29 rows live | Works |
| Dependencies | **Code exists, 0 live data** | Can't validate from prod |
| Meeting minutes | ✅ REAL — 16 meetings, 2 with notes | Works but limited |
| File attachments | **STUB** — 0 rows, no logic | Needs full build |
| Recurring tasks | **3 tasks, inconsistent data** | Fragile, needs normalization |
| Board hierarchy | ✅ REAL — 17 registrations, 149 delegated tasks | One-directional only |

## Feature Matrix: Engine Has It → Web UI Needs It

### Phase 2A: Search, Filters & Activity Feed (PF + PB)

**Engine queries available:** `search`, `overdue`, `due_today`, `due_this_week`, `next_7_days`, `urgent`, `high_priority`, `by_label`, `changes_today`, `changes_this_week`, `completed_today`, `completed_this_week`

**Backend (PB):**
- `GET /boards/{board_id}/tasks/filter?query=<type>` — expose engine query types via API
- `GET /boards/{board_id}/activity` — changes_today/changes_since feed
- API already has `/tasks/search` and `/tasks/overdue` ✅

**Frontend (PF):**
- Search bar with full-text search across tasks
- Filter sidebar: by assignee, priority, due date range, labels, status
- "Activity Feed" page (currently "Coming soon" in sidebar)
- Filter persistence via URL params

### Phase 2B: Person Views & Statistics (PF + PB)

**Engine queries:** `person_tasks`, `person_waiting`, `person_completed`, `person_review`, `person_statistics`, `statistics`, `month_statistics`

**Backend (PB):**
- `GET /boards/{board_id}/people/{person_id}/tasks` — person task view
- `GET /boards/{board_id}/people/{person_id}/stats` — person statistics
- `GET /boards/{board_id}/statistics` — board-level statistics with time ranges

**Frontend (PF):**
- Click person in People panel → shows their tasks by status
- Person stats card (completion rate, overdue count, WIP)
- Board statistics dashboard (velocity, completion trends, overdue trends)
- Monthly statistics view

### Phase 2C: Board Settings & Management (PF + PB)

**Engine actions:** `set_wip_limit`, `manage_holidays`, `register_person`, `remove_person`, `add_manager`, `add_delegate`

**Backend (PB):**
- `PATCH /boards/{board_id}/config` — update WIP limits, columns, timezone, language
- `POST /boards/{board_id}/people` — add person to board
- `DELETE /boards/{board_id}/people/{person_id}` — remove person
- `PATCH /boards/{board_id}/people/{person_id}` — update role, WIP limit
- `GET/POST /boards/{board_id}/holidays` — manage holidays

**Frontend (PF):**
- Board Settings page (from gear icon) — editable WIP limits, timezone, language
- People panel → add/remove/edit roles (currently read-only)
- Holiday calendar management
- Column configuration (order, visibility, names)

### Phase 2D: Task Workflow Actions (PF + PB)

**Engine actions:** `start`, `wait`, `resume`, `return`, `review`, `approve`, `reject`, `conclude`, `reopen`, `force_start`

**Backend (PB):**
- `POST /boards/{board_id}/tasks/{task_id}/action` — execute workflow action
- Returns new state + any validation errors (WIP limit, approval required, etc.)

**Frontend (PF):**
- Right-click or button menu on task cards with available actions
- Actions change based on current state (inbox → start, in_progress → wait/review, etc.)
- Approval UI for tasks requiring close approval
- Undo last action button

### Phase 2E: Dependencies & Reminders (PF + PB)

**Engine actions:** `add_dep`, `remove_dep`, `add_reminder`, `remove_reminder`

**Backend (PB):**
- `POST /boards/{board_id}/tasks/{task_id}/dependencies` — add/remove dependency
- `POST /boards/{board_id}/tasks/{task_id}/reminders` — add/remove reminder

**Frontend (PF):**
- Dependency picker in TaskDetailPanel
- Visual dependency lines on kanban (blocked indicator already exists)
- Reminder date/time picker
- "Blocked by" badge with link to blocking task

### Phase 2F: Recurring Tasks (PF + PB)

**Engine support:** `recurrence: daily/weekly/monthly/yearly`, `max_cycles`, `recurrence_end_date`, cycle advancement

**Backend (PB):**
- `POST /boards/{board_id}/tasks` already supports recurring type ✅
- Need: `PATCH` to modify recurrence rules
- Need: `GET /boards/{board_id}/tasks/{task_id}/recurrence` — show cycle history

**Frontend (PF):**
- Recurrence picker in task creation/edit (daily/weekly/monthly/yearly)
- Max cycles and end date inputs
- Cycle history view
- "Next occurrence" preview

### Phase 2G: Meeting Management (PF + PB)

**Engine support:** meeting type, scheduled_at, participants, external invites, minutes processing, access windows

**Backend (PB):**
- `POST /boards/{board_id}/tasks` with `type: "meeting"` ✅
- `GET /boards/{board_id}/meetings` — upcoming meetings (engine has `upcoming_meetings` query)
- `POST /boards/{board_id}/tasks/{task_id}/participants` — manage participants
- `POST /boards/{board_id}/tasks/{task_id}/minutes` — process meeting minutes

**Frontend (PF):**
- Meeting creation with date/time picker and participant selector
- Agenda view (engine has `agenda`, `agenda_week` queries)
- Meeting detail page with minutes and action items
- External participant invite flow

### Phase 2H: Reports & Export (PF + PB)

**Engine support:** `standup`, `digest`, `weekly` report types, `summary` query

**Backend (PB):**
- `GET /boards/{board_id}/reports/{type}` — generate standup/digest/weekly report
- `GET /boards/{board_id}/export?format=csv` — export tasks

**Frontend (PF):**
- Reports page with standup, digest, weekly views
- Export button (CSV download)
- Printable report view

### Phase 2I: File Attachments (PB + PF)

**Engine support:** attachment config per board, audit log

**Backend (PB):**
- `POST /boards/{board_id}/tasks/{task_id}/attachments` — upload file
- `GET /boards/{board_id}/tasks/{task_id}/attachments` — list files
- Storage: local filesystem initially, S3 in Phase 3

**Frontend (PF):**
- Drag-and-drop file upload in TaskDetailPanel and comments
- File preview (images, PDFs)
- Attachment list with download links

---

## Priority Ordering

**Ship first (highest user impact, engine support exists):**
1. **2A** — Search & Filters + Activity Feed
2. **2B** — Person Views & Statistics
3. **2C** — Board Settings (editable)
4. **2D** — Task Workflow Actions

**Ship second (important but more complex):**
5. **2E** — Dependencies & Reminders
6. **2F** — Recurring Tasks
7. **2G** — Meeting Management

**Ship last (needs infrastructure):**
8. **2H** — Reports & Export
9. **2I** — File Attachments

## Assignment

- **PB**: All backend endpoints (extend main.py, wrap engine queries/actions)
- **PF**: All frontend pages and components
- **Architect**: Review API contracts before implementation
- **QA-E2E**: Validate each sub-phase on live build
- **QA-Unit**: Validate backend endpoints

## Key Principles

1. The engine (7,827 lines) has rich logic but it's **NOT thin SQL wrappers** — it has JS aggregation, JSON parsing, BFS cycle detection, embedding search. PB must port the logic, not just copy SQL.
2. `/tasks/search` is **ID-only** today — needs real full-text implementation before search UI is built.
3. **Dependencies and attachments have 0 live data** — build and test from scratch, can't validate from prod.
4. **Recurring task data model is inconsistent** — some use string enum, some use JSON object. Normalize before building UI.
5. The Architect should review API contracts BEFORE PB implements — use `/codex:adversarial-review` to challenge design.

## Codex Validation Date
2026-04-03 — validated against live DB on .63 and engine source on .160.
