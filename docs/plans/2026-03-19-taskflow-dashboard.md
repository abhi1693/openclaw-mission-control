# TaskFlow Dashboard — Implementation Plan

> **Standalone project** (`taskflow-api/` + `taskflow-dashboard/`). 
> **Methodology:** TDD. **Multilingual:** pt-BR / en-US.

**Goal:** Dashboard for the TaskFlow WhatsApp GTD system on NanoClaw.

**Stack:** API: FastAPI + SQLite. Frontend: Pure TypeScript + React 19 SPA (no Next.js). WebSocket for real-time.

**Full spec:** `docs/plans/2026-03-19-taskflow-dashboard.full.md` — contains all code samples, test fixtures, Tailwind CSS classes, wireframes, and TypeScript interfaces. Reference by section heading:

| Need | Section in full spec |
|---|---|
| Tailwind classes, sidebar collapse, mobile drawer, card styling | `## UI Reference` |
| SQL CREATE TABLE statements | `### Key Schemas` |
| Production board list + activity stats | `### Current Boards` + `### Real-World Usage Patterns` |
| API response JSON examples | `### API Contract` |
| TypeScript interfaces (Board, Task, Person, etc.) | `### Step 2: Write TypeScript types` |
| i18n Messages interface + locale mappings | `### Step 3: Write i18n module` |
| API test fixtures + conftest.py | `### TDD Implementation` |
| Frontend test examples | `### TDD Steps` (Tasks 3 & 4) |
| WebSocket change detection SQL + reconnection code | `#### WS /ws` + `### Step 4: Create API client` |
| systemd service file | `### Systemd Service` |

---

## Target Machine

- `nanoclaw@192.168.2.63` — user is `nanoclaw`, **NOT root** (cannot write to `/root/`)
- Deploy path: `/home/nanoclaw/taskflow-api/`
- DB: `/home/nanoclaw/nanoclaw/data/taskflow/taskflow.db`
- Python 3.12, **no pip** → first-time: `sudo apt install python3-pip`
- API port: `8100`, frontend port: `3001`

---

## UI Reference

Screenshots: `docs/pics/MC App Kanban.png` and `MC App Kanban 2.png`. Full Tailwind specs → `## UI Reference` in full spec.

**Key decisions:**
- Two-row header: top bar (brand/user) + page header (title/actions: Board/List toggle, `+` button, bell with badge, columns, monitor, sparkles, gear)
- Sidebar: `w-64` expanded / `w-16` collapsed (icons + Radix Tooltip, state in `localStorage:taskflow-sidebar-collapsed`) / mobile: `md:hidden` drawer overlay with `bg-black/50` backdrop
- Active nav: `bg-blue-100 text-blue-800` (light blue fill)
- Board/List toggle: pill-shaped `rounded-full`, `bg-blue-600` active
- Kanban: `w-[280-300px]` columns, `rounded-xl`, colored dot + plain text count
- Task cards: `rounded-xl`, state tinting (amber=approval, blue=lead review, gray=blocked)
- Review sub-filters: dark pill active, outlined inactive. Derive from `waiting_for`/`blocked_by` fields
- People panel: `User` Lucide icon avatars (not initials), `bg-emerald-500` status dot bottom-right
- Loading: skeleton pulses. Error: red alert + retry. Empty: icon + message.

---

## Data Model (production 2026-03-20)

**11 boards** (dynamic — auto-provision on person registration). 125+ tasks. Composite PK `(board_id, id)`.

**Critical fields on `tasks` table:**

