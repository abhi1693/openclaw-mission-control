# TaskFlow Product Pages Spec

## Landing Page

### Hero Section
- Headline: "Gerencie tarefas com IA via WhatsApp" (or English variant)
- Sub: "A plataforma GTD que funciona onde sua equipe já está"
- CTA: "Começar com WhatsApp" → login flow
- Hero image: animated screenshot of board + WhatsApp side by side

### Features Section
- **Kanban Board** — drag-and-drop, multiple views, real-time sync
- **WhatsApp Integration** — create tasks, get updates, talk to AI from WhatsApp
- **AI Assistant** — natural language commands, smart suggestions, meeting → tasks
- **Team Collaboration** — organizations, boards, roles, permissions
- **Board Chat** — real-time chat with AI directly in the dashboard

### How It Works
1. Sign in with your WhatsApp number
2. Create your organization and invite your team
3. Create boards, add tasks, assign work
4. Get AI assistance via WhatsApp or Board Chat

### Social Proof / Stats
- Number of tasks managed, teams using it, messages processed

### Footer
- Links: About, Privacy, Terms, API Docs, Support
- Language switcher (pt-BR / en-US)

---

## Login Page

### Layout
- Clean centered card on gradient background
- TaskFlow logo + tagline
- Phone number input with country flag selector (default: +55 Brazil)
- "Send Code via WhatsApp" button (green, WhatsApp style)
- After code sent: 6-digit OTP input with countdown timer
- "Resend Code" link (enabled after 60s)
- Link to landing page / about

### States
1. **Phone input** — enter number, click send
2. **Code sent** — show "Code sent to +55 86 99999-9999", 6-digit input
3. **Verifying** — spinner
4. **Error** — "Invalid code, try again" / "Number not found"
5. **Success** — redirect to dashboard or onboarding

---

## Onboarding Wizard (first login)

### Step 1: Profile
- Name (pre-filled from WhatsApp if available)
- Photo (optional upload or WhatsApp photo)

### Step 2: Organization
- "Create new organization" or "Join existing" (if they have an invite)
- Org name, timezone selector

### Step 3: First Board
- Board name
- Template selector (GTD / Kanban / Scrum / Empty)
- "Invite team" — add phone numbers

### Step 4: Done
- "Your board is ready!"
- "Talk to the AI assistant" → opens board chat
- Quick tutorial: "Try saying: create a task to fix the login page"

---

## Settings Pages

### User Settings (/settings/profile)
- Name, photo, phone (read-only), language, timezone
- Notification preferences (per type toggle)
- Active sessions (list, revoke)
- Delete account

### Organization Settings (/settings/org)
- Name, slug, logo
- Timezone, language
- Member management (list, invite, roles, remove)
- Invite link management
- Danger zone: transfer ownership, delete org

### Board Settings (/boards/:id/settings)
- Board name, description
- Column configuration (add/remove/reorder)
- WIP limits per column
- Board members (add/remove from org members)
- Standup/digest/review schedules
- Automation rules (future)
- Archive/delete board
