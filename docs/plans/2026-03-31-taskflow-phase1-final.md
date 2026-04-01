# TaskFlow Phase 1 (Final) — API Endpoints + Auth + Frontend CRUD

> **Reviewed by:** Claude Code agent (code-reviewer). 3 critical issues found and addressed.
> **Supersedes:** phase1-spec.md and phase1-revised.md

## Strategy Change: Extend Python API, Not NanoClaw Core

The earlier plan proposed adding an HTTP gateway inside NanoClaw (Option D). The reviewer found this:
- Requires modifying NanoClaw core (contradicts skill-only rule)
- The engine lives inside container images, not the main process
- Engine constructor has write side-effects (schema migration on every instantiation)

**Revised approach:** Extend the existing Python FastAPI (`main.py`) with PATCH/DELETE/comments endpoints. Simple SQLite writes with validation rules ported from the engine where needed. This:
- Works within existing deployment (no new servers)
- Respects "never modify NanoClaw core" rule
- Is pragmatically simpler for Phase 1 traffic levels

The NanoClaw HTTP gateway can be Phase 2 when complex engine operations (recurring cycling, delegation rollups) are needed from the web UI.

---

## Phase 1A: Fix Broken API Endpoints (BLOCKER)

**CRITICAL finding:** The frontend `api.ts` defines `updateTask`, `deleteTask`, `getComments`, `addComment` — but the Python API has NO corresponding endpoints. TaskDetailPanel edits, drag-and-drop, comments, and delete are ALL broken today. This must be fixed FIRST.

### New endpoints to add to `main.py`:

```python
# Task mutations
PATCH  /boards/{board_id}/tasks/{task_id}     # Update column, priority, assignee, due_date, title, description
DELETE /boards/{board_id}/tasks/{task_id}      # Delete task (or archive)

# Comments
GET    /boards/{board_id}/tasks/{task_id}/comments    # List comments (from task_history)
POST   /boards/{board_id}/tasks/{task_id}/comments    # Add comment (insert to task_history)
```

### Column-move semantics

The engine enforces a state machine (start, wait, resume, approve, etc.). For Phase 1 web UI:
- **Allow free-form column assignment** via PATCH `{ column: "next_action" }`
- Add basic validation: can't move to `done` if `requires_close_approval` is set and no approval exists
- Log all moves to `task_history` table
- Skip complex engine validation (WIP limits, recurring cycling, delegation rollups) — these are enforced via WhatsApp agent path
- Document this as a known limitation

### SQLite fix (prerequisite)

The Python API does NOT set WAL mode or busy_timeout on write connections. Add to `db_connection()`:

```python
def db_connection(*, read_only: bool = True):
    db_path = get_db_path()
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
```

### Task assignment for agents:
- **PB:** Add PATCH/DELETE/comments endpoints to main.py, fix WAL/busy_timeout
- **PF:** Nothing — frontend already has the client methods, they'll just start working
- **QA-E2E:** Validate each endpoint works end-to-end

---

## Phase 1B: WhatsApp OTP Authentication

### OTP delivery — revised approach

**Problem (found by reviewer):** The IPC authorization system blocks DMs to unknown phone numbers. New users signing up won't be in `external_contacts`. The OTP message will be silently dropped.

**Solution:** Create a new IPC message type `send_otp` with its own handler that bypasses the DM authorization check:

```typescript
// New file: src/ipc-plugins/send-otp.ts (TaskFlow skill, not NanoClaw core)
// Registered in ALLOWED_IPC_PLUGIN_FILES

export function handleOtpIpc(data: { phone: string; message: string }, channel: Channel) {
  const jid = `${data.phone.replace(/\D/g, '')}@s.whatsapp.net`;
  // Verify phone is on WhatsApp before sending
  const exists = await channel.sock.onWhatsApp(jid);
  if (!exists?.[0]?.exists) return { error: 'not_on_whatsapp' };
  await channel.sendMessage(jid, data.message, 'TaskFlow');
  return { sent: true };
}
```

IPC file format:
```json
{
  "type": "send_otp",
  "phone": "+5586999999999",
  "message": "Seu código TaskFlow: 123456"
}
```

The Python API writes this to `data/ipc/main/otp/{timestamp}.json`. The NanoClaw IPC watcher handles it via the plugin.

**This is a skill-level change** — the OTP plugin registers in the TaskFlow skill's IPC handler space, not NanoClaw core.

### Auth flow (unchanged from original spec)

```
POST /auth/request-otp     { phone: "+5586999999999" }
POST /auth/verify-otp      { phone: "+5586999999999", code: "123456" }
POST /auth/refresh          { refresh_token: "..." }
POST /auth/logout
GET  /auth/me
```

### Database tables (in taskflow.db)