| Field | Notes |
|---|---|
| `id` | Mixed: `T-001`, `T1`, `M1`, `P15.1`. NOT globally unique. |
| `"column"` | **Reserved word** — always quote in SQL. Values: inbox/next_action/in_progress/waiting/review/done |
| `priority` | `urgente` / `alta` / `normal` / `baixa` / NULL. No `media`. |
| `due_date` | ISO 8601 **datetime** (`2026-03-16T02:59:00Z`), NOT date-only |
| `parent_task_id` | Links subtask to parent (e.g., `P15.1` → `P15`) |
| `scheduled_at` | Meeting datetime (ISO 8601) |
| `child_exec_board_id` | Delegated to child board (53 tasks in prod). Key cross-board mechanism. |
| `child_exec_person_id` | Person on the child board |
| `child_exec_rollup_status` | Status from child board |
| `waiting_for` | Who/what blocks — used for review sub-filter derivation |
| `labels` | JSON string in DB (`'["urgente"]'`). API parses → returns `string[]`. |

**Overdue rule:** `date(due_date) < date('now','localtime')` AND `column != 'done'`. Server timezone is `America/Fortaleza` (UTC-3). Display dates as locale-formatted date-only (`dd/MM/yyyy` pt-BR, `MM/dd/yyyy` en-US).

**Runners:** Standup `0 8 * * 1-5`, Digest `0 18 * * 1-5`, Review `0 11 * * 5`. 159/159 successful this week.

**Cross-board:** `child_exec_*` is the mechanism (53 tasks). `linked_parent_*` is unused (0 rows). TEC: 1 local task + 18 linked SEC tasks.

Full schemas, board list, activity stats → full spec `### Key Schemas` + `### Current Boards` + `### Real-World Usage Patterns`.

---

## API (Task 1) — `taskflow-api/`

FastAPI on NanoClaw. SQLite. Bearer token auth (`TASKFLOW_API_TOKEN`). CORS from `TASKFLOW_CORS_ORIGINS`. All queries parameterized (`?`).

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /health` | No | `{"status":"ok"}` |
| `GET /stats` | Yes | `{total_boards, total_tasks, tasks_by_column, tasks_overdue, boards[]}` |
| `GET /boards` | Yes | `Board[]` |
| `GET /boards/{id}` | Yes | `BoardDetail` (+ config, people, tasks_by_column) |
| `GET /boards/{id}/tasks?column=` | Yes | `Task[]`. Valid columns: inbox/next_action/in_progress/waiting/review/done. Invalid → 400 |
| `GET /boards/{id}/linked-tasks` | Yes | `Task[]` where `child_exec_board_id IS NOT NULL` |
| `GET /tasks/overdue` | Yes | `Task[]` sorted by due_date ASC |
| `GET /tasks/search?q=T79` | Yes | `Task[]` matching ID (case-insensitive, limit 20) |
| `GET /runners/status` | Yes | `[{board_id, standup_last_run, digest_last_run, review_last_run, *_cron}]` |
| `WS /ws?token=` | Token in query | `taskflow:snapshot` on connect, `taskflow:updated` on change |

**Errors:** `{"detail":"..."}` with 400/401/404/503.
**Labels:** API parses JSON string → returns `string[]`. Parse failure → `[]`.
**WebSocket change detection:** polls every 5s: `max(updated_at)||count(*)` from tasks + `count(*)` from boards, board_people, board_config.
**Security note:** Token visible in frontend bundle — acceptable for private LAN read-only dashboard.

**Tests:** 17 cases (auth, stats, boards, tasks, overdue, column filter, labels, WS auth, WS snapshot). Fixture DB in `conftest.py` with `importlib.reload` for env isolation. Full test code → `### TDD Implementation` in full spec.

**Deploy:** `.env.example` + systemd service (`User=nanoclaw`). Full service file → `### Systemd Service` in full spec.

---

## Frontend (Tasks 2-4) — `taskflow-dashboard/`

Pure React 19 SPA. React Router (`/` + `/boards/:boardId`). TanStack Query + Table. Recharts. Radix UI. Tailwind CSS 3. Lucide icons. Bundler: developer's choice.

### Task 2: Setup + API Client + i18n

