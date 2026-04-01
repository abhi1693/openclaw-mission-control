# TaskFlow Current Capabilities — What Already Exists

> **Source:** Direct investigation of NanoClaw codebase on 192.168.2.160

## What's Already Built (and working)

### Task Management (taskflow-engine.ts — 7,816 lines, 10 MCP tools)

**Task types:** simple, project (with subtasks P1.1, P1.2), recurring (daily/weekly/monthly/yearly), inbox (quick capture), meeting (with participants + external invites)

**Columns:** inbox → next_action → in_progress → waiting → review → done

**10 move actions:** start, wait, resume, return, review, approve, reject, conclude, reopen, force_start

**Features already in the engine:**
- Task dependencies (blocked_by field)
- Subtasks / checklists (within project tasks)
- Labels (JSON array on tasks)
- Notes (per task)
- Reminders
- Due dates with overdue tracking
- Task history / audit log (task_history table)
- Archive system (archive table with full snapshots)
- Undo last mutation
- Close approval (requires_close_approval flag)
- WIP limits per person
- Bulk reassignment (transfer_all action)

### Board Hierarchy & Delegation
- Parent/child boards (boards.parent_board_id)
- Cross-board task delegation (child_exec_* fields)
- Rollup status from child to parent
- Hierarchy depth control (hierarchy_level, max_depth)
- Child board registration table

### Scheduled Reports (task-scheduler.ts)
- **Standup** — morning: board view, auto-archives old done tasks
- **Digest** — evening: completed today, due in 48h, blocked tasks
- **Weekly Review** — Friday: completed this week, due next week, stale tasks, per-person stats
- Cron-based scheduling with DST guard
- All three are NanoClaw scheduled tasks that spawn container agents

### People & Contacts
- Board members with roles and WIP limits
- Admin roles (manager, delegate) with permissions matrix
- External contacts for meetings (with DM invite flow)
- Meeting external participants with per-occurrence tracking
- Notification group JIDs per person

### WhatsApp Integration (CLAUDE.md.template — 1,081 lines)
- Natural language command router (no hardcoded commands)
- 5-tier sender identification (name → ID → phone → first-name → single-person)
- Voice message support (pre-transcribed)
- Authorization matrix (Everyone/Assignee/Delegate/Manager)
- WhatsApp-specific formatting (bold, italic, strikethrough, bullets)
- Command synonyms in Portuguese/English/Spanish
- Anti-prompt-injection rules
- Scope guard (task management only, rejects off-topic)

### Board Configuration (board_runtime_config table)
- Language (pt-BR, en-US, es-ES)
- Timezone (IANA)
- Geography (state, city, country)
- Standup/digest/review cron schedules (local + UTC pairs)
- DST synchronization guard
- Attachment settings (enabled, formats, max size)
- Control group routing (where reports go)
- Welcome message flag
- Runner task IDs for each scheduled report

### Database (14 tables in taskflow.db)
boards, board_people, board_admins, board_config, board_runtime_config, board_groups, board_holidays, board_id_counters, board_chat, tasks, task_history, archive, child_board_registrations, external_contacts, meeting_external_participants, attachment_audit_log

---

## What the Dashboard Has (React frontend — 2,221 lines across 6 core files)

**Pages:**
- **Dashboard** (477 lines): Stats cards (total boards, tasks, overdue), bar chart by column, overdue tasks table with sorting, board list with settings panel, task type filter (simple/project/meeting/recurring/inbox), real-time pulse animation on updates
- **BoardDetail** (858 lines): Kanban + List view toggle, priority/assignee filters, search, drag-and-drop columns, task click → detail panel, board chat (Dialog overlay), board config (collapsible, below kanban), review column filter tabs (all/approval/lead/blocked)

**Task Management (already working):**
- **TaskDetailPanel** (269 lines, Radix Dialog slide-over): Edit status (column select), priority, assignee (people dropdown), due date (date input). View description, labels, comments. Add comments. Delete task. Mark done/reopen.
- **TaskCreationDialog** (210 lines, centered Dialog): Title, description, priority, assignee, due date. Creates simple inbox tasks via API.
- **TaskCard** (196 lines): Shows ID, title, assignee, priority badge, due date, overdue label, labels, delegation indicator, type icon (simple/project/meeting/recurring)

**Board Management:**
- **BoardConfigPanel**: Read-only display of language, timezone, WIP limit, standup/digest/review schedules
- **BoardSettingsPanel**: Board detail view from Dashboard, read-only
- **PeoplePanel**: Collapsible, owner first, per-board localStorage, person click filters kanban by assignee, hover lift effect

