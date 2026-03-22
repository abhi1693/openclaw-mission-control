# TaskFlow Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every implementation step.
>
> **IMPORTANT:** This is a **standalone project** — two separate directories (`taskflow-api/` and `taskflow-dashboard/`), NOT part of the existing Mission Control Next.js codebase. Do not modify the MC frontend or backend.

**Goal:** Build a dashboard to monitor the TaskFlow WhatsApp GTD app running on NanoClaw, giving the user visibility into boards, tasks, people, and stats across the 3-level organizational hierarchy. Multilingual (pt-BR / en-US).

**Architecture:** Two independent services. A FastAPI server runs on the NanoClaw machine (`nanoclaw@192.168.2.63`), reading the TaskFlow SQLite database directly and serving REST + WebSocket. A standalone TypeScript/React SPA connects to this API directly. No proxy, no middleware.

**Tech Stack:**
- API: Python 3.11+ / FastAPI / SQLite 
- Frontend: **Pure TypeScript + React 19** — no Next.js, no SSR, no meta-framework. Single-page application with client-side routing only.
- UI libraries: React Router, TanStack Query, TanStack Table, Recharts, Radix UI, Tailwind CSS 3, Lucide icons
- Real-time: WebSocket
- Bundler/tooling: developer's choice

**Methodology:** TDD — write failing tests first, then implement the minimal code to make them pass, then refactor. Every task below follows this cycle.

---

## Target Machine

- **NanoClaw:** `nanoclaw@192.168.2.63` (SSH access, Python 3.12, **no pip installed** — install with `sudo apt install python3-pip`)
- **Home directory:** `/home/nanoclaw/` (NOT `/root/` — the `nanoclaw` user cannot write to `/root/`)
- **TaskFlow DB:** `/home/nanoclaw/nanoclaw/data/taskflow/taskflow.db`
- **API deployment path:** `/home/nanoclaw/taskflow-api/`
- **API port:** `8100`
- **Frontend:** Served as a static SPA on port `3000` (port 3001 is used by NanoClaw core).

**First-time setup on the machine:**
```bash
sudo apt update && sudo apt install -y python3-pip
```

---

## Design Foundation

**Visual Thesis:** A calm, professional operations dashboard — think Linear meets government. Muted slate surfaces with precise data hierarchy, not flashy SaaS. The interface should feel like a control room: information-dense but never cluttered.

**Content Plan:** Two pages, each with one job:
- **Dashboard (`/`):** Status overview (4 stat cards) → board hierarchy tree (clickable, shows task counts) → column distribution chart (Recharts bar) → overdue alert table (TanStack Table). Narrative: "here's the big picture, here's the structure, here's the distribution, here's what needs attention."
- **Board Detail (`/boards/:id`):** People panel (left) → Kanban columns with task cards (center) → board config (collapsible). Narrative: "who's involved, what's the work, how's the board configured."

**Interaction Thesis:**
1. **Staggered entrance** — stat cards and board tree items appear with a subtle cascade on page load (CSS `animation-delay` per item, ~50ms stagger)
2. **View transitions** — Board/List toggle animates cards between layouts (fade + slide, ~200ms)
3. **Live pulse** — when WebSocket delivers `taskflow:updated`, a subtle blue pulse ripples through affected stat cards before data refreshes

**Typography:**
- Display/headlines: `Space Grotesk` (geometric, technical) — `font-display: swap`, loaded via Google Fonts
- Body text: `Inter` — acceptable for data dashboards (this is NOT a landing page)
- Monospace (task IDs, board codes): `JetBrains Mono`
- Scale: `text-3xl font-bold` page titles, `text-xl font-semibold` section headers, `text-sm` table body, `text-xs text-slate-500` metadata/timestamps
- Weight contrast: titles at `700`, headers at `600`, body at `400`, metadata at `400` in muted color

## UI Reference

Design based on Mission Control Kanban screenshots (`docs/pics/MC App Kanban.png` and `MC App Kanban 2.png`). Follow these specs exactly.

### Color Palette

Primarily slate/neutral with selective accent colors.

| Role | Color |
|---|---|
| Page background | `bg-slate-50` |
| Cards/panels | `bg-white border border-slate-100` |
| Sidebar background | `bg-slate-50` (slightly cool/off-white, not pure white) |
| Primary text | `text-slate-900` |
| Secondary text | `text-slate-500` |
| Muted text | `text-slate-400` |
| Active nav item | `bg-blue-100 text-blue-800 font-medium` (light blue fill, NOT dark) |
| Interactive hover | `hover:bg-slate-50` |
| Accent (action buttons) | `bg-blue-600 text-white` |
| Urgent badge | `bg-rose-200 text-rose-800` |
| High badge | `bg-rose-100 text-rose-700` |
| Medium/Normal badge | `bg-amber-100 text-amber-700` |
| Low badge | `bg-blue-100 text-blue-700` |
| Approval needed accent | `border-l-3 border-amber-400` + `bg-amber-50` tint |
| Lead review accent | `border-l-3 border-blue-400` + `bg-blue-50` tint |
| Success/status dot | `bg-emerald-500` |
| Error | `bg-red-50 border-red-200 text-red-800` |

### Global Layout (Two-Row Header)

The header is **two rows**, not one. The top bar has branding/user, the page header row below has title/actions.

```
┌─────────────────────────────────────────────────────────────┐
│ [OC] OPENCLAW        [Personal ▼]        [Abhimanyu ○]     │  ← top bar
│      Mission Control                      Operator          │
├───────────┬─────────────────────────────────────────────────┤
│NAVIGATION │  Misson Control App      [Board][List] [+][🔔]…│  ← page header
│           │  Keep tasks moving...                           │
│ OVERVIEW  │                                                 │
│  Dashboard│  ┌─Agents─┐ ┌─Inbox─┐ ┌─In Prog┐ ┌─Review─┐  │
│  Live feed│  │        │ │       │ │        │ │        │  │
│           │  │ items  │ │ cards │ │ cards  │ │ cards  │  │
│ BOARDS    │  │        │ │       │ │        │ │        │  │
│  Boards ← │  └────────┘ └───────┘ └────────┘ └────────┘  │
│  Tags     │              main content area                  │
│  Approvals│                                                 │
│  ...      │                                                 │
└───────────┴─────────────────────────────────────────────────┘
```

- **Top bar** (`h-14`, `bg-white`, `border-b border-slate-200`, `px-4 flex items-center justify-between`):
  - Left: Hamburger button (mobile only, `md:hidden`) + App icon (`w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center text-xs font-bold`) + "TASKFLOW" `text-sm font-bold tracking-widest text-slate-800 ml-2` + "Dashboard" subtitle `text-[10px] text-slate-400`
  - Center: Workspace/org selector dropdown (optional v1)
  - Right: Locale toggle + user avatar (`w-8 h-8 rounded-full`) + name/role text

- **Left sidebar** — desktop: `hidden md:flex w-64 bg-slate-50 border-r border-slate-200 flex-col` / mobile: drawer overlay:
  - Top label: `text-[10px] font-bold tracking-widest text-slate-400 uppercase px-4 pt-4 pb-3` ("NAVIGATION")
  - Section headers: `text-[11px] font-semibold tracking-wider text-slate-400 uppercase px-4 pt-5 pb-2` ("OVERVIEW", "BOARDS", "ADMINISTRATION")
  - Nav items: `mx-2 px-3 py-2 text-sm text-slate-600 hover:bg-white rounded-lg flex items-center gap-3` with 16px Lucide icon (`w-4 h-4`)
  - Active item: `bg-blue-100 text-blue-800 font-medium rounded-lg` (light blue fill with blue text — matching screenshot)
  - Sections:
    - "OVERVIEW": Dashboard (`LayoutGrid`), Live feed (`Activity`)
    - "BOARDS": dynamic list from `/boards`. Each: `short_code` (or `group_folder` fallback) + task count badge (`text-[10px] bg-slate-100 text-slate-600 rounded-full px-1.5`). Icon: `Folder`.

- **Page header row** (inside main content, `flex items-center justify-between mb-6`):
  - Left: title `text-2xl font-semibold text-slate-900` + subtitle `text-sm text-slate-500 mt-1`
  - Right: `flex items-center gap-3`
    1. **Board/List toggle** (see section below)
    2. **Add button**: `w-9 h-9 rounded-full bg-blue-600 text-white flex items-center justify-center hover:bg-blue-700` — `Plus` Lucide icon `w-5 h-5`
    3. **Notifications bell**: `relative w-9 h-9 rounded-full bg-slate-100 flex items-center justify-center hover:bg-slate-200` — `Bell` Lucide icon `w-5 h-5 text-slate-600`. Badge: `absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-emerald-500 text-white text-[9px] font-bold flex items-center justify-center` (shows count like "1")
    4. **Columns view**: `w-9 h-9 rounded-full bg-slate-100 flex items-center justify-center hover:bg-slate-200` — `Columns3` icon `w-5 h-5 text-slate-600`
    5. **Monitor**: same style — `Monitor` icon
    6. **AI/Sparkles**: same style — `Sparkles` icon
    7. **Settings**: same style — `Settings` (gear) icon

### Sidebar Collapse (Desktop)