```sql
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  phone TEXT UNIQUE NOT NULL,
  name TEXT,
  photo_url TEXT,
  language TEXT DEFAULT 'pt-BR',
  timezone TEXT DEFAULT 'America/Fortaleza',
  created_at TEXT DEFAULT (datetime('now')),
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS otp_requests (
  id TEXT PRIMARY KEY,
  phone TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  attempts INTEGER DEFAULT 0,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  refresh_token_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
```

### Security
- Max 5 OTP attempts per phone per 15 minutes
- OTP expires in 5 minutes
- JWT access token: 1 hour, refresh token: 7 days
- Phone number normalization using engine's existing `normalizePhone()` pattern

---

## Phase 1C: Organization Layer

Lightweight multi-tenancy (unchanged from original spec):

```sql
CREATE TABLE IF NOT EXISTS organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  icon_url TEXT,
  timezone TEXT DEFAULT 'America/Fortaleza',
  language TEXT DEFAULT 'pt-BR',
  created_by TEXT REFERENCES users(id),
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS org_members (
  org_id TEXT REFERENCES organizations(id),
  user_id TEXT REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'member',
  joined_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (org_id, user_id)
);

-- Add org_id to boards
-- Existing boards get a default org on migration
```

### API endpoints
```
POST   /orgs                     Create organization
GET    /orgs                     List user's orgs
GET    /orgs/:id                 Org details
PATCH  /orgs/:id                 Update org
GET    /orgs/:id/members         List members
POST   /orgs/:id/members         Invite (sends WhatsApp via OTP IPC)
```

---

## Phase 1D: Frontend Pages

### Login page
- Phone input with country code (default +55)
- "Send Code via WhatsApp" button
- 6-digit OTP input with countdown
- JWT stored in httpOnly cookie

### Profile page
- Edit name, photo, language, timezone
- Active sessions list

### Org management
- Org switcher in header
- Org creation wizard
- Member management (add/remove, roles)

### Board CRUD UI
- "New Board" dialog (name, template, timezone)
- Board settings expansion (edit columns, WIP, schedules)
- People panel "+" actually adds members

### Enhanced task editing
- Editable title and description in TaskDetailPanel
- Labels editor
- These now work because Phase 1A added the PATCH endpoint

---

## Development Rules

### NanoClaw Skill Architecture (CRITICAL)

