# TaskFlow Phase 1: Foundation — Auth + Multi-tenancy

> **Prerequisite:** Read `docs/plans/2026-03-31-taskflow-product-roadmap.md` for full context.

**Goal:** Users log in with WhatsApp, create organizations, invite team, create/manage boards.

**Timeline estimate:** 2-3 weeks with current agent team.

---

## 1.1 WhatsApp OTP Authentication

### User Flow
```
1. User opens TaskFlow → sees login page
2. Enters phone number (with country code picker)
3. Clicks "Send Code"
4. API generates 6-digit OTP, stores hash + expiry (5 min)
5. NanoClaw sends OTP via WhatsApp: "Your TaskFlow code: 123456"
6. User enters code on web form
7. API verifies → issues JWT (access + refresh tokens)
8. User is redirected to dashboard
```

### API Endpoints
```
POST /auth/request-otp     { phone: "+5586999999999" }
POST /auth/verify-otp      { phone: "+5586999999999", code: "123456" }
POST /auth/refresh          { refresh_token: "..." }
POST /auth/logout           (invalidate session)
GET  /auth/me               (current user profile)
```

### Database Schema (taskflow.db)
```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  phone TEXT UNIQUE NOT NULL,
  name TEXT,
  photo_url TEXT,
  language TEXT DEFAULT 'pt-BR',
  timezone TEXT DEFAULT 'America/Fortaleza',
  created_at TEXT DEFAULT (datetime('now')),
  last_login_at TEXT
);

CREATE TABLE otp_requests (
  id TEXT PRIMARY KEY,
  phone TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  verified INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  refresh_token_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
```

### WhatsApp OTP Delivery
- Use NanoClaw's existing `send_message` IPC mechanism
- API writes OTP message to `data/ipc/main/messages/otp-{timestamp}.json`
- NanoClaw sends via WhatsApp channel to the phone number
- OR: use the board chat `_inject_message_for_agent` pattern adapted for DMs

### JWT Structure
```json
{
  "sub": "user-uuid",
  "phone": "+5586999999999",
  "name": "Miguel Oliveira",
  "orgs": ["org-uuid-1"],
  "iat": 1774900000,
  "exp": 1774986400
}
```

### Frontend
- Login page: phone input + country code picker + "Send Code" button
- OTP verification: 6-digit input with auto-focus
- Loading states, error handling, retry timer (60s)
- Store JWT in httpOnly cookie (not localStorage)
- Protected routes: redirect to login if no valid session

---

## 1.2 User Profile

### API Endpoints
```
GET    /users/me                (current user)
PATCH  /users/me                { name, photo_url, language, timezone }
```

### Frontend
- Profile page accessible from header avatar dropdown
- Edit name, upload photo, select language, select timezone
- Changes reflect immediately across the app

---

## 1.3 Organization Spaces

### Data Model
```sql
CREATE TABLE organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  icon_url TEXT,
  timezone TEXT DEFAULT 'America/Fortaleza',
  language TEXT DEFAULT 'pt-BR',
  created_by TEXT REFERENCES users(id),
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE org_members (
  org_id TEXT REFERENCES organizations(id),
  user_id TEXT REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'member',  -- owner, admin, member, viewer
  joined_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE org_invites (
  id TEXT PRIMARY KEY,
  org_id TEXT REFERENCES organizations(id),
  phone TEXT NOT NULL,
  invited_by TEXT REFERENCES users(id),
  status TEXT DEFAULT 'pending',  -- pending, accepted, expired
  created_at TEXT DEFAULT (datetime('now')),
  expires_at TEXT
);
```

### API Endpoints
```
POST   /orgs                    { name, slug }
GET    /orgs                    (list user's orgs)
GET    /orgs/:id                (org details)
PATCH  /orgs/:id                { name, icon_url, timezone }
DELETE /orgs/:id                (owner only)

GET    /orgs/:id/members        (list members)
POST   /orgs/:id/members        { phone, role }  (invite)
PATCH  /orgs/:id/members/:uid   { role }
DELETE /orgs/:id/members/:uid   (remove)

POST   /orgs/:id/invites        { phone }
GET    /invites/:token           (accept invite link)
```

### Invite Flow
1. Owner clicks "Invite" → enters phone number
2. API creates invite + sends WhatsApp message with link
3. Recipient clicks link → auto-verifies phone → joins org
4. If recipient has no account, the link triggers the OTP flow first

### Frontend
- Org selector in header (switch between orgs)
- Org creation wizard: name → slug → invite members
- Org settings page: name, logo, timezone, members list
- Member management: add/remove, change roles