The sidebar has two states: **expanded** (`w-64`) and **collapsed** (`w-16`, icons only). The user toggles between them.

- **Toggle trigger**: `ChevronsLeft` Lucide icon button at the bottom of the sidebar (expanded) / `ChevronsRight` (collapsed). Styled: `mx-auto mb-4 w-8 h-8 rounded-lg hover:bg-white flex items-center justify-center text-slate-400 hover:text-slate-600`
- **State**: stored in `localStorage` key `taskflow-sidebar-collapsed`. Managed by a `useSidebarCollapsed()` hook returning `[collapsed, toggleCollapsed]`.
- **Transition**: `transition-[width] duration-200 ease-in-out` on the sidebar container

**Expanded state** (`w-64`):
- Full layout as described above: section headers + icon + label + badge

**Collapsed state** (`w-16`):
- Section headers hidden
- Nav items: centered icon only (`w-10 h-10 mx-auto rounded-lg flex items-center justify-center hover:bg-white`). Active: `bg-blue-100 text-blue-800`
- Board list: show only the first letter of `short_code` as a `w-8 h-8 rounded-lg bg-slate-100 text-slate-600 text-xs font-bold flex items-center justify-center` chip. Tooltip on hover showing full board name + task count (use Radix `Tooltip`)
- App brand: icon only (hide text)
- On hover over collapsed sidebar: show Radix `Tooltip` with the nav item label (e.g., "Dashboard", "SEC — 82 tasks")

**Main content** adjusts: `ml-64` (expanded) → `ml-16` (collapsed), with matching `transition-[margin] duration-200`

### Mobile Sidebar (Drawer)

On mobile (`md:hidden`), the sidebar is hidden entirely and replaced by a drawer overlay.

- **Trigger**: Hamburger button (`Menu` Lucide icon) in the top bar left side, visible only on `md:hidden`
- **Overlay**: `fixed inset-0 z-40 bg-black/50 transition-opacity duration-200` — clicking it closes the drawer
- **Drawer panel**: `fixed inset-y-0 left-0 z-50 w-64 bg-slate-50 shadow-xl transform transition-transform duration-200`
  - Open: `translate-x-0`
  - Closed: `-translate-x-full`
- **Close button**: `X` Lucide icon at top-right of drawer, `absolute top-4 right-4 text-slate-400 hover:text-slate-600`
- **Content**: Same as expanded sidebar (full labels, not collapsed)
- Use Radix `Dialog` or React state + portal for the overlay

### Board/List Toggle

- Pill-shaped segmented control: `inline-flex rounded-full border border-slate-200 overflow-hidden`
- Active segment: `bg-blue-600 text-white px-4 py-1.5 text-sm font-medium rounded-full` (dark blue/navy fill)
- Inactive segment: `bg-white text-slate-600 px-4 py-1.5 text-sm font-medium hover:bg-slate-50`
- Board = Kanban view, List = flat TanStack Table of same tasks

### Kanban Board

- Horizontal scroll: `flex gap-4 overflow-x-auto pb-4`
- Each column: `w-[280px] min-w-[280px] md:w-[300px] md:min-w-[300px] flex-shrink-0`
  - **Column container**: `bg-white rounded-xl border border-slate-100`
  - **Header** (`px-4 py-3 flex items-center justify-between border-b border-slate-50`):
    - Left: colored status dot (`w-2.5 h-2.5 rounded-full`) + column title `text-sm font-semibold text-slate-700 ml-2`
    - Right: count — plain colored text `text-sm font-semibold` using the column's accent color (inbox → `text-gray-500`, in_progress → `text-yellow-600`, review → `text-purple-600`, done → `text-green-600`). No background chip — just the number.
  - **Card list**: `p-2 space-y-2 overflow-y-auto max-h-[calc(100vh-220px)]`

### Review Column Sub-Filters

The Review column has pill-style filter tabs below the header:

- Container: `flex flex-wrap gap-1.5 px-3 py-2`
- Each tab: `text-[11px] font-medium rounded-full px-2.5 py-1 cursor-pointer transition-colors`
- Active tab: `bg-slate-900 text-white`
- Inactive tab: `bg-white text-slate-500 border border-slate-200 hover:bg-slate-50`
- Tabs (localized): All · {count}, Approval needed · {count}, Lead review · {count}, Blocked · {count}
- Filtering: client-side filter on the review tasks by status subtype (derive from task state — if `waiting_for` contains "aprovação"/"approval" → Approval needed, if `waiting_for` contains "lead"/"gestor" → Lead review, if `blocked_by` is non-empty → Blocked)

### Task Cards

- Container: `bg-white rounded-xl border border-slate-100 shadow-sm p-3.5 hover:shadow-md transition-shadow`
- **State tinting** (review column cards only):
  - Approval needed: `bg-amber-50 border-l-3 border-amber-400` (amber left rail + amber tint)
  - Waiting for lead review: `bg-blue-50 border-l-3 border-blue-400` (blue left rail + blue tint)
  - Blocked: `bg-slate-50 border-l-3 border-slate-400` (gray left rail)
- **Top row**: `flex items-start justify-between gap-2`
  - Title: `text-sm font-medium text-slate-800 line-clamp-2 flex-1`
  - Priority badge (right): `text-[10px] font-bold uppercase tracking-wide rounded-full px-2.5 py-0.5 flex-shrink-0`
    - `urgente`: `bg-rose-100 text-rose-700` — shows "URGENTE" / "URGENT"
    - `alta`: `bg-rose-50 text-rose-600` — shows "ALTA" / "HIGH"
    - `normal`: `bg-amber-100 text-amber-700` — shows "NORMAL"
    - `baixa`: `bg-blue-100 text-blue-700` — shows "BAIXA" / "LOW"
    - `null`: no badge
- **Labels** (below title, `mt-2`): `inline-flex items-center text-[10px] font-medium rounded-full px-2 py-0.5 bg-white border border-slate-200` with colored dot (`w-1.5 h-1.5 rounded-full inline-block mr-1`). Label colors: rotate through emerald, blue, red, purple, amber.
- **Status indicator** (if applicable): `text-[10px] font-semibold uppercase tracking-wide mt-2` with colored dot:
  - `● APPROVAL NEEDED · 1` → amber/orange dot + `text-amber-600`
  - `● WAITING FOR LEAD REVIEW` → blue/purple dot + `text-blue-600`
  - `● BLOCKED` → gray dot + `text-slate-500`
- **Assignee** (bottom, `mt-2 pt-2 border-t border-slate-50`): `text-xs text-slate-500 flex items-center gap-1.5` with `User` Lucide icon (`w-3.5 h-3.5 text-slate-400`). When unassigned: show `text-xs text-slate-400` "Unassigned" with gray `User` icon
- **Overdue date**: `text-[11px] text-red-600 font-medium` next to assignee
- **Meeting icon**: if `type === 'meeting'`, show `Calendar` Lucide icon (`w-3.5 h-3.5 text-indigo-400`) next to task ID

### People Panel (leftmost column in board detail)

- Container: `w-56 min-w-[224px] flex-shrink-0 bg-white rounded-xl border border-slate-100 p-4 self-start`
- Header: `flex justify-between items-center mb-4`
  - Title: `text-xs font-bold tracking-wider text-slate-500 uppercase` ("EQUIPE" / "PEOPLE") + right-aligned "Add" text link `text-xs text-blue-600`
  - Count: `text-xs text-slate-400` below title (e.g., "4 total")
- Each person: `py-2.5 flex items-center gap-3`
  - Avatar: `relative w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center` with `User` Lucide icon (`w-4 h-4 text-blue-500`) — icon-based, NOT initials
  - Status dot: `absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-emerald-500 border-2 border-white` (overlapping avatar bottom-right)
  - Info: `flex flex-col`
    - Name: `text-sm font-medium text-slate-800`
    - Role: `text-[11px] text-emerald-600 leading-tight` (with green dot prefix `● ` for active status). Display raw DB `role` value.

### Stats Cards (Dashboard Overview)

- Grid: `grid grid-cols-2 md:grid-cols-4 gap-4`
- Each card: `bg-white rounded-xl border border-slate-100 shadow-sm p-5`
  - Label: `text-xs font-medium text-slate-400 uppercase tracking-wide`
  - Value: `text-3xl font-bold text-slate-900 mt-2`
  - Icon: `absolute top-4 right-4` — Lucide icon in `text-slate-200 w-5 h-5`

### States

- **Loading**: Skeleton pulses `bg-slate-200 animate-pulse rounded-xl` matching card/column shapes. Use 3 skeleton cards per column.
- **Error**: `bg-red-50 border border-red-200 rounded-xl p-5` with `text-red-800` message + retry button `bg-red-100 hover:bg-red-200 text-red-700 text-sm font-medium px-3 py-1.5 rounded-lg`
- **Empty column**: Centered — Lucide icon `w-10 h-10 text-slate-200` + message `text-sm text-slate-400 mt-2`

---

## Multilingual Support

TaskFlow stores Portuguese values for priorities. The dashboard supports pt-BR and en-US via a locale toggle. The API returns raw DB values; the frontend maps them.