**Infrastructure:**
- **API Client** (api.ts): Full typed client with request/error handling, WebSocket with auto-reconnect
- **Already supports:** createTask, updateTask, deleteTask, getComments, addComment, listChat, sendChat, searchTasks, overdueTasks, linkedTasks, runnersStatus
- **i18n**: pt-BR + en-US with locale context, date formatting, cron description humanizer
- **Real-time**: WebSocket bridge (taskflow:snapshot, taskflow:updated, chat:new), TanStack Query invalidation on updates
- **Routing**: React Router with Layout wrapper, 2 routes (/ and /boards/:boardId)

**What works end-to-end (backend + frontend):**
- ✅ View boards, tasks, overdue, search
- ✅ Create simple tasks (title, description, priority, assignee, due date)
- ✅ Board chat with agent
- ✅ Filter by priority, assignee, task type, review sub-filter

**Frontend client defined BUT backend endpoints MISSING (broken today):**
- ⚠️ `updateTask` (PATCH) — TaskDetailPanel edits status/priority/assignee/due_date, drag-and-drop calls this — returns 404
- ⚠️ `deleteTask` (DELETE) — delete button in TaskDetailPanel — returns 404
- ⚠️ `getComments` / `addComment` — comments section in TaskDetailPanel — returns 404
- ⚠️ Drag-and-drop between columns — UI is fully wired but calls `updateTask` which fails

**What the frontend CANNOT do (no API or no UI):**
- ❌ Edit task title, description, labels, notes (read-only in detail panel)
- ❌ Create project/recurring/meeting tasks (only simple)
- ❌ Manage subtasks
- ❌ Manage people (add/remove members)
- ❌ Create/edit boards
- ❌ Edit board config (columns, WIP, schedules)
- ❌ My Tasks cross-board view
- ❌ Calendar view
- ❌ Notification center content

---

## What the API Has (main.py — 649 lines)

| Endpoint | Exists |
|----------|--------|
| Health check | ✅ |
| Board list + detail | ✅ |
| Board tasks (with column filter) | ✅ |
| Create simple task | ✅ |
| Overdue tasks | ✅ |
| Task search | ✅ |
| Linked/delegated tasks | ✅ |
| Runner status | ✅ |
| Board chat (GET/POST) | ✅ |
| WebSocket (snapshot + updates + chat:new) | ✅ |

---

## What's MISSING for a Full Product

### Auth & Multi-tenancy
- ❌ No authentication (single bearer token)
- ❌ No user accounts
- ❌ No organizations / multi-tenancy
- ❌ No session management
- ❌ No role-based access control on API

### API CRUD Gaps
- ❌ No board CREATE/UPDATE/DELETE via API (only via WhatsApp/SKILL.md wizard)
- ❌ No task UPDATE via API (move, reassign, edit — only via engine MCP tools)
- ❌ No task DELETE via API
- ❌ No people management via API (add/remove members)
- ❌ No board config UPDATE via API
- ❌ No task comments via API (only task_history read)
- ❌ No file upload/attachment API
- ❌ No recurring task management API
- ❌ No meeting management API

### Frontend Gaps
- ❌ No login page
- ❌ No user profile
- ❌ No organization management
- ❌ No board creation UI
- ❌ No task editing (only view + create simple)
- ❌ No drag-and-drop between columns (move)
- ❌ No subtask management UI
- ❌ No recurring task UI
- ❌ No meeting view
- ❌ No calendar view
- ❌ No my-tasks cross-board view
- ❌ No notification center (bell icon exists but no content)
- ❌ No settings pages
- ❌ No landing/product page
- ❌ No mobile responsive design

### Integration Gaps
- ❌ WhatsApp ↔ Web chat not unified (separate conversations)
- ❌ No push notifications
- ❌ No email notifications
- ❌ No webhook API
- ❌ No external integrations

---

## Key Insight: The Engine Already Does Everything

The `taskflow-engine.ts` (7,816 lines) already supports ALL the task management features: creation, moves, reassignment, dependencies, subtasks, recurring, meetings, delegation, reports, undo, history, archive.

**The gap is NOT in capabilities — it's in the API and frontend.** The engine is only accessible via MCP tools (agent container) and WhatsApp. The web API exposes read-only views + simple task creation. The dashboard is a viewer, not an editor.

**The product expansion is primarily:**
1. Expose engine operations as REST API endpoints
2. Add auth/multi-tenancy layer
3. Build frontend CRUD pages that call those APIs
4. Add landing page + onboarding

The engine doesn't need to change much — it's the API and frontend that need to catch up.
