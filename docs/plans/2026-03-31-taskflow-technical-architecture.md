# TaskFlow Technical Architecture

## Current Stack

```
┌─────────────────────────────────────────────────────┐
│ TaskFlow Dashboard (React 19 + TypeScript)           │
│ Port 3000 — Vite build, Tailwind, Radix UI           │
│ 192.168.2.63 (prod) / gateway .60 (dev)              │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP + WebSocket
┌──────────────────────▼──────────────────────────────┐
│ TaskFlow API (FastAPI/Python)                         │
│ Port 8100 — REST + WebSocket                         │
│ 192.168.2.63 (prod)                                  │
│ Reads/writes: data/taskflow/taskflow.db              │
│ Writes: store/messages.db (for agent pipeline)        │
└──────────────────────┬──────────────────────────────┘
                       │ Shared SQLite files
┌──────────────────────▼──────────────────────────────┐
│ NanoClaw (Node.js)                                    │
│ 192.168.2.63 (prod) / 192.168.2.160 (dev)            │
│ WhatsApp channel, agent containers, IPC, scheduling   │
│ Polls: store/messages.db                              │
│ Reads/writes: data/taskflow/taskflow.db               │
└─────────────────────────────────────────────────────┘
```

## Target Architecture (Phase 1+)

```
┌─────────────────────────────────────────────────────┐
│ Landing Page (static, same React app or separate)     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ TaskFlow Dashboard (React 19)                         │
│ + Auth context (JWT)                                  │
│ + Org context (multi-tenant)                          │
│ + Protected routes                                    │
│ + Login/OTP pages                                     │
│ + Settings/Profile/Org pages                          │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP + WebSocket + JWT
┌──────────────────────▼──────────────────────────────┐
│ TaskFlow API (FastAPI)                                │
│ + JWT auth middleware                                 │
│ + /auth/* (OTP, verify, refresh)                      │
│ + /orgs/* (CRUD, members, invites)                    │
│ + /users/* (profile)                                  │
│ + /boards/* (CRUD, expanded from current)             │
│ + /tasks/* (expanded)                                 │
│ + /chat/* (existing board chat)                       │
│                                                       │
│ Database: SQLite (Phase 1) → PostgreSQL (Phase 2+)    │
│ OTP delivery: via NanoClaw WhatsApp IPC               │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ NanoClaw (unchanged core)                             │
│ + TaskFlow skill branch (all customizations)          │
│ WhatsApp channel for OTP + notifications + agent chat │
└─────────────────────────────────────────────────────┘
```

## Database Migration Path

### Phase 1: SQLite (enhanced)
- Add users, organizations, sessions tables to taskflow.db
- Single-file, works with current deployment
- Sufficient for single-server, moderate concurrency
- WAL mode + busy_timeout for concurrent access

### Phase 2: PostgreSQL
- Migrate when concurrent writes become a bottleneck
- Or when multi-server deployment is needed
- Use Alembic for migrations
- PostgreSQL on 192.168.2.66 (already running MC database)

### Phase 3: Full Stack
- Redis: sessions, rate limiting, presence, pub/sub
- S3: file attachments, user photos
- Background queue: notifications, digests, automations

## Auth Flow Detail

```
User                    Frontend              API                 NanoClaw
 │                         │                    │                     │
 │ enters phone            │                    │                     │
 │────────────────────────>│                    │                     │
 │                         │ POST /auth/otp     │                     │
 │                         │───────────────────>│                     │
 │                         │                    │ generate OTP        │
 │                         │                    │ store hash+expiry   │
 │                         │                    │ write IPC file      │
 │                         │                    │────────────────────>│
 │                         │                    │                     │ send WhatsApp msg
 │                         │   200 OK           │                     │ "Code: 123456"
 │                         │<───────────────────│                     │
 │ receives WhatsApp msg   │                    │                     │
 │<────────────────────────────────────────────────────────────────────│
 │                         │                    │                     │
 │ enters code             │                    │                     │
 │────────────────────────>│                    │                     │
 │                         │ POST /auth/verify  │                     │
 │                         │───────────────────>│                     │
 │                         │                    │ verify hash         │
 │                         │                    │ create/find user    │
 │                         │                    │ issue JWT           │
 │                         │  { jwt, refresh }  │                     │
 │                         │<───────────────────│                     │
 │                         │ store in cookie    │                     │
 │                         │ redirect to app    │                     │
```

## Deployment

### NanoClaw Skill Architecture

NanoClaw (https://github.com/qwibitai/nanoclaw) is the upstream codebase. TaskFlow is a **skill** — a git branch (`skill/taskflow`) that merges into the codebase.

**ALL changes** to NanoClaw files (src/index.ts, src/ipc.ts, container/*, src/taskflow-db.ts, etc.) MUST be committed to `skill/taskflow`, never directly to `main`. The skill branch CAN modify any file — the key is branch discipline, not file restrictions.

```
upstream/main (NanoClaw core updates)
     │
     ├── skill/taskflow (ALL TaskFlow changes)
     │     ├── src/taskflow-db.ts (schema)
     │     ├── src/index.ts (trigger bypass, output routing)
     │     ├── src/ipc.ts (OTP plugin allowlist)
     │     ├── src/ipc-plugins/send-otp.ts (new)
     │     ├── container/agent-runner/src/ipc-mcp-stdio.ts (MCP tools)
     │     └── container/agent-runner/src/runtime-config.ts (env vars)
     │
     └── main (local) = merge of upstream + skill/taskflow
```

### Development (.160)
- NanoClaw source on `skill/taskflow` branch
- All changes committed to skill branch
- Build and test here
- Deploy to production via deploy script

### Production (.63)
- NanoClaw runtime (systemd user service)
- TaskFlow API (systemd service, port 8100)
- TaskFlow Dashboard (built static)
- Deploy FROM .160 only — never edit source here

### Gateway (.60)
- OpenClaw Mission Control (manages the agent team)
- Agent workspaces (PF, PB, QA, etc.)
- Chrome MCP for browser testing

## Security Considerations

- OTP brute force protection: max 5 attempts per phone per 15 min
- JWT: short-lived access (1h), long-lived refresh (7d)
- CORS: restrict to known origins
- Rate limiting: per IP and per user
- Input validation: all endpoints
- SQL injection: parameterized queries (already used)
- XSS: React auto-escapes, CSP headers
- Multi-tenant isolation: all queries scoped by org_id