**Locale state:** React Context (`LocaleContext`). Default: `pt-BR`. Persisted in `localStorage` key `taskflow-locale`. Provided via `useLocale()` hook returning `[locale, setLocale]`.

**Scope of i18n (frontend only):**

| Category | Examples |
|---|---|
| Column names | `next_action` → "Próxima Ação" / "Next Action" |
| Priority labels | `alta` → "Alta" / "High" |
| Page titles | "Painel TaskFlow" / "TaskFlow Dashboard" |
| Table headers | "Responsável" / "Assignee", "Prazo" / "Due Date" |
| Empty states | "Nenhuma tarefa atrasada" / "No overdue tasks" |
| Date formatting | `dd/MM/yyyy` (pt-BR) / `MM/dd/yyyy` (en-US) |
| Role labels | Displayed as-is from DB `role` field (actual job titles, not translated) |

User-created content (task titles, labels, notes) is NOT translated — displayed as-is.

**Priority mapping** (from live production data + TaskFlow docs):

| DB value | pt-BR | en-US | Badge color |
|---|---|---|---|
| `urgente` | Urgente | Urgent | `bg-red-200 text-red-800` |
| `alta` | Alta | High | `bg-red-100 text-red-700` |
| `normal` | Normal | Normal | `bg-gray-100 text-gray-700` |
| `baixa` | Baixa | Low | `bg-blue-100 text-blue-700` |
| `null` | — | — | No badge (no priority set) |

**Note:** The value `media` does NOT exist in the live data. Current production only has `normal` and `null`.

**Column mapping:**

| DB value | pt-BR | en-US | Dot color |
|---|---|---|---|
| `inbox` | Inbox | Inbox | `bg-gray-400` |
| `next_action` | Próxima Ação | Next Action | `bg-blue-400` |
| `in_progress` | Em Andamento | In Progress | `bg-yellow-400` |
| `waiting` | Aguardando | Waiting | `bg-orange-400` |
| `review` | Revisão | Review | `bg-purple-400` |
| `done` | Concluída | Done | `bg-green-400` |

---

## Context for the Developer

### What is TaskFlow?

TaskFlow is a WhatsApp-based GTD (Getting Things Done) task management system running on NanoClaw. Users interact via WhatsApp group messages (e.g., `@Case tarefa para Alexandre: revisar contrato ate sexta`). The bot manages tasks using a Kanban board with GTD columns.

### Data Model

- **Boards** — each WhatsApp group is a board. Boards form a hierarchy: SEC (level 1, root) → SECTI, SECI, TEC, SETEC, SEAF, SETD (level 2, directors). Max depth: 3.
- **Tasks** — GTD columns: `inbox → next_action → in_progress → waiting → review → done`. Each task has assignee, priority, due date, notes, labels, subtasks.
- **People** — board members with a `role` field containing the person's actual job title (e.g., "Subsecretario de Planejamento e Inovacao", "Gestor", "Tecnico"). Also has phone, per-person WIP limits.
- **Runners** — scheduled cron jobs per board: morning standup, manager digest, weekly review.

### Time Semantics

- `due_date` is **ISO 8601 datetime** (NOT date-only). Examples from live data: `2026-03-16T02:59:00Z`, `2026-07-04T20:00:00.000Z`. Some values may have milliseconds, some may not. Always parse as full datetime.
- For **overdue evaluation**, compare only the date portion: extract the date from `due_date`, compare against today in the server's local timezone (`America/Fortaleza`, UTC-3).
- For **display**, show only the date portion formatted per locale (`dd/MM/yyyy` for pt-BR, `MM/dd/yyyy` for en-US).
- `scheduled_at` (meetings only) is also ISO 8601 datetime.
- `created_at` and `updated_at` are ISO 8601 datetime strings.
- Each board has a `timezone` field in `board_runtime_config` (e.g., `America/Fortaleza`). Per-board timezone evaluation is out of scope for v1.

### Database

SQLite at `/home/nanoclaw/nanoclaw/data/taskflow/taskflow.db` on the NanoClaw machine.

Core tables used by this project: `boards`, `board_config`, `board_runtime_config`, `board_people`, `tasks`.

Other tables exist (`task_history`, `board_holidays`, `archive`, `board_admins`, `board_id_counters`) but are NOT used in v1.

### Key Schemas

```sql
CREATE TABLE boards (
  id TEXT PRIMARY KEY,
  group_jid TEXT NOT NULL,
  group_folder TEXT NOT NULL,
  board_role TEXT DEFAULT 'standard',  -- 'standard' | 'hierarchy'
  hierarchy_level INTEGER,
  max_depth INTEGER,
  parent_board_id TEXT REFERENCES boards(id),
  short_code TEXT
);

CREATE TABLE tasks (
  id TEXT NOT NULL,               -- mixed formats: 'T-001', 'T1', 'T12', 'M1', 'P15.1'
  board_id TEXT NOT NULL REFERENCES boards(id),
  type TEXT NOT NULL DEFAULT 'simple',  -- 'simple' | 'project' | 'meeting' | 'recurring' | 'inbox'
  title TEXT NOT NULL,
  assignee TEXT,
  next_action TEXT,               -- GTD next physical action
  waiting_for TEXT,               -- who/what is blocking
  "column" TEXT DEFAULT 'inbox',  -- RESERVED WORD: always quote in SQL
  priority TEXT,                  -- 'urgente' | 'alta' | 'normal' | 'baixa' | NULL
  due_date TEXT,                  -- ISO 8601 datetime (NOT date-only): '2026-03-16T02:59:00Z'
  description TEXT,
  labels TEXT DEFAULT '[]',       -- JSON array of strings (currently empty in prod)
  notes TEXT DEFAULT '[]',        -- JSON array of {id, text, author, created_at}
  subtasks TEXT,                  -- JSON or NULL
  parent_task_id TEXT,            -- links subtask to parent (e.g., 'P15.1' parent is 'P15')
  participants TEXT,              -- meeting participants (JSON)
  scheduled_at TEXT,              -- meeting datetime (ISO 8601)
  recurrence TEXT,                -- recurring task config (JSON)
  created_at TEXT NOT NULL,       -- ISO 8601 datetime
  updated_at TEXT NOT NULL,       -- ISO 8601 datetime
  child_exec_enabled INTEGER DEFAULT 0, -- 1 if task is delegated to a child board
  child_exec_board_id TEXT,             -- which child board has this task (~51 tasks in prod)
  child_exec_person_id TEXT,            -- person on child board
  child_exec_rollup_status TEXT,        -- status from child board
  -- Additional columns exist (linked_parent_*, blocked_by, reminders, etc.) but not used in v1
  PRIMARY KEY (board_id, id)      -- COMPOSITE KEY: task IDs are NOT globally unique
);

CREATE TABLE board_people (
  board_id TEXT REFERENCES boards(id),
  person_id TEXT NOT NULL,
  name TEXT NOT NULL,
  phone TEXT,
  role TEXT DEFAULT 'member',  -- actual job title string, NOT an enum
  wip_limit INTEGER,
  PRIMARY KEY (board_id, person_id)
);

CREATE TABLE board_config (
  board_id TEXT PRIMARY KEY REFERENCES boards(id),
  columns TEXT DEFAULT '["inbox","next_action","in_progress","waiting","review","done"]',
  wip_limit INTEGER DEFAULT 5,
  next_task_number INTEGER DEFAULT 1
);

CREATE TABLE board_runtime_config (
  board_id TEXT PRIMARY KEY REFERENCES boards(id),
  language TEXT NOT NULL DEFAULT 'pt-BR',
  timezone TEXT NOT NULL DEFAULT 'America/Fortaleza',
  standup_cron_local TEXT,
  digest_cron_local TEXT,
  review_cron_local TEXT
);
```

### Current Boards (Production — snapshot 2026-03-20)

The board hierarchy is **dynamic** — new boards are auto-provisioned when a manager registers a person with a phone number. The dashboard must handle new boards appearing at any time.

| Short Code | Level | Parent | Tasks | WhatsApp Group |
|---|---|---|---|---|
| SEC | 1 | — | 84 | SEC-SECTI - TaskFlow |
| SEAF | 2 | SEC | 1 | laizys-taskflow |
| SECI | 2 | SEC | 14 | SECI-SECTI - TaskFlow |
| SECTI | 2 | SEC | 0 | SECTI - TaskFlow |
| SETD | 2 | SEC | 21 | SETD-SECTI - TaskFlow |
| SETEC | 2 | SEC | 7 | SETEC-SECTI - TaskFlow |
| TEC | 2 | SEC | 1 | Tec - TaskFlow |
| *(null)* | 3 | SECI | 0 | ci-seci-taskflow |
| *(null)* | 3 | SETD | 0 | setd-secti-taskflow |
| *(null)* | 3 | SETD | 0 | ux-setd-secti-taskflow |
| *(null)* | 3 | SETEC | 0 | setd-secti-taskflow-2 |

**Note:** Level-3 boards have `short_code = NULL`. The sidebar must fall back to `group_folder` as display name.

**Task column distribution (from 2026-03-20 standup):** inbox: 35, next_action: 33, in_progress: 7, waiting: 5, review: 4, done: 41

