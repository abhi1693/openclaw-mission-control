# TaskFlow Product Roadmap

> **Purpose:** Expand TaskFlow Dashboard from a single-board kanban viewer into a full multi-tenant GTD platform with WhatsApp authentication, organization spaces, and AI assistant integration.

**Current state:** React 19 SPA + NanoClaw backend + WhatsApp channel + Board Chat. No auth, single-tenant, read-mostly.

**Target:** Production SaaS product accessible at a public URL with self-service onboarding.

---

## Phase 1: Foundation (Auth + Multi-tenancy)

**Goal:** Users can log in, create organizations, and manage boards — the minimum viable multi-user product.

### 1.1 WhatsApp OTP Authentication
- **Login flow:** Enter phone number → receive 6-digit code via WhatsApp → verify → session created
- **How it works:** NanoClaw already has WhatsApp channel. The API sends an OTP message via the existing `send_message` IPC, user enters the code on the web form, API verifies and issues a JWT.
- **Session:** JWT stored in httpOnly cookie, 7-day expiry, refresh token
- **No passwords:** WhatsApp number is the identity. Phone number = user ID.
- **Files:** New `auth.py` module in TaskFlow API, login/verify endpoints, JWT middleware

### 1.2 User Profile
- Name, phone (from WhatsApp), photo (optional), preferred language, timezone
- Profile page: edit name, photo, language, timezone
- First login: auto-create user from WhatsApp contact info

### 1.3 Organization Spaces
- Create organization (name, logo/icon, timezone, language)
- Organization roles: owner, admin, member, viewer
- Invite flow: owner sends WhatsApp invite link → recipient clicks → auto-joins org
- Organization settings page
- Each org has its own boards, members, settings

### 1.4 Board CRUD
- Create board (name, columns, WIP limits) from the UI
- Edit board settings (currently read-only Board Config panel)
- Archive/delete board
- Board permissions: who can view/edit within the org
- Board templates: GTD (default), Kanban, Scrum, Custom

### 1.5 User/Member Management
- Add/remove members from organization
- Add/remove members from board (the People panel becomes editable)
- Role assignment per board (admin, member, viewer)
- The "+" button on People panel actually works (currently placeholder)

**Deliverable:** Users log in with WhatsApp, create an org, invite team, create boards, manage members.

---

## Phase 2: Task Power Features

**Goal:** Make task management rich enough to replace standalone tools.

### 2.1 Rich Task Editor
- Markdown description editor (not just plain text)
- File attachments (images, documents) stored in object storage
- Subtasks / checklists within a task
- Task comments with @mentions
- Task activity log (who changed what, when)

### 2.2 Task Dependencies
- Visual dependency links between tasks
- Blocked indicator (already exists) with dependency chain view
- Drag to create dependency
- Auto-block downstream tasks

### 2.3 Recurring Tasks UI
- Create/edit recurring tasks from the UI (currently only via WhatsApp/agent)
- Visual recurrence indicator on cards
- Skip/snooze occurrence
- Recurrence history

### 2.4 Labels & Filters
- Custom labels per board (color + name)
- Filter by label, priority, assignee, due date range
- Saved filters (custom views)
- Quick filter chips above kanban

### 2.5 Bulk Operations
- Multi-select tasks (shift+click, checkbox mode)
- Bulk move, assign, prioritize, label
- Bulk archive/delete

**Deliverable:** Tasks have rich content, dependencies, recurrence, and filtering.

---

## Phase 3: Views & Productivity

**Goal:** Multiple ways to see and interact with work.

### 3.1 Calendar View
- Tasks plotted on a calendar by due date
- Drag to reschedule
- Day/week/month views
- Meetings shown inline (already in NanoClaw data)

### 3.2 My Tasks View
- Cross-board personal task list
- "Today", "This week", "Overdue" sections
- Quick actions (complete, snooze, reassign)

### 3.3 Timeline / Gantt
- Tasks on a horizontal timeline
- Dependencies shown as arrows
- Drag to adjust dates
- Critical path highlighting

### 3.4 Dashboard Analytics
- Personal velocity (tasks completed per week)
- Team workload (tasks per person, capacity)
- Cycle time (avg time from inbox → done)
- Overdue trend
- Board health score

### 3.5 Search
- Global search across all boards/tasks/comments
- Full-text search with filters
- Search results grouped by board
- Recent searches

**Deliverable:** Users can view work in calendar, timeline, and personal dashboard modes.

---

## Phase 4: Communication & Notifications

**Goal:** Keep everyone informed without leaving the app.

### 4.1 Notification Center
- In-app notification list (expand current bell icon)
- Notification types: assigned, mentioned, due soon, overdue, comment, status change
- Mark read/unread, dismiss
- Notification preferences (per type: in-app, WhatsApp, email)

### 4.2 WhatsApp Notifications
- Assignment notifications via WhatsApp
- Due date reminders (1 day before, on due date, overdue)
- @mention alerts
- Configurable per user (opt in/out per type)