NanoClaw (https://github.com/qwibitai/nanoclaw) is the upstream codebase. TaskFlow is a **skill** distributed as a git branch (`skill/taskflow`). ALL changes — including modifications to `src/index.ts`, `src/ipc.ts`, `container/agent-runner/src/*`, `src/taskflow-db.ts`, and any other NanoClaw file — MUST be committed to the `skill/taskflow` branch, NEVER directly to `main`.

**How it works:**
- `skill/taskflow` branch contains all TaskFlow-specific changes
- Install: `git fetch upstream skill/taskflow && git merge upstream/skill/taskflow`
- The skill branch CAN modify any file in the codebase (src/, container/, etc.)
- Upstream NanoClaw updates merge separately; conflicts resolved in the skill branch
- This ensures TaskFlow changes survive upstream updates

**Git workflow for every change:**
```bash
git checkout skill/taskflow
# make changes
git add . && git commit -m "feat(taskflow): description"
git checkout main && git merge skill/taskflow
npm run build
# deploy to production via deploy script
```

**NEVER:**
- Commit directly to `main` on the dev machine
- Push TaskFlow changes to `origin/main`
- Modify files on the production machine (.63) directly

### Machine Roles
- **.160** — development machine. All source code changes, builds, and testing happen here
- **.63** — production machine. Deploy TO here FROM .160 via deploy script. Never edit source here.
- **.60** — OpenClaw gateway. Agent workspaces (PF, PB, etc.) and MC backend. Frontend dev here.

### File Locations
- NanoClaw source + TaskFlow skill: `root@192.168.2.160:~/nanoclaw/` (skill/taskflow branch)
- TaskFlow API: deployed on .63 at `/home/nanoclaw/taskflow-api/main.py`
- TaskFlow Dashboard: PF workspace on .60, deployed to .63
- OTP IPC plugin: `src/ipc-plugins/send-otp.ts` (on skill/taskflow branch)
- IPC allowlist: `src/ipc.ts` line 56 `ALLOWED_IPC_PLUGIN_FILES` (on skill/taskflow branch)

---

## Task Split

| Phase | Task | Agent | Effort |
|-------|------|-------|--------|
| 1A | PATCH/DELETE/comments endpoints + WAL fix | PB | 1-2 days |
| 1A | Validate TaskDetailPanel/DnD/comments work | QA-E2E | 1 day |
| 1B | OTP IPC plugin (send-otp.ts) | PB | 1-2 days |
| 1B | Auth endpoints (request-otp, verify, refresh) | PB | 2-3 days |
| 1B | Login page + OTP flow | PF | 2-3 days |
| 1C | Org schema + CRUD endpoints | PB | 2-3 days |
| 1C | Org management UI | PF | 2-3 days |
| 1D | Profile page + board CRUD UI | PF | 2-3 days |
| 1D | Enhanced task editing | PF | 1-2 days |
| All | E2E testing across all phases | QA-E2E | ongoing |
| All | Schema review + API contracts | Architect | 1-2 days |

**Estimated total: 4-6 weeks** (revised from original 2-3 weeks per reviewer feedback)

---

## Gaps Filled (Codex review feedback)

### OTP IPC Plugin — VERIFIED FEASIBLE

Investigated on .160. The IPC plugin mechanism is well-defined:
- Plugins live in `src/ipc-plugins/` with `export function register(reg)` pattern
- `ALLOWED_IPC_PLUGIN_FILES` is a Set in `src/ipc.ts` — adding `send-otp.js` is a one-line change
- Plugin handler receives `deps.sendMessage(jid, text, sender)` — direct WhatsApp send, bypasses DM authorization
- Existing plugins: `create-group.js`, `provision-child-board.js`, `provision-root-board.js`

**One-line core change needed:** Add `'send-otp.js'` to `ALLOWED_IPC_PLUGIN_FILES` Set. Everything else is skill-level.

### Board CRUD / Member Management API

```
POST   /boards                            Create board (name, columns, template, timezone)
PATCH  /boards/{board_id}                 Update board (name, columns, wip_limit)
DELETE /boards/{board_id}                 Archive board

GET    /boards/{board_id}/members         List members
POST   /boards/{board_id}/members         Add member (person_id, name, phone, role)
DELETE /boards/{board_id}/members/{pid}   Remove member
PATCH  /boards/{board_id}/members/{pid}   Update role, wip_limit
```

Board creation writes to `boards`, `board_config`, `board_runtime_config`, `board_people` tables.
Does NOT provision WhatsApp groups — that remains via SKILL.md wizard for now.

### Org Invites (restored from original spec)

```sql
CREATE TABLE IF NOT EXISTS org_invites (
  id TEXT PRIMARY KEY,
  org_id TEXT REFERENCES organizations(id),
  phone TEXT NOT NULL,
  invited_by TEXT REFERENCES users(id),
  status TEXT DEFAULT 'pending',
  token TEXT UNIQUE NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL
);
```

```
POST   /orgs/:id/invites              Create invite (phone) → sends WhatsApp via OTP IPC
GET    /invites/:token                 Accept invite → joins org
```

### Session Security

- JWT access token in httpOnly cookie with `SameSite=Lax`
- CSRF: use `SameSite=Lax` cookie + check `Origin` header on mutations
- Refresh token rotation: each refresh issues a new refresh token, invalidates the old one
- WebSocket auth: pass JWT as query param on connect, verify on server, close on expiry
- Session revocation: delete from sessions table, refresh token becomes invalid

### Migration / Backfill Plan

When adding `org_id` to existing boards:
1. Create a default organization ("TaskFlow") owned by the first user (matched by phone to board admin)
2. Add `org_id TEXT REFERENCES organizations(id)` column to `boards` table
3. Backfill all existing boards with the default org ID
4. Add NOT NULL constraint after backfill
5. Add org_members entries for all existing board_people

### Free-form Column Moves — Scope Restriction

Web UI free-form column moves are RESTRICTED to:
- Task types: `simple`, `inbox` only
- Excluded from web moves: `recurring` (has cycle logic), tasks with `child_exec_enabled=1` (delegation), tasks with `requires_close_approval=1` (needs approval gate)
- The PATCH endpoint checks these conditions and returns 409 with explanation if violated
- WhatsApp path still uses full engine validation for all task types

### Timeline — revised to 5-7 weeks

Per Codex feedback, 5-7 weeks is more realistic. The biggest schedule risks are OTP integration and org/auth edge cases, not the CRUD routes.

---

## Known Limitations (Phase 1)

1. **Column moves restricted** — web UI only moves simple/inbox tasks. Recurring, delegated, approval-gated tasks can only be moved via WhatsApp.
2. **No recurring task management from web** — create/edit recurring tasks only via WhatsApp.
3. **No meeting management from web** — meetings only via WhatsApp.
4. **No file attachments** — no upload/storage infrastructure yet.
5. **Search only matches task IDs** — full-text search deferred to Phase 2.
6. **Single SQLite database** — sufficient for Phase 1 scale, PostgreSQL migration in Phase 2.