**Task types (production):** simple, project (with subtasks via `parent_task_id`), meeting (with `scheduled_at`), recurring, inbox

**Task ID formats (production):** `T-001`, `T1`, `T9`, `T12`, `M1`, `M3`, `M8`, `P15`, `P15.1`, `P16.1`, `T78`, `T79` — mixed formats, NOT zero-padded. Same ID can exist on multiple boards (e.g., `T1` on 4 boards). Always use composite key `(board_id, id)`.

### Real-World Usage Patterns (this week)

Understanding how TaskFlow is actually used helps build the right dashboard:

**Task lifecycle observed this week:**
1. Manager captures on root board: `Anotar: SEI Anatel/IA, atribuir para Rafael` → creates SEC-T79
2. Cross-board notification: SEC → SETEC board: `🔔 Nova tarefa atribuída a você: SEC-T79`
3. Manager delegates deeper: `T79 atribuir para Reginaldo` → system auto-provisions Reginaldo's personal board + WhatsApp group
4. Worker updates via child board: `p16.1 proximo passo, reunião SSP sobre SPIA, agendada 23-03 às 11h00` → updates next_action
5. Worker completes: `T13 foi finalizada` or `T46- concluido✅` → moves to done
6. Voice commands: `[Voice: Iniciar T50.]` → moves to in_progress
7. Reminders: `me lembre de levantar status na segunda sobre os sites faltantes` → schedules reminder

**Automated runners (daily, all boards):**
- **Standup (08:00 local)**: Full Kanban snapshot with counts per board. Includes cross-board task references.
- **Digest (18:00 local)**: Overdue tasks + day summary per board. Includes executive summary on root board.
- **Weekly review (Fri 11:00 local)**: Weekly board review.
- Runner stats this week: 159/159 runs successful, 0 failures. Newly provisioned boards may not have fired yet.

**Cross-board features visible in production:**
- Task assigned on SEC → notification on assignee's child board
- Child board shows parent board tasks in standups
- Notifications: `🔔 Atualização na sua tarefa: T56 — Sistema Procolo Strans`

**Dynamic provisioning (happened today):**
- Rafael typed: `Reginaldo, telefone: 86999986334, Analista de Negócios`
- System: auto-created WhatsApp group, provisioned board, sent welcome message + invite link
- All within seconds — the dashboard should reflect this immediately via WebSocket

**Dashboard implications (prioritized by usage data):**
1. **Distinguish local vs linked tasks** — TEC has 1 local task but 18 linked SEC tasks via `child_exec_board_id`. Boards with 0 local tasks are still active through linked parent work. Show both counts in the board cards and allow filtering.
2. **Quick-search by task ID** — users constantly type `T79`, `P19.1`, `T9`. Add a global search bar that finds tasks by ID across all boards.
3. **Board health dashboard** — combine: local task count + linked task count + mutation rate (history events/week) + runner freshness (last standup/digest time). Highest monitoring need: SEC (84 tasks, 86 events), SECI (15 tasks, 41 events), SETD (21 tasks, 24 events).
4. **Runner status per board** — show last standup/digest/review time. Flag boards where runners haven't fired (e.g., newly provisioned boards).
5. **Auto-refresh sidebar** — new boards appear dynamically (Reginaldo's was created mid-conversation today). Poll `/boards` or use WebSocket.
6. **Cross-board task flow** — `child_exec_*` is the mechanism (~51 tasks). `linked_parent_*` is unused. Show parent board reference on linked task cards.
7. **Filter system noise** — SECI had 778 `⏳ Processando...` messages this week. Analytics/counts should exclude bot processing messages.
8. **Support all task ID formats** — T, M, P, subtask P15.1 — mixed, not zero-padded.

**Activity this week (production data):**
- 1,860 messages across 11 boards (238 substantive user commands after noise filtering)
- 38 tasks created, 50 movement events, 21 completions
- Most active: SEC (20 created, 86 history events), SECI (10 created, 41 events)
- Most common user actions: task updates (44), inbox capture (41), completion (25), delegation (14)

---

## Task 1: TaskFlow API Server

**Location:** `taskflow-api/`

**Files to create:**
- `taskflow-api/main.py`
- `taskflow-api/requirements.txt`
- `taskflow-api/requirements-dev.txt`
- `taskflow-api/taskflow-api.service`
- `taskflow-api/.env.example`
- `taskflow-api/tests/test_api.py`
- `taskflow-api/tests/conftest.py`

### Environment Variables

```bash
# taskflow-api/.env.example
TASKFLOW_DB_PATH=/home/nanoclaw/nanoclaw/data/taskflow/taskflow.db
TASKFLOW_API_PORT=8100
TASKFLOW_API_TOKEN=change-me-to-a-strong-random-token
TASKFLOW_CORS_ORIGINS=http://localhost:3000
TASKFLOW_POLL_INTERVAL=5
```

### Authentication

Bearer token via `Authorization: Bearer <token>` header. Token set via `TASKFLOW_API_TOKEN` env var. All endpoints except `/health` require it. WebSocket authenticates via query param: `/ws?token=<token>`.

**Security note:** The API token is embedded in the frontend bundle and visible in browser DevTools. This is acceptable for a dashboard on a private LAN. For public deployments, add a backend-for-frontend proxy layer.

### CORS

Explicit origin allowlist via `TASKFLOW_CORS_ORIGINS` env var (comma-separated). No wildcard. Update this to match the actual URL where the frontend is served (e.g., `http://192.168.2.63:3000`).

### Error Responses

All errors return JSON: `{"detail": "<message>"}` with HTTP status codes:
- `400` — invalid parameter (e.g., unknown column value)
- `401` — missing or invalid token
- `404` — resource not found
- `503` — database unavailable

### API Contract

#### `GET /health` (no auth)
```json
{"status": "ok"}
```

#### `GET /stats`
```json
{
  "total_boards": 7,
  "total_tasks": 34,
  "tasks_by_column": {"inbox": 6, "next_action": 19, "in_progress": 2, "waiting": 1, "done": 6},
  "tasks_overdue": 3,
  "boards": [
    {
      "id": "board-sec-taskflow",
      "short_code": "SEC",
      "group_folder": "sec-secti",
      "group_jid": "120363409319476199@g.us",
      "board_role": "hierarchy",
      "hierarchy_level": 1,
      "max_depth": 3,
      "parent_board_id": null,
      "task_count": 84,
      "people_count": 5
    }
  ]
}
```

#### `GET /boards`
Returns: `Board[]` (same shape as `boards` in `/stats`)

#### `GET /boards/{board_id}`
Returns `BoardDetail`. The `board_code` field on tasks is derived from `JOIN boards b ON b.id = t.board_id` using `b.short_code`. The `labels` field is parsed server-side from the SQLite JSON string into an actual array.

```json
{
  "id": "board-sec-taskflow",
  "short_code": "SEC",
  "group_folder": "sec-secti",
  "group_jid": "120363409319476199@g.us",
  "board_role": "hierarchy",
  "hierarchy_level": 1,
  "max_depth": 3,
  "parent_board_id": null,
  "task_count": 84,
  "people_count": 5,
  "language": "pt-BR",
  "timezone": "America/Fortaleza",
  "wip_limit": 3,
  "columns": ["inbox", "next_action", "in_progress", "waiting", "review", "done"],
  "standup_cron_local": "0 8 * * 1-5",
  "digest_cron_local": "0 18 * * 1-5",
  "review_cron_local": "0 11 * * 5",
  "people": [
    {"person_id": "p1", "board_id": "board-sec-taskflow", "name": "Miguel Oliveira", "phone": "558699916064", "role": "Gestor", "wip_limit": null}
  ],
  "tasks_by_column": {"inbox": 4, "next_action": 19, "in_progress": 2, "waiting": 1, "done": 2}
}
```

#### `GET /boards/{board_id}/tasks?column=inbox`
Returns: `Task[]`. `column` query param is optional. Valid values: `inbox`, `next_action`, `in_progress`, `waiting`, `review`, `done`. Invalid → 400.

```json
{
  "id": "T12",
  "board_id": "board-sec-taskflow",
  "board_code": "SEC",
  "title": "Revisar contrato do fornecedor",
  "assignee": "Carlos Giovanni",
  "column": "next_action",
  "priority": "normal",
  "due_date": "2026-03-20T02:59:00Z",
  "type": "simple",
  "labels": [],
  "created_at": "2026-03-15T10:00:00",
  "updated_at": "2026-03-19T14:30:00"
}
```

Note: `labels` is returned as a **parsed JSON array** (not a raw string). The API parses the SQLite JSON string server-side. If parsing fails, return `[]`.

#### `GET /tasks/overdue`
Returns: `Task[]` — tasks where `date(due_date) < date('now', 'localtime')` AND `column NOT IN ('done')`. Sorted by `due_date ASC`.

#### `GET /tasks/search?q=T79`
Returns: `Task[]` — search by task ID across all boards. Matches `id LIKE ?` (case-insensitive). Users frequently search by task ID in WhatsApp (`T79`, `P19.1`). Limit 20 results.

#### `GET /boards/{board_id}/linked-tasks`
Returns: `Task[]` — tasks on THIS board that are delegated to child boards (`child_exec_board_id IS NOT NULL`). Crucial: TEC has 1 local task but 18 linked SEC tasks. Include `child_exec_board_id`, `child_exec_person_id`, `child_exec_rollup_status` in response.

#### `GET /runners/status`
Returns runner health for all boards:
```json
[{
  "board_id": "board-sec-taskflow",
  "standup_last_run": null,
  "digest_last_run": null,
  "review_last_run": null,
  "standup_cron": "0 8 * * 1-5",
  "digest_cron": "0 18 * * 1-5",
  "review_cron": "0 11 * * 5"
}]
```
Query from `board_runtime_config`. **Note:** `task_run_logs` table does not exist yet in production — all `*_last_run` values return `null` until TaskFlow core implements run logging. Cron schedules come from `board_runtime_config`.

#### `WS /ws?token=<token>`

Events (server → client):
```json
{"event": "taskflow:snapshot", "data": <Stats>}   // on connect
{"event": "taskflow:updated", "data": <Stats>}    // when data changes
```

**Change detection SQL** (runs every `TASKFLOW_POLL_INTERVAL` seconds):
```sql
SELECT
  (SELECT max(updated_at) || ':' || count(*) FROM tasks) || '|' ||
  (SELECT count(*) FROM boards) || '|' ||
  (SELECT count(*) FROM board_people) || '|' ||
  (SELECT count(*) FROM board_config)
AS hash
```

This detects: task creates/updates/deletes, board adds/removes, people adds/removes, config adds/removes. It does NOT detect in-place config value changes (e.g., WIP limit change) since those tables lack `updated_at`. Acceptable for v1.

### Requirements

```
# requirements.txt
fastapi>=0.115
uvicorn>=0.34
```

```
# requirements-dev.txt
pytest>=8.0
httpx>=0.27
pytest-asyncio>=0.23
```

### Systemd Service

```ini
# taskflow-api/taskflow-api.service
[Unit]
Description=TaskFlow API
After=network.target

[Service]
Type=simple
User=nanoclaw
WorkingDirectory=/home/nanoclaw/taskflow-api
EnvironmentFile=/home/nanoclaw/taskflow-api/.env
ExecStart=/home/nanoclaw/taskflow-api/run.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### TDD Implementation

**Step 1: Write `conftest.py` with fixture SQLite database**

```python
# taskflow-api/tests/conftest.py
import os, sqlite3, pytest, importlib

@pytest.fixture(autouse=True)
def test_env(tmp_path):
    """Create fixture DB and set env vars BEFORE importing main."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE boards (id TEXT PRIMARY KEY, short_code TEXT, group_folder TEXT, group_jid TEXT, board_role TEXT, hierarchy_level INTEGER, max_depth INTEGER, parent_board_id TEXT);
        CREATE TABLE tasks (id TEXT, board_id TEXT, type TEXT DEFAULT 'simple', title TEXT, assignee TEXT, "column" TEXT DEFAULT 'inbox', priority TEXT, due_date TEXT, labels TEXT DEFAULT '[]', notes TEXT DEFAULT '[]', subtasks TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE board_people (board_id TEXT, person_id TEXT, name TEXT, phone TEXT, role TEXT, wip_limit INTEGER, PRIMARY KEY (board_id, person_id));
        CREATE TABLE board_config (board_id TEXT PRIMARY KEY, columns TEXT DEFAULT '[]', wip_limit INTEGER DEFAULT 5, next_task_number INTEGER DEFAULT 1);
        CREATE TABLE board_runtime_config (board_id TEXT PRIMARY KEY, language TEXT DEFAULT 'pt-BR', timezone TEXT DEFAULT 'America/Fortaleza', standup_cron_local TEXT, digest_cron_local TEXT, review_cron_local TEXT);

        INSERT INTO boards VALUES ('board-test', 'TEST', 'test', '123@g.us', 'hierarchy', 1, 3, NULL);
        INSERT INTO boards VALUES ('board-child', 'CHILD', 'child', '456@g.us', 'hierarchy', 2, 3, 'board-test');
        INSERT INTO tasks VALUES ('T-001', 'board-test', 'simple', 'Overdue task', 'Alice', 'inbox', 'normal', '2020-01-15T02:59:00Z', '[]', '[]', NULL, '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        INSERT INTO tasks VALUES ('T1', 'board-test', 'simple', 'Normal task', 'Bob', 'next_action', NULL, '2099-12-31T23:59:00Z', '[]', '[]', NULL, '2026-01-01T00:00:00', '2026-01-02T00:00:00');
        INSERT INTO tasks VALUES ('M1', 'board-test', 'meeting', 'Team standup', NULL, 'done', NULL, NULL, '[]', '[]', NULL, '2026-01-01T00:00:00', '2026-01-03T00:00:00');
        INSERT INTO board_people VALUES ('board-test', 'p1', 'Alice', '5551234', 'Gestor', 3);
        INSERT INTO board_people VALUES ('board-test', 'p2', 'Bob', '5555678', 'Tecnico', NULL);
        INSERT INTO board_config VALUES ('board-test', '["inbox","next_action","in_progress","waiting","review","done"]', 3, 4);
        INSERT INTO board_runtime_config VALUES ('board-test', 'pt-BR', 'America/Fortaleza', '0 8 * * 1-5', '0 18 * * 1-5', '0 11 * * 5');
    """)
    conn.close()

    os.environ["TASKFLOW_DB_PATH"] = db_path
    os.environ["TASKFLOW_API_TOKEN"] = "test-token"
    os.environ["TASKFLOW_CORS_ORIGINS"] = "http://localhost:3000"
    os.environ["TASKFLOW_POLL_INTERVAL"] = "60"

    # Force reimport to pick up new env vars
    import main as main_module
    importlib.reload(main_module)
    yield db_path