### 4.3 Email Integration
- Daily digest email (configurable)
- Weekly review email
- Direct reply to email → creates task comment

### 4.4 Board Chat Enhancements
- Thread replies (reply to specific message)
- @mention with autocomplete
- File/image sharing in chat
- Message reactions (emoji)
- Pin important messages

**Deliverable:** Users never miss important updates via their preferred channel.

---

## Phase 5: AI Assistant & Automation

**Goal:** AI that works alongside humans, not just responds to queries.

### 5.1 Natural Language Commands
- "Create a task: fix the login page, assign to Alexandre, high priority"
- "Move T40 to next action"
- "What's overdue?" (already works via board chat)
- "Summarize this week's progress"
- Context-aware: agent knows which board you're on

### 5.2 Smart Suggestions
- Suggest task priorities based on due dates and dependencies
- Suggest assignments based on team workload
- Suggest task breakdown (large task → subtasks)
- "This task has been in progress for 5 days — want to check in?"

### 5.3 Meeting → Tasks
- Send meeting notes via WhatsApp or chat
- Agent extracts action items and creates tasks
- Assigns based on who was mentioned
- Links back to the meeting

### 5.4 Custom Automations
- Rule builder: When [trigger] → Do [action]
- Triggers: task created, moved, overdue, assigned, commented
- Actions: send WhatsApp, move task, assign, create subtask, notify
- Templates: "When task moves to done, notify the creator via WhatsApp"

### 5.5 WhatsApp ↔ Web Seamless
- Same conversation visible in both WhatsApp and Board Chat
- Reply from either channel, history shared
- Agent responds to whichever channel the user is on

**Deliverable:** AI assistant that proactively helps manage work.

---

## Phase 6: Product & Growth

**Goal:** Make it a real product people can discover and adopt.

### 6.1 Landing Page
- Value proposition: "GTD task management with WhatsApp AI assistant"
- Feature highlights with screenshots
- "Get Started" → WhatsApp login
- Demo board (public read-only)
- Pricing page (if SaaS)

### 6.2 Onboarding Flow
- First-time wizard: create org → invite team → create first board
- Sample board with example tasks
- Tooltips and guided tour
- "Talk to the assistant" prompt in board chat

### 6.3 PWA / Mobile
- Progressive Web App (installable)
- Mobile-responsive layouts (current is desktop-first)
- Push notifications
- Offline support (cached board data)

### 6.4 API & Integrations
- Public REST API with documentation
- Webhook support (outgoing events)
- Zapier / n8n integration
- GitHub integration (issues ↔ tasks)
- Google Calendar sync

### 6.5 Admin & Billing
- Super admin dashboard (all orgs, usage stats)
- Usage limits per plan
- Billing integration (Stripe)
- Plan management (free, pro, enterprise)

**Deliverable:** Public product with onboarding, mobile support, and integrations.

---

## Technical Architecture

### Current Stack
- **Frontend:** React 19 + TypeScript + Tailwind + Radix UI + TanStack
- **Backend API:** FastAPI (Python) — TaskFlow API on port 8100
- **Agent Engine:** NanoClaw (Node.js) — WhatsApp, agent containers, SQLite
- **Database:** SQLite (taskflow.db + messages.db)
- **Real-time:** WebSocket
- **Deployment:** 192.168.2.160 (dev) → 192.168.2.63 (prod)

### Needed for Full Product
- **Database migration:** SQLite → PostgreSQL for multi-tenancy and concurrent writes
- **Object storage:** S3-compatible for file attachments
- **Auth:** JWT with WhatsApp OTP verification
- **Caching:** Redis for sessions, presence, rate limiting
- **Queue:** Background jobs for notifications, digests, automations
- **CDN:** Static assets, images
- **Domain + TLS:** Public URL with HTTPS

### Migration Path
1. Phase 1 can still use SQLite (single-tenant + auth layer on top)
2. Phase 2 requires PostgreSQL migration (concurrent writes, relations)
3. Phase 3+ requires the full stack

---

## Priority Matrix

| Phase | Effort | Impact | Dependency |
|-------|--------|--------|------------|
| 1.1 WhatsApp OTP Auth | Medium | Critical | NanoClaw WhatsApp channel |
| 1.3 Organizations | Medium | Critical | Auth |
| 1.4 Board CRUD | Low | High | Organizations |
| 1.5 Member Management | Low | High | Organizations |
| 2.1 Rich Task Editor | Medium | High | None |
| 2.4 Labels & Filters | Low | High | None |
| 3.2 My Tasks View | Low | High | Auth |
| 4.1 Notification Center | Medium | High | Auth |
| 5.1 NL Commands | Low | Medium | Board Chat (done) |
| 6.1 Landing Page | Low | Medium | None |

**Recommended start:** Phase 1 (auth + org + CRUD) in parallel with 2.1 (rich tasks) and 6.1 (landing page).