---

## 1.4 Board CRUD

### Changes to Existing Schema
```sql
-- Add org_id to boards table
ALTER TABLE boards ADD COLUMN org_id TEXT REFERENCES organizations(id);

-- Board permissions
CREATE TABLE board_members (
  board_id TEXT REFERENCES boards(id),
  user_id TEXT REFERENCES users(id),
  role TEXT DEFAULT 'member',  -- admin, member, viewer
  PRIMARY KEY (board_id, user_id)
);
```

### API Endpoints
```
POST   /orgs/:id/boards          { name, columns, wip_limit, template }
GET    /orgs/:id/boards           (list org boards)
PATCH  /boards/:id                { name, columns, wip_limit, language, timezone }
DELETE /boards/:id                (archive)

GET    /boards/:id/members        (list board members)
POST   /boards/:id/members        { user_id, role }
DELETE /boards/:id/members/:uid
```

### Board Templates
```json
{
  "gtd": ["inbox", "next_action", "in_progress", "waiting", "review", "done"],
  "kanban": ["backlog", "todo", "in_progress", "review", "done"],
  "scrum": ["backlog", "sprint_backlog", "in_progress", "testing", "done"],
  "custom": []
}
```

### Frontend
- "New Board" button on dashboard
- Board creation dialog: name, template, invite members
- Board settings: expanded from current Board Config panel
- Board archive/delete in settings

---

## 1.5 Member Management on Boards

### Frontend Changes
- People panel "+" button opens "Add Member" dialog
- Search org members by name/phone
- Assign role (admin/member/viewer)
- Remove member (admin only)
- The People panel becomes the member management hub

### NanoClaw Integration
- New board members get added to `board_people` in taskflow.db
- NanoClaw creates WhatsApp group if needed (existing skill capability)
- New members receive WhatsApp notification: "You were added to board X"

---

## File Structure

### New Files (TaskFlow API)
```
taskflow-api/
  auth.py              — OTP, JWT, session management
  models.py            — User, Organization, OrgMember, etc.
  middleware.py         — JWT auth middleware (replace simple token)
  routes/
    auth.py            — /auth/* endpoints
    orgs.py            — /orgs/* endpoints
    users.py           — /users/* endpoints
    boards.py          — /boards/* CRUD (expand current)
```

### New Files (TaskFlow Dashboard)
```
taskflow-dashboard/src/
  pages/
    Login.tsx          — phone input + OTP verification
    Profile.tsx        — user profile editor
    OrgSettings.tsx    — organization settings + member management
    OrgSelector.tsx    — org switcher in header
    NewBoard.tsx       — board creation wizard
  components/
    AuthProvider.tsx   — JWT context, protected routes
    PhoneInput.tsx     — country code + phone number input
    OTPInput.tsx       — 6-digit code input
    OrgSwitcher.tsx    — dropdown in header
    InviteDialog.tsx   — invite member via phone
    MemberList.tsx     — manage org/board members
  hooks/
    useAuth.ts         — login/logout/refresh
    useOrg.ts          — current org context
  lib/
    auth.ts            — JWT storage, refresh logic
```

### Modified Files
```
taskflow-api/
  main.py              — add auth middleware, mount new routers
taskflow-dashboard/src/
  App.tsx              — add AuthProvider, protected routes, org context
  components/Layout.tsx — add org switcher to header
  components/PeoplePanel.tsx — make "+" functional (add member)
  pages/BoardDetail.tsx — add board settings CRUD
  pages/Dashboard.tsx   — filter boards by org
```

---

## Migration Notes

- Phase 1 can still use SQLite — single-file, no PostgreSQL needed yet
- JWT auth replaces the current `TASKFLOW_API_TOKEN` bearer token
- Existing boards need `org_id` backfilled (create a default org for existing data)
- The current `board_people` table maps to `board_members` with user references
- NanoClaw's WhatsApp groups remain the source of truth for board membership; the web UI adds a management layer on top

---

## Development Approach

### All work follows NanoClaw skill pattern:
- Frontend changes: TaskFlow Dashboard (PF workspace on gateway)
- API changes: TaskFlow API skill branch on dev machine (.160)
- Deploy to production (.63) via deploy script
- Never modify NanoClaw core codebase directly

### Suggested task split for agents:
- **PB:** Auth API (OTP, JWT, sessions), Org/User/Board CRUD endpoints
- **PF:** Login page, OTP flow, org management UI, board CRUD UI
- **Architect:** Schema design review, API contract specs
- **QA-E2E:** Auth flow E2E, multi-tenant isolation testing