@pytest.fixture
def client():
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)

@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}
```

**Step 2: Write failing tests first**

```python
# taskflow-api/tests/test_api.py

# --- Auth tests ---
def test_health_no_auth_required(client):
    assert client.get("/health").status_code == 200

def test_stats_requires_auth(client):
    assert client.get("/stats").status_code == 401

def test_stats_wrong_token(client):
    r = client.get("/stats", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401

# --- Stats ---
def test_stats(client, auth_headers):
    r = client.get("/stats", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total_boards"] == 2
    assert d["total_tasks"] == 3
    assert d["tasks_overdue"] == 1
    assert d["tasks_by_column"]["inbox"] == 1
    assert d["tasks_by_column"]["next_action"] == 1
    assert d["tasks_by_column"]["done"] == 1

# --- Boards ---
def test_boards(client, auth_headers):
    r = client.get("/boards", headers=auth_headers)
    assert r.status_code == 200
    boards = r.json()
    assert len(boards) == 2
    sec = next(b for b in boards if b["short_code"] == "TEST")
    assert sec["task_count"] == 3
    assert sec["people_count"] == 2

def test_board_detail(client, auth_headers):
    r = client.get("/boards/board-test", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["wip_limit"] == 3
    assert d["language"] == "pt-BR"
    assert d["timezone"] == "America/Fortaleza"
    assert d["standup_cron_local"] == "0 8 * * 1-5"
    assert len(d["people"]) == 2
    assert d["tasks_by_column"]["inbox"] == 1
    assert d["columns"] == ["inbox", "next_action", "in_progress", "waiting", "review", "done"]

def test_board_hierarchy(client, auth_headers):
    r = client.get("/boards/board-child", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["parent_board_id"] == "board-test"

def test_board_not_found(client, auth_headers):
    assert client.get("/boards/nonexistent", headers=auth_headers).status_code == 404

# --- Tasks ---
def test_board_tasks(client, auth_headers):
    r = client.get("/boards/board-test/tasks", headers=auth_headers)
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 3
    assert all("board_code" in t for t in tasks)
    assert tasks[0]["board_code"] == "TEST"

def test_board_tasks_filter_column(client, auth_headers):
    r = client.get("/boards/board-test/tasks?column=inbox", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == "T-001"

def test_board_tasks_invalid_column(client, auth_headers):
    r = client.get("/boards/board-test/tasks?column=hacked", headers=auth_headers)
    assert r.status_code == 400

def test_labels_parsed_as_array(client, auth_headers):
    r = client.get("/boards/board-test/tasks?column=inbox", headers=auth_headers)
    task = r.json()[0]
    assert isinstance(task["labels"], list)
    assert task["labels"] == []

def test_task_has_composite_key_fields(client, auth_headers):
    r = client.get("/boards/board-test/tasks", headers=auth_headers)
    task = r.json()[0]
    assert "board_id" in task
    assert "board_code" in task

# --- Overdue ---
def test_overdue(client, auth_headers):
    r = client.get("/tasks/overdue", headers=auth_headers)
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == "T-001"
    assert "2020-01-15" in tasks[0]["due_date"]  # ISO datetime, contains date portion

# --- WebSocket ---
def test_ws_requires_auth(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            pass

def test_ws_wrong_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=wrong") as ws:
            pass

def test_ws_snapshot_on_connect(client):
    with client.websocket_connect("/ws?token=test-token") as ws:
        data = ws.receive_json()
        assert data["event"] == "taskflow:snapshot"
        assert data["data"]["total_boards"] == 2
```

**Step 3: Run tests — they should all FAIL (main.py doesn't exist yet)**

```bash
cd taskflow-api && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
# Expected: ImportError or all failures
```

**Step 4: Implement `main.py`** — write the minimal FastAPI app to make all tests pass

Key implementation notes:
- Read ALL env vars inside functions/dependencies, NOT at module level (for test reloadability)
- SQLite connection: `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`
- All SQL uses `?` parameterized queries for user input (`board_id`, `column`)
- Parse `labels` server-side: `json.loads(row["labels"] or "[]")` with try/except returning `[]`
- `"column"` is a reserved word in SQL — always quote it as `"column"` or backtick it
- WebSocket: accept only if token matches, send snapshot on connect, poll in background task

**Step 5: Run tests — they should all PASS**

```bash
pytest tests/ -v
# Expected: 17 tests passed
```

**Step 6: Deploy on NanoClaw**

```bash
scp -r taskflow-api/ nanoclaw@192.168.2.63:/home/nanoclaw/taskflow-api/
ssh nanoclaw@192.168.2.63
cd /home/nanoclaw/taskflow-api
cp .env.example .env
# Edit .env: set a strong TASKFLOW_API_TOKEN and correct TASKFLOW_CORS_ORIGINS

# First time only: install pip and venv (not installed by default)
sudo apt update && sudo apt install -y python3-pip python3-venv

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Create run.sh wrapper:
echo '#!/bin/bash
cd /home/nanoclaw/taskflow-api && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100' > run.sh
chmod +x run.sh
./run.sh  # smoke test

# Install as systemd service:
sudo cp taskflow-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now taskflow-api
curl http://localhost:8100/health
```

**Step 7: Commit**

```bash
git add taskflow-api/
git commit -m "feat(taskflow-api): HTTP API + WebSocket with auth, CORS, and tests"
```

---

## Task 2: Frontend — Project Setup, API Client, i18n

**Location:** `taskflow-dashboard/`

**Files to create:**
- `taskflow-dashboard/package.json`
- `taskflow-dashboard/` build config (bundler-specific)
- `taskflow-dashboard/tsconfig.json`
- `taskflow-dashboard/tailwind.config.ts`
- `taskflow-dashboard/postcss.config.js`
- `taskflow-dashboard/.env.example`
- `taskflow-dashboard/src/api/types.ts`
- `taskflow-dashboard/src/api/taskflow.ts`
- `taskflow-dashboard/src/api/__tests__/taskflow.test.ts`
- `taskflow-dashboard/src/i18n/index.ts`
- `taskflow-dashboard/src/i18n/pt-BR.ts`
- `taskflow-dashboard/src/i18n/en-US.ts`
- `taskflow-dashboard/src/i18n/__tests__/i18n.test.ts`
- `taskflow-dashboard/src/hooks/useLocale.tsx`
- `taskflow-dashboard/src/hooks/useTaskFlowWebSocket.ts`
- `taskflow-dashboard/src/main.tsx`
- `taskflow-dashboard/src/App.tsx`
- `taskflow-dashboard/index.html`

### Environment Variables

```bash
# taskflow-dashboard/.env.example
TASKFLOW_API_URL=http://localhost:8100
TASKFLOW_API_TOKEN=same-token-as-api-server
```

### Step 1: Scaffold project

Set up a TypeScript + React 19 project with your preferred bundler and test runner. Install these dependencies:

```bash
# Core
npm install react react-dom

# Routing & data
npm install react-router-dom @tanstack/react-query @tanstack/react-table

# UI
npm install recharts @radix-ui/react-dialog @radix-ui/react-tabs @radix-ui/react-tooltip
npm install tailwindcss@3 postcss autoprefixer lucide-react tailwind-merge tailwindcss-animate

# Dev / testing
npm install -D typescript @types/react @types/react-dom
npm install -D @testing-library/react @testing-library/jest-dom jsdom
# + your chosen test runner (vitest, jest, etc.)
```

Configure your bundler to expose environment variables `TASKFLOW_API_URL` and `TASKFLOW_API_TOKEN` to the browser (the mechanism depends on your bundler).

### Step 2: Write TypeScript types (TDD: types first)

```typescript
// taskflow-dashboard/src/api/types.ts
export interface Board {
  id: string;
  short_code: string | null;
  group_folder: string;
  group_jid: string;
  board_role: string;
  hierarchy_level: number | null;
  max_depth: number | null;
  parent_board_id: string | null;
  task_count: number;
  people_count: number;
}

export interface Task {
  id: string;              // mixed formats: 'T-001', 'T1', 'M1', 'P15.1'
  board_id: string;
  board_code: string | null;  // from boards.short_code (may be null for level-3 boards)
  title: string;
  assignee: string | null;
  column: string;
  priority: string | null;    // 'urgente' | 'alta' | 'normal' | 'baixa' | null
  due_date: string | null;    // ISO 8601 datetime: '2026-03-16T02:59:00Z' (NOT date-only)
  type: string;               // 'simple' | 'project' | 'meeting' | 'recurring' | 'inbox'
  labels: string[];           // parsed array, NOT a string
  parent_task_id: string | null;  // non-null for subtasks (e.g., 'P15.1' → parent 'P15')
  scheduled_at: string | null;   // meetings only: ISO 8601 datetime
  child_exec_board_id: string | null;  // if delegated to a child board (~51 tasks in prod)
  child_exec_person_id: string | null; // person on child board
  child_exec_rollup_status: string | null; // status from child board
  created_at: string;
  updated_at: string;
}

// Unique key for a task is (board_id, id) — NOT id alone

export interface Person {
  person_id: string;
  board_id: string;
  name: string;
  phone: string | null;
  role: string;
  wip_limit: number | null;
}

export interface BoardDetail extends Board {
  language: string | null;
  timezone: string | null;
  wip_limit: number | null;
  columns: string[];
  standup_cron_local: string | null;
  digest_cron_local: string | null;
  review_cron_local: string | null;
  people: Person[];
  tasks_by_column: Record<string, number>;
}

export interface Stats {
  total_boards: number;
  total_tasks: number;
  tasks_by_column: Record<string, number>;
  tasks_overdue: number;
  boards: Board[];
}

export interface WsEvent {
  event: "taskflow:snapshot" | "taskflow:updated";
  data: Stats;
}
```

### Step 3: Write i18n module (TDD)

Write failing test first:
```typescript
// taskflow-dashboard/src/i18n/__tests__/i18n.test.ts
import { getMessages } from '../index';

test('pt-BR has all column translations', () => {
  const m = getMessages('pt-BR');
  expect(m.columns.next_action).toBe('Próxima Ação');
  expect(m.columns.done).toBe('Concluída');
});

test('en-US has all column translations', () => {
  const m = getMessages('en-US');
  expect(m.columns.next_action).toBe('Next Action');
  expect(m.columns.done).toBe('Done');
});

test('priorities are translated', () => {
  expect(getMessages('pt-BR').priorities.alta).toBe('Alta');
  expect(getMessages('en-US').priorities.alta).toBe('High');
});

test('page titles differ by locale', () => {
  expect(getMessages('pt-BR').dashboardTitle).toBe('Painel TaskFlow');
  expect(getMessages('en-US').dashboardTitle).toBe('TaskFlow Dashboard');
});
```

Then implement `Messages` interface, `pt-BR.ts`, `en-US.ts`, and `getMessages()` function.

The `Messages` interface must include: `dashboardTitle`, `dashboardSubtitle`, `boardDetailSubtitle`, `boards`, `tasks`, `overdue`, `inProgress`, `taskId`, `title`, `assignee`, `dueDate`, `board`, `priority`, `people`, `noOverdueTasks`, `noTasks`, `boardConfig`, `language`, `timezone`, `wipLimit`, `standup`, `digest`, `weeklyReview`, `columns` (Record), `priorities` (Record), `boardView`, `listView`.

### Step 4: Write API client with WebSocket reconnection

```typescript
// taskflow-dashboard/src/api/taskflow.ts
// Access env vars via your bundler's mechanism (e.g., import.meta.env.*, process.env.*, window.__ENV__, etc.)
const API_URL = /* env: TASKFLOW_API_URL */ "http://localhost:8100";
const API_TOKEN = /* env: TASKFLOW_API_TOKEN */ "";

const headers = (): HeadersInit => ({
  "Authorization": `Bearer ${API_TOKEN}`,
  "Content-Type": "application/json",
});

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { headers: headers() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const taskflowApi = {
  health: () => get<{ status: string }>("/health"),
  stats: () => get<Stats>("/stats"),
  boards: () => get<Board[]>("/boards"),
  board: (id: string) => get<BoardDetail>(`/boards/${encodeURIComponent(id)}`),
  boardTasks: (id: string, column?: string) => {
    const q = column ? `?column=${encodeURIComponent(column)}` : "";
    return get<Task[]>(`/boards/${encodeURIComponent(id)}/tasks${q}`);
  },
  overdueTasks: () => get<Task[]>("/tasks/overdue"),
};

export function connectWebSocket(onEvent: (event: WsEvent) => void): () => void {
  let ws: WebSocket | null = null;
  let retryMs = 1000;
  let stopped = false;

  function connect() {
    if (stopped) return;
    const wsUrl = API_URL.replace(/^http/, "ws") + `/ws?token=${encodeURIComponent(API_TOKEN)}`;
    ws = new WebSocket(wsUrl);
    ws.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)); } catch {}
      retryMs = 1000; // reset backoff on successful message
    };
    ws.onclose = () => {
      if (stopped) return;
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 30000); // exponential backoff, max 30s
    };
    ws.onerror = () => ws?.close();
  }

  connect();
  return () => { stopped = true; ws?.close(); };
}
```

### Step 5: Write `useLocale` hook

```typescript
// taskflow-dashboard/src/hooks/useLocale.tsx
import { createContext, useContext, useState, type ReactNode } from 'react';
import type { Locale } from '../i18n';

const STORAGE_KEY = 'taskflow-locale';
const defaultLocale: Locale = (localStorage.getItem(STORAGE_KEY) as Locale) || 'pt-BR';

const LocaleContext = createContext<[Locale, (l: Locale) => void]>([defaultLocale, () => {}]);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(defaultLocale);
  const setLocale = (l: Locale) => { setLocaleState(l); localStorage.setItem(STORAGE_KEY, l); };
  return <LocaleContext.Provider value={[locale, setLocale]}>{children}</LocaleContext.Provider>;
}

export function useLocale() { return useContext(LocaleContext); }
```

### Step 6: Write `useTaskFlowWebSocket` hook

```typescript
// taskflow-dashboard/src/hooks/useTaskFlowWebSocket.ts
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { connectWebSocket } from '../api/taskflow';

export function useTaskFlowWebSocket() {
  const qc = useQueryClient();
  useEffect(() => {
    const disconnect = connectWebSocket((event) => {
      if (event.event === 'taskflow:updated') {
        qc.invalidateQueries({ queryKey: ['taskflow'] });
      }
    });
    return disconnect;
  }, [qc]);
}
```

### Step 7: Set up routing in `App.tsx`

```typescript
// taskflow-dashboard/src/App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LocaleProvider } from './hooks/useLocale';
import { Layout } from './components/Layout';
import Dashboard from './pages/Dashboard';
import BoardDetail from './pages/BoardDetail';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LocaleProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/boards/:boardId" element={<BoardDetail />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </LocaleProvider>
    </QueryClientProvider>
  );
}
```

**Route table:** `/` → Dashboard, `/boards/:boardId` → BoardDetail

### Step 8: Run tests

```bash
npx test  # or your test runner command
```

### Step 9: Commit

```bash
git add taskflow-dashboard/
git commit -m "feat(taskflow-dashboard): scaffold React app with typed API client, i18n, WebSocket, and routing"
```

---

## Task 3: Frontend — Overview Dashboard

**Files to create:**
- `taskflow-dashboard/src/pages/Dashboard.tsx`
- `taskflow-dashboard/src/components/Layout.tsx`
- `taskflow-dashboard/src/components/Sidebar.tsx`
- `taskflow-dashboard/src/components/StatsCards.tsx`
- `taskflow-dashboard/src/components/BoardHierarchy.tsx`
- `taskflow-dashboard/src/components/ColumnChart.tsx`
- `taskflow-dashboard/src/components/OverdueTable.tsx`
- `taskflow-dashboard/src/components/LocaleToggle.tsx`
- `taskflow-dashboard/src/components/__tests__/Dashboard.test.tsx`

**Layout:**

```
┌──────────────────────────────────────────────────────────────┐
│ Painel TaskFlow                             [pt-BR] [en-US]  │
│ Monitore seus quadros e tarefas GTD.                         │
│                                                              │
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                │
│ │Quadros │ │Tarefas │ │Atrasa- │ │Em Anda-│                │
│ │   7    │ │   35   │ │das  3  │ │mento 2 │                │
│ └────────┘ └────────┘ └────────┘ └────────┘                │
│                                                              │
│ ┌─ Hierarquia ──────────────────────────────────────────────┐│
│ │ SEC (raiz) — 28 tarefas                                   ││
│ │  ├─ SECTI — 0         ├─ SETEC — 0                       ││
│ │  ├─ SECI — 2          ├─ SEAF — 0                        ││
│ │  ├─ TEC — 0           └─ SETD — 4                        ││
│ └───────────────────────────────────────────────────────────┘│
│                                                              │
│ ┌─ Tarefas por Coluna ─┐ ┌─ Tarefas Atrasadas ─────────────┐│
│ │ [Recharts bar chart] │ │ ID   │ Título   │ Prazo  │Quadro││
│ │ inbox: 6             │ │ T003 │ Revisar..│ 15/03  │ SEC  ││
│ │ próx. ação: 20       │ │ T012 │ Contrato.│ 10/03  │ SEC  ││
│ │ em andamento: 2      │ │                                   ││
│ └──────────────────────┘ └───────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