- **Types:** `Board`, `Task`, `Person`, `BoardDetail`, `Stats`, `WsEvent` interfaces matching API. Full definitions → `### Step 2` in full spec.
- **API client:** typed `fetch` wrapper + `connectWebSocket()` with exponential backoff reconnection (1s → 30s max). Env vars: `TASKFLOW_API_URL`, `TASKFLOW_API_TOKEN` (inject via bundler mechanism).
- **i18n:** `LocaleContext` (React Context), default `pt-BR`, persist in `localStorage:taskflow-locale`. `Messages` interface with: page titles, table headers, empty states, date formats, `columns` Record, `priorities` Record. Full Messages definition → `### Step 3` in full spec.
- **Routing:** React Router: `/` → Dashboard, `/boards/:boardId` → BoardDetail.

### Task 3: Overview Dashboard

- Stats cards (4-col grid): boards, tasks, overdue, in-progress
- Board hierarchy tree (clickable, shows local + linked task counts)
- Column chart (Recharts bar)
- Overdue table (TanStack Table, localized headers)
- Global search bar (calls `/tasks/search`)
- Runner status per board (last run times, flag stale boards)
- `useTaskFlowWebSocket` hook: invalidate queries on `taskflow:updated`
- Skeleton loading, error alert with retry, empty states

### Task 4: Board Detail

- **Kanban** (Board toggle): 6 GTD columns with task cards
- **List** (List toggle): flat TanStack Table, sortable
- **People panel** (leftmost): icon avatars, roles, status dots
- **Board config** (collapsible): language, timezone, WIP, cron schedules
- **Review sub-filters:** All / Approval needed / Lead review / Blocked
  - Derive: `waiting_for` contains "aprovação"/"approval" → Approval needed; "lead"/"gestor" → Lead review; `blocked_by` non-empty → Blocked
- **Cards:** ID (`{board_code}-{id}`), title, priority badge, labels, assignee (or gray "Unassigned"), overdue date (red), meeting `Calendar` icon, linked-board badge

Frontend test examples → `### TDD Steps` (Tasks 3 & 4) in full spec.

---

## Deploy (Task 5)

**API:**
```bash
scp -r taskflow-api/ nanoclaw@192.168.2.63:/home/nanoclaw/taskflow-api/
ssh nanoclaw@192.168.2.63
cd /home/nanoclaw/taskflow-api
sudo apt install -y python3-pip  # first time only
pip install -r requirements.txt
cp .env.example .env  # set TASKFLOW_API_TOKEN + TASKFLOW_CORS_ORIGINS
sudo cp taskflow-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now taskflow-api
curl http://localhost:8100/health  # verify: {"status":"ok"}
```

**Frontend:**
```bash
cd taskflow-dashboard
cp .env.example .env  # set TASKFLOW_API_URL + TASKFLOW_API_TOKEN
npm run build
npx serve dist -l 3001  # or caddy/nginx
```

**Verify:** dashboard loads, click board → Kanban renders, toggle locale, check DevTools WS connected, unauthorized → 401.

---

## Data Display Rules

- **Task IDs:** `{board_code}-{id}`. If `short_code` is null (level-3 boards), use `group_folder`.
- **Meetings** (`type=meeting`): show `Calendar` Lucide icon, display `scheduled_at` datetime.
- **Subtasks** (`parent_task_id` set): show in Kanban normally. Do NOT filter out.
- **Linked tasks:** show `child_exec_board_id` as a badge referencing the child board.
- **Priority null:** no badge. **Labels empty:** no pills. **Role:** display raw DB text as-is.
- **Unassigned:** gray `User` icon + "Unassigned" in `text-slate-400`.
- **User content** (titles, labels, notes): never translated — displayed as-is.

---

## Out of Scope (v2)

Write operations, runner management, meeting UI, task delegation, attachment viewer, board creation wizard, Board Chat panel, TLS termination, per-board timezone in overdue, pagination.