**Sidebar content:**
- "TaskFlow" brand at top with `ClipboardList` Lucide icon
- "Dashboard" link (always visible, links to `/`)
- "Quadros" / "Boards" section header
- List of all boards fetched from `/boards`, each as a link to `/boards/:boardId`, showing `short_code` and `task_count` badge

### TDD Steps

**Step 1: Write smoke test**

```typescript
// taskflow-dashboard/src/components/__tests__/Dashboard.test.tsx
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { LocaleProvider } from '../../hooks/useLocale';
import Dashboard from '../../pages/Dashboard';

// Mock the API
vi.mock('../../api/taskflow', () => ({
  taskflowApi: {
    stats: vi.fn().mockResolvedValue({
      total_boards: 2, total_tasks: 5, tasks_by_column: { inbox: 3, done: 2 },
      tasks_overdue: 1, boards: [{ id: 'b1', short_code: 'TEST', task_count: 5, people_count: 2, /* ... */ }],
    }),
    overdueTasks: vi.fn().mockResolvedValue([]),
  },
  connectWebSocket: vi.fn().mockReturnValue(() => {}),
}));

function renderDashboard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LocaleProvider>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </LocaleProvider>
    </QueryClientProvider>
  );
}

test('renders dashboard title in pt-BR', async () => {
  renderDashboard();
  expect(await screen.findByText('Painel TaskFlow')).toBeTruthy();
});

test('renders stats cards', async () => {
  renderDashboard();
  expect(await screen.findByText('2')).toBeTruthy(); // total_boards
});
```

**Step 2: Run test — should FAIL**

**Step 3: Implement components to make tests pass**

**Step 4: Build remaining components (StatsCards, BoardHierarchy, ColumnChart, OverdueTable, Layout, Sidebar, LocaleToggle)**

**Step 5: Run all tests — should PASS**

**Step 6: Manual test at `http://localhost:5173/`**

**Step 7: Commit**

```bash
git commit -m "feat(taskflow-dashboard): add overview dashboard with real-time stats and hierarchy"
```

---

## Task 4: Frontend — Board Detail with Kanban View

**Files to create:**
- `taskflow-dashboard/src/pages/BoardDetail.tsx`
- `taskflow-dashboard/src/components/KanbanView.tsx`
- `taskflow-dashboard/src/components/TaskCard.tsx`
- `taskflow-dashboard/src/components/PeoplePanel.tsx`
- `taskflow-dashboard/src/components/BoardConfigPanel.tsx`
- `taskflow-dashboard/src/components/TaskListView.tsx`
- `taskflow-dashboard/src/components/__tests__/BoardDetail.test.tsx`
- `taskflow-dashboard/src/components/__tests__/TaskCard.test.tsx`

**Layout (Kanban — "Board" toggle):**

```
┌──────────────────────────────────────────────────────────────────────┐
│ SEC — Secretaria                               [Quadro] [Lista]     │
│ Nível 1 · 4 pessoas · Limite WIP: 3              [pt-BR] [en-US]   │
│                                                                      │
│ ┌─EQUIPE──┐ ┌─● Inbox──4──┐ ┌─● Próx. Ação─19─┐ ┌─● Em Andam.─2─┐│
│ │         │ │              │ │                  │ │                 ││
│ │ Miguel  │ │ ┌──────────┐ │ │ ┌──────────┐    │ │ ┌──────────┐   ││
│ │ Gestor  │ │ │SEC-T023  │ │ │ │SEC-T001  │    │ │ │SEC-T015  │   ││
│ │         │ │ │Revisar.. │ │ │ │  ALTA     │    │ │ │  ALTA    │   ││
│ │ Carlos  │ │ │○ Carlos  │ │ │ │Contrato..│    │ │ │Deploy... │   ││
│ │ SubSec. │ │ └──────────┘ │ │ │○ Alex    │    │ │ │○ Miguel  │   ││
│ │ Plan.   │ │              │ │ └──────────┘    │ │ └──────────┘   ││
│ │         │ │              │ │                  │ │                 ││
│ │ Alex    │ │              │ │                  │ │                 ││
│ │ Técnico │ │              │ │                  │ │                 ││
│ └─────────┘ └──────────────┘ └──────────────────┘ └────────────────┘│
│                                                                      │
│ ┌─● Aguardando─1┐ ┌─● Revisão─0───────────────┐ ┌─● Concluída─2──┐│
│ │               │ │                             │ │                 ││
│ │ ┌───────────┐ │ │   (Nenhuma tarefa)          │ │ ┌────────────┐ ││
│ │ │SEC-T008   │ │ │                             │ │ │SEC-T002    │ ││
│ │ │Aguardando │ │ │                             │ │ │Concluído.. │ ││
│ │ │jurídico   │ │ │                             │ │ │○ Alex      │ ││
│ │ └───────────┘ │ │                             │ │ └────────────┘ ││
│ └───────────────┘ └─────────────────────────────┘ └────────────────┘│
│                                                                      │
│ ┌─ Configuração do Quadro ──────────────────────────────────────────┐│
│ │ Idioma: pt-BR · Fuso: America/Fortaleza · WIP: 3                 ││
│ │ Standup: 08:00 · Digest: 18:00 · Revisão Semanal: Sex 11:00      ││
│ └────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

**List view ("Lista" toggle):** TanStack Table showing all tasks for the board in a flat table with columns: ID, Title, Assignee, Column, Priority, Due Date. Sortable. Uses the same i18n translations.

**TaskCard component:**
- White card, `rounded-lg`, `shadow-sm`, `border border-gray-100`
- Top: Task ID (e.g., `SEC-T12`, `SEC-M1`, `SEC-P15.1`) + priority badge pill
- Middle: Title text (`line-clamp-2`)
- Bottom: Label pills (from parsed `labels` array) + assignee with `User` Lucide icon
- Overdue `due_date` → `text-red-600` + red border-left accent

**PeoplePanel:**
- Header: "EQUIPE" / "PEOPLE" + count
- Each person: green dot (first person listed) / blue dot (others) + name + role text (from DB `role` field, displayed as-is)

**BoardConfigPanel** (collapsible, `Settings` Lucide icon):
- Language, timezone, WIP limit, standup/digest/review cron times

### TDD Steps

**Step 1: Write TaskCard unit test**

```typescript
// taskflow-dashboard/src/components/__tests__/TaskCard.test.tsx
import { render, screen } from '@testing-library/react';
import { LocaleProvider } from '../../hooks/useLocale';
import TaskCard from '../TaskCard';

const mockTask = {
  id: 'T-001', board_id: 'b1', board_code: 'SEC', title: 'Test task',
  assignee: 'Alice', column: 'inbox', priority: 'alta', due_date: '2020-01-01',
  type: 'simple', labels: ['urgente'], created_at: '', updated_at: '',
};

test('renders task ID and title', () => {
  render(<LocaleProvider><TaskCard task={mockTask} /></LocaleProvider>);
  expect(screen.getByText('SEC-T-001')).toBeTruthy();
  expect(screen.getByText('Test task')).toBeTruthy();
});

test('renders priority badge in pt-BR', () => {
  render(<LocaleProvider><TaskCard task={mockTask} /></LocaleProvider>);
  expect(screen.getByText('Alta')).toBeTruthy();
});

test('renders overdue date in red', () => {
  render(<LocaleProvider><TaskCard task={mockTask} /></LocaleProvider>);
  const dateEl = screen.getByText(/01\/01\/2020/);
  expect(dateEl.className).toContain('text-red');
});

test('renders label pills', () => {
  render(<LocaleProvider><TaskCard task={mockTask} /></LocaleProvider>);
  expect(screen.getByText('urgente')).toBeTruthy();
});
```

**Step 2: Run — FAIL**

**Step 3: Implement TaskCard**

**Step 4: Write BoardDetail smoke test**

**Step 5: Implement KanbanView, PeoplePanel, BoardConfigPanel, TaskListView**

**Step 6: Run all tests — PASS**

**Step 7: Manual test at `/boards/board-sec-taskflow`**

**Step 8: Commit**

```bash
git commit -m "feat(taskflow-dashboard): add multilingual board detail with kanban and list views"
```

---

## Task 5: Deploy

**Step 1: Deploy API server on NanoClaw (if not already done in Task 1)**

```bash
ssh nanoclaw@192.168.2.63
cd /home/nanoclaw/taskflow-api
cp .env.example .env
# Edit .env:
#   TASKFLOW_API_TOKEN=<generate: openssl rand -hex 32>
#   TASKFLOW_CORS_ORIGINS=http://192.168.2.63:3000  (or wherever frontend is served)
sudo apt update && sudo apt install -y python3-pip python3-venv  # first time only
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo cp taskflow-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now taskflow-api
curl http://localhost:8100/health  # → {"status": "ok"}
```

**Step 2: Build frontend**

```bash
cd taskflow-dashboard
cp .env.example .env
# Edit .env:
#   TASKFLOW_API_URL=http://192.168.2.63:8100
#   TASKFLOW_API_TOKEN=<same token as API server>
npm run build
```

**Step 3: Serve frontend**

Option A (simple):
```bash
npx serve -s dist -l 3000
```

Option B (production — Caddy):
```
:3000 {
  root * /home/nanoclaw/taskflow-dashboard/dist
  try_files {path} /index.html
  file_server
}
```

**Step 4: Verify**

- Open `http://192.168.2.63:3000/` → dashboard loads with live data
- Click SEC board → Kanban view with tasks
- Toggle pt-BR / en-US → all labels, headers, dates switch
- Toggle Board / List → view switches between Kanban and table
- Open DevTools → Network → WS: connected, receiving events
- Overdue tasks table shows tasks with past due dates
- Unauthorized API calls (no token) return 401
- Empty board shows empty state message

**Step 5: Tag**

```bash
git tag v1.0.0-taskflow-dashboard
```

---

## Data Display Rules

- **Task IDs:** Display as `{board_code}-{id}` (e.g., `SEC-T-001`). If `board_code` is null, use `{group_folder}` as fallback. Never assume ID format — display as-is.
- **Meetings** (`type = 'meeting'`): Show in Kanban like any other task. Display `scheduled_at` datetime instead of `due_date` if available. Use `M` prefix icon or badge to distinguish.
- **Subtasks** (`parent_task_id IS NOT NULL`): Show in Kanban like regular tasks. Optionally indent or show parent reference. Do NOT filter them out.
- **Boards with null `short_code`** (level-3 boards): Use `group_folder` as display name in sidebar and headers.
- **Priority null:** No badge displayed. Treat as "no priority set."
- **Labels empty:** `[]` — no label pills rendered. Labels may be populated in the future.
- **Role field:** Display the raw `role` string from the database. Do NOT assume it's an enum — it contains actual job titles.

---

## Out of Scope (v2)

- Board Chat panel (right-side drawer with threaded agent messages — visible in screenshot 2)

- Write operations (creating/moving tasks from the dashboard)
- Runner management (start/stop/reschedule cron jobs from UI)
- Meeting management UI
- Task delegation (child board execution from dashboard)
- Attachment viewer
- Board creation wizard
- TLS termination (use Caddy/nginx reverse proxy if needed)
- Per-board timezone in overdue evaluation (v1 uses server local time)
- Pagination on task endpoints (v1 data volumes are small)


  ┌────────────────────────────────────────────────────────────────────────┬──────────┐
  │                                 Agent                                  │ Interval │
  ├────────────────────────────────────────────────────────────────────────┼──────────┤
  │ Programmer-Frontend                                                    │ 3m       │
  ├────────────────────────────────────────────────────────────────────────┼──────────┤
  │ Programmer-Backend                                                     │ 3m       │
  ├────────────────────────────────────────────────────────────────────────┼──────────┤
  │ Supervisor                                                             │ 5m       │
  ├────────────────────────────────────────────────────────────────────────┼──────────┤
  │ Architect, QA-Unit, QA-E2E                                             │ 10m      │
  ├────────────────────────────────────────────────────────────────────────┼──────────┤
  │ DevOps                                                                 │ 30m      │
  └────────────────────────────────────────────────────────────────────────┴──────────┘

      332 -**If you are the Supervisor and QA reports a blocker:**                                                                                                                                 
      333 -- Route the failure to the responsible developer with a clear ask.                                                                                                                        
      334 -- Track the blocker in `MEMORY.md`.                                                                                                                                                     
      335 -- Follow up next heartbeat if the developer hasn't responded.    

      are you reviewing the plan for the next board run? 

skills list as:
  - frontend-aesthetics — triggers when generating any frontend UI code
  - frontend-architecture — triggers when planning greenfield or design-led frontend work
  - frontend-review — triggers when reviewing frontend output (preflight or final review)

  Pre-start fixes needed:

  1. Copy missing fixture to QA-E2E's workspace
  2. Clear QA-E2E's 22 stale sessions
  3. Fix Frontend task status (inbox → review)
  4. Replace python3 -m http.server with npx serve -s (SPA routing)
  5. Kill stale port 8000 API
  6. Run board-start.sh

  Let me execute the 6 pre-start fixes, keeping all review tasks for the Supervisor to re-evaluate with the new checklist.
  Ready for bash scripts/board-start.sh when you give
  the word.

  Are the plans file following the strucuture from https://developers.openai.com/blog/designing-delightful-frontends-with-gpt-5-4 and                                                    
https://claude.com/blog/improving-frontend-design-through-skills, review and validate     