# Mission Control (MC1) — API Skill Reference

> **Version:** 0.1.0  
> **Base URL:** `http://localhost:8000`  
> **API Prefix:** `/api/v1`  
> **Generated:** 2026-03-21  
> **Total Endpoints:** 142

---

## Table of Contents

1. [Authentication](#authentication)
2. [Common Patterns](#common-patterns)
3. [Health](#health)
4. [Auth Bootstrap](#auth-bootstrap)
5. [Organizations](#organizations)
6. [Users](#users)
7. [Gateways (Admin)](#gateways-admin)
8. [Gateway Sessions](#gateway-sessions)
9. [Boards](#boards)
10. [Board Memory](#board-memory)
11. [Board Webhooks](#board-webhooks)
12. [Board Onboarding](#board-onboarding)
13. [Board Groups](#board-groups)
14. [Board Group Memory](#board-group-memory)
15. [Agents (Admin)](#agents-admin)
16. [Agent API (Agent-Scoped)](#agent-api-agent-scoped)
17. [Tasks](#tasks)
18. [Approvals](#approvals)
19. [Tags](#tags)
20. [Custom Fields](#custom-fields)
21. [Activity](#activity)
22. [Metrics](#metrics)
23. [Skills Marketplace](#skills-marketplace)
24. [Souls Directory](#souls-directory)
25. [SSE Streaming](#sse-streaming)
26. [Error Handling](#error-handling)
27. [Rate Limits](#rate-limits)
28. [Endpoint Index](#endpoint-index)

---

## Authentication

MC1 supports two auth modes controlled by `AUTH_MODE`:

### Local Mode (`AUTH_MODE=local`)

All protected endpoints require a bearer token:

```http
Authorization: Bearer <LOCAL_AUTH_TOKEN>
```

### Clerk Mode (`AUTH_MODE=clerk`)

Uses Clerk JWT authentication with `CLERK_SECRET_KEY`.

### Agent Authentication

Autonomous agents authenticate via:

```http
X-Agent-Token: <agent-token>
```

On shared user/agent routes, the backend also accepts `Authorization: Bearer <agent-token>` as fallback after user auth fails.

**Rate limit:** Agent auth is limited to **20 requests per 60 seconds per IP**.

### Auth Constants

```
TOKEN=XI76ghKT9r4lzfHpxCjY32u8EytS0eLnWqUcsbRaJPMQwZ1ANFvGVmdkBOio5D
BASE=http://localhost:8000/api/v1
```

---

## Common Patterns

### Pagination

List endpoints return paginated responses:

```json
{
  "items": [...],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

**Query parameters:** `limit` (default 50), `offset` (default 0).

### Request IDs

Every response includes `X-Request-Id`. Clients may supply their own.

### Security Headers

All responses include:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`

### CORS

Exposed headers: `X-Total-Count`, `X-Limit`, `X-Offset`.

### Common Response Model: `OkResponse`

```json
{ "ok": true }
```

Used by DELETE and action endpoints.

### UUID Format

All IDs are UUID v4 strings: `"11111111-1111-1111-1111-111111111111"`.

---

## Health

Health probes do **not** require authentication.

### 1. `GET /health` — Liveness Check

```bash
curl http://localhost:8000/health
```

**Response:** `{"ok": true}`

### 2. `GET /healthz` — Liveness Alias

```bash
curl http://localhost:8000/healthz
```

**Response:** `{"ok": true}`

### 3. `GET /readyz` — Readiness Check

```bash
curl http://localhost:8000/readyz
```

**Response:** `{"ok": true}`

---

## Auth Bootstrap

### 4. `POST /api/v1/auth/bootstrap` — Resolve Caller Identity

Resolves the authenticated user from the bearer token. No request body.

**Auth:** User bearer token  
**Response:** `UserRead`

```bash
curl -s -X POST "$BASE/auth/bootstrap" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "id": "uuid",
  "clerk_user_id": "user_2abcXYZ",
  "email": "alex@example.com",
  "name": "Alex Chen",
  "preferred_name": "Alex",
  "pronouns": "they/them",
  "timezone": "America/Los_Angeles",
  "notes": "Primary operator",
  "context": "Handles incident coordination",
  "is_super_admin": false
}
```

**Errors:** `401` if not a user actor.

---

## Organizations

All organization endpoints require user authentication. Admin endpoints require org admin role.

### 5. `POST /api/v1/organizations` — Create Organization

**Auth:** User  
**Body:**
```json
{ "name": "My Org" }
```

**Response:** `OrganizationRead` — Caller becomes owner.

```bash
curl -s -X POST "$BASE/organizations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Org"}'
```

**Errors:** `409` if name already exists, `422` if empty name.

### 6. `GET /api/v1/organizations/me/list` — List My Organizations

**Auth:** User

```bash
curl -s "$BASE/organizations/me/list" -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
[
  {
    "id": "uuid",
    "name": "My Org",
    "role": "owner",
    "is_active": true
  }
]
```

### 7. `PATCH /api/v1/organizations/me/active` — Set Active Organization

**Auth:** User  
**Body:**
```json
{ "organization_id": "uuid" }
```

```bash
curl -s -X PATCH "$BASE/organizations/me/active" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"organization_id":"<org-id>"}'
```

### 8. `GET /api/v1/organizations/me` — Get Active Organization

**Auth:** Org member

```bash
curl -s "$BASE/organizations/me" -H "Authorization: Bearer $TOKEN"
```

### 9. `DELETE /api/v1/organizations/me` — Delete Active Organization

**Auth:** Org owner only  
Deletes the entire organization and all dependent entities (boards, tasks, agents, etc.).

```bash
curl -s -X DELETE "$BASE/organizations/me" -H "Authorization: Bearer $TOKEN"
```

**Errors:** `403` if not owner.

### 10. `GET /api/v1/organizations/me/member` — Get My Membership

**Auth:** Org member  
Returns the caller's membership record including board access entries.

```bash
curl -s "$BASE/organizations/me/member" -H "Authorization: Bearer $TOKEN"
```

### 11. `GET /api/v1/organizations/me/members` — List Members (Paginated)

**Auth:** Org member

```bash
curl -s "$BASE/organizations/me/members?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

### 12. `GET /api/v1/organizations/me/members/{member_id}` — Get Member

**Auth:** Org member (admin can view any, non-admin only self)

```bash
curl -s "$BASE/organizations/me/members/<member-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 13. `PATCH /api/v1/organizations/me/members/{member_id}` — Update Member Role

**Auth:** Org admin  
**Body:**
```json
{ "role": "admin" }
```

Roles: `owner`, `admin`, `member`.

```bash
curl -s -X PATCH "$BASE/organizations/me/members/<member-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role":"admin"}'
```

### 14. `PUT /api/v1/organizations/me/members/{member_id}/access` — Update Member Board Access

**Auth:** Org admin  
**Body:**
```json
{
  "all_boards_read": false,
  "all_boards_write": false,
  "board_access": [
    { "board_id": "uuid", "can_read": true, "can_write": true }
  ]
}
```

```bash
curl -s -X PUT "$BASE/organizations/me/members/<member-id>/access" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"all_boards_read":true,"all_boards_write":true,"board_access":[]}'
```

### 15. `DELETE /api/v1/organizations/me/members/{member_id}` — Remove Member

**Auth:** Org admin. Cannot remove self. Cannot remove last owner.

```bash
curl -s -X DELETE "$BASE/organizations/me/members/<member-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 16. `GET /api/v1/organizations/me/invites` — List Pending Invites (Paginated)

**Auth:** Org admin

```bash
curl -s "$BASE/organizations/me/invites" -H "Authorization: Bearer $TOKEN"
```

### 17. `POST /api/v1/organizations/me/invites` — Create Invite

**Auth:** Org admin  
**Body:**
```json
{
  "invited_email": "user@example.com",
  "role": "member",
  "all_boards_read": true,
  "all_boards_write": false,
  "board_access": []
}
```

```bash
curl -s -X POST "$BASE/organizations/me/invites" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"invited_email":"user@example.com","role":"member","all_boards_read":true,"all_boards_write":false,"board_access":[]}'
```

**Errors:** `409` if user already a member.

### 18. `DELETE /api/v1/organizations/me/invites/{invite_id}` — Revoke Invite

**Auth:** Org admin

```bash
curl -s -X DELETE "$BASE/organizations/me/invites/<invite-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 19. `POST /api/v1/organizations/invites/accept` — Accept Invite

**Auth:** User  
**Body:**
```json
{ "token": "<invite-token>" }
```

```bash
curl -s -X POST "$BASE/organizations/invites/accept" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token":"<invite-token>"}'
```

**Errors:** `403` if email mismatch, `404` if token invalid.

---

## Users

### 20. `GET /api/v1/users/me` — Get My Profile

**Auth:** User

```bash
curl -s "$BASE/users/me" -H "Authorization: Bearer $TOKEN"
```

**Response:** `UserRead` (same as bootstrap).

### 21. `PATCH /api/v1/users/me` — Update My Profile

**Auth:** User  
**Body (all fields optional):**
```json
{
  "name": "Alex Chen",
  "preferred_name": "Alex",
  "pronouns": "they/them",
  "timezone": "America/Los_Angeles",
  "notes": "...",
  "context": "..."
}
```

```bash
curl -s -X PATCH "$BASE/users/me" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"preferred_name":"Alex","timezone":"Europe/Rome"}'
```

### 22. `DELETE /api/v1/users/me` — Delete My Account

**Auth:** User  
Deletes user and any personal-only organizations. Clears Clerk user if applicable.

```bash
curl -s -X DELETE "$BASE/users/me" -H "Authorization: Bearer $TOKEN"
```

---

## Gateways (Admin)

Gateways connect MC1 to OpenClaw runtime instances. All gateway admin endpoints require org admin role.

### 23. `GET /api/v1/gateways` — List Gateways (Paginated)

**Auth:** Org admin

```bash
curl -s "$BASE/gateways?limit=50&offset=0" -H "Authorization: Bearer $TOKEN"
```

### 24. `POST /api/v1/gateways` — Create Gateway

**Auth:** Org admin  
**Body:**
```json
{
  "name": "Production Gateway",
  "url": "http://localhost:3000",
  "token": "gateway-api-token",
  "workspace_root": "/path/to/workspace",
  "allow_insecure_tls": false,
  "disable_device_pairing": false
}
```

Creates a gateway and provisions a main agent. The gateway URL is validated for connectivity.

```bash
curl -s -X POST "$BASE/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Gateway","url":"http://localhost:3000","token":"<token>","workspace_root":"/workspace"}'
```

### 25. `GET /api/v1/gateways/{gateway_id}` — Get Gateway

**Auth:** Org admin

```bash
curl -s "$BASE/gateways/<gateway-id>" -H "Authorization: Bearer $TOKEN"
```

### 26. `PATCH /api/v1/gateways/{gateway_id}` — Update Gateway

**Auth:** Org admin  
**Body (partial update):**
```json
{
  "name": "Updated Name",
  "url": "http://new-url:3000",
  "token": "new-token"
}
```

Re-validates connectivity when URL/token/TLS settings change. Refreshes main agent.

```bash
curl -s -X PATCH "$BASE/gateways/<gateway-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Gateway"}'
```

### 27. `POST /api/v1/gateways/{gateway_id}/templates/sync` — Sync Gateway Templates

**Auth:** Org admin  
**Query parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_main` | bool | true | Include main agent in sync |
| `lead_only` | bool | false | Only sync lead agents |
| `reset_sessions` | bool | false | Reset agent sessions |
| `rotate_tokens` | bool | false | Rotate agent tokens |
| `force_bootstrap` | bool | false | Force re-bootstrap |
| `overwrite` | bool | false | Overwrite existing templates |
| `board_id` | UUID | null | Scope sync to one board |

```bash
curl -s -X POST "$BASE/gateways/<gateway-id>/templates/sync?include_main=true&overwrite=true" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:** `GatewayTemplatesSyncResult` with per-agent sync status.

### 28. `DELETE /api/v1/gateways/{gateway_id}` — Delete Gateway

**Auth:** Org admin  
Deletes gateway, main agent, duplicate main agents, and installed skills.

```bash
curl -s -X DELETE "$BASE/gateways/<gateway-id>" -H "Authorization: Bearer $TOKEN"
```

---

## Gateway Sessions

Inspect and interact with live OpenClaw gateway sessions. All require org admin.

### 29. `GET /api/v1/gateways/status` — Gateway Status

**Auth:** Org admin  
**Query parameters:** `board_id`, `gateway_url`, `gateway_token`, `gateway_disable_device_pairing`, `gateway_allow_insecure_tls`

```bash
curl -s "$BASE/gateways/status?board_id=<board-id>" -H "Authorization: Bearer $TOKEN"
```

### 30. `GET /api/v1/gateways/sessions` — List Gateway Sessions

**Auth:** Org admin  
**Query:** `board_id`

```bash
curl -s "$BASE/gateways/sessions?board_id=<board-id>" -H "Authorization: Bearer $TOKEN"
```

### 31. `GET /api/v1/gateways/sessions/{session_id}` — Get Session

**Auth:** Org admin  
**Query:** `board_id`

```bash
curl -s "$BASE/gateways/sessions/<session-id>?board_id=<board-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 32. `GET /api/v1/gateways/sessions/{session_id}/history` — Session History

**Auth:** Org admin  
**Query:** `board_id`

```bash
curl -s "$BASE/gateways/sessions/<session-id>/history?board_id=<board-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 33. `POST /api/v1/gateways/sessions/{session_id}/message` — Send Session Message

**Auth:** Org admin  
**Query:** `board_id`  
**Body:**
```json
{ "message": "Hello from Mission Control" }
```

```bash
curl -s -X POST "$BASE/gateways/sessions/<session-id>/message?board_id=<board-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello"}'
```

### 34. `GET /api/v1/gateways/commands` — Supported Protocol Commands

**Auth:** Org admin  
Returns supported gateway protocol methods and events.

```bash
curl -s "$BASE/gateways/commands" -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "protocol_version": "...",
  "methods": [...],
  "events": [...]
}
```

---

## Boards

### 35. `GET /api/v1/boards` — List Boards (Paginated)

**Auth:** Org member  
**Query:** `gateway_id`, `board_group_id`

```bash
curl -s "$BASE/boards?limit=50&offset=0" -H "Authorization: Bearer $TOKEN"
```

### 36. `POST /api/v1/boards` — Create Board

**Auth:** Org admin  
**Body:**
```json
{
  "name": "Infrastructure Board",
  "description": "Infrastructure tasks",
  "gateway_id": "uuid",
  "board_group_id": "uuid-or-null",
  "board_type": "general",
  "objective": null,
  "success_metrics": null,
  "target_date": null
}
```

The gateway must have a main agent provisioned before boards can be created.

```bash
curl -s -X POST "$BASE/boards" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Infra Board","gateway_id":"<gateway-id>"}'
```

**Errors:** `422` if gateway invalid or missing main agent.

### 37. `GET /api/v1/boards/{board_id}` — Get Board

**Auth:** User with board read access

```bash
curl -s "$BASE/boards/<board-id>" -H "Authorization: Bearer $TOKEN"
```

### 38. `GET /api/v1/boards/{board_id}/snapshot` — Board Snapshot

**Auth:** User or Agent with board read access  
Returns a rich view model with board config, agents, tasks, and memory.

```bash
curl -s "$BASE/boards/<board-id>/snapshot" -H "Authorization: Bearer $TOKEN"
```

### 39. `GET /api/v1/boards/{board_id}/group-snapshot` — Board Group Snapshot

**Auth:** User or Agent with board read access  
**Query:** `include_self` (default false), `include_done` (default false), `per_board_task_limit` (default 5, 0-100)

Returns cross-board status for dependency and overlap checks across the board's group.

```bash
curl -s "$BASE/boards/<board-id>/group-snapshot?include_self=true&per_board_task_limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

### 40. `PATCH /api/v1/boards/{board_id}` — Update Board

**Auth:** User with board write access  
**Body (partial):**
```json
{
  "name": "Updated Name",
  "description": "Updated desc",
  "objective": "Ship v2",
  "success_metrics": {"metric": "uptime", "target": "99.9%"},
  "target_date": "2026-06-01",
  "board_type": "goal",
  "board_group_id": "uuid-or-null",
  "gateway_id": "uuid",
  "require_approval_for_done": true,
  "require_review_before_done": false,
  "comment_required_for_review": false,
  "only_lead_can_change_status": false,
  "block_status_changes_with_pending_approval": false
}
```

Board update notifications are sent to lead agents. Group change notifications go to all group agents.

```bash
curl -s -X PATCH "$BASE/boards/<board-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"objective":"Ship v2 by June"}'
```

**Errors:** `422` if goal board missing objective/success_metrics, or gateway invalid.

### 41. `DELETE /api/v1/boards/{board_id}` — Delete Board

**Auth:** User with board write access  
Deletes board and all dependent records (tasks, agents, memory, webhooks, approvals, etc.).

```bash
curl -s -X DELETE "$BASE/boards/<board-id>" -H "Authorization: Bearer $TOKEN"
```

---

## Board Memory

Board memory stores durable context and chat messages for a board.

### 42. `GET /api/v1/boards/{board_id}/memory` — List Board Memory (Paginated)

**Auth:** User or Agent with board read access  
**Query:** `is_chat` (bool, optional — filter chat vs durable memory)

```bash
curl -s "$BASE/boards/<board-id>/memory?is_chat=false&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

### 43. `GET /api/v1/boards/{board_id}/memory/stream` — Stream Board Memory (SSE)

**Auth:** User or Agent  
**Query:** `since` (ISO datetime), `is_chat` (bool)

```bash
curl -N "$BASE/boards/<board-id>/memory/stream?is_chat=true" \
  -H "Authorization: Bearer $TOKEN"
```

**SSE Event:** `memory` with `{"memory": {...}}` data.

### 44. `POST /api/v1/boards/{board_id}/memory` — Create Board Memory

**Auth:** User or Agent with board write access  
**Body:**
```json
{
  "content": "Decision: We'll use PostgreSQL for the data layer.",
  "tags": ["decision"],
  "source": "Lead Agent"
}
```

Special behaviors:
- Tags containing `"chat"` → marks as chat, notifies board lead + @mentioned agents
- Content `/pause` or `/resume` → broadcasts control command to all board agents
- `@agent_name` mentions → notifies mentioned agents

```bash
curl -s -X POST "$BASE/boards/<board-id>/memory" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Status update: all tests passing","tags":["chat"]}'
```

---

## Board Webhooks

Webhooks allow external systems to push events into boards.

### 45. `GET /api/v1/boards/{board_id}/webhooks` — List Webhooks (Paginated)

**Auth:** User with board read access

```bash
curl -s "$BASE/boards/<board-id>/webhooks" -H "Authorization: Bearer $TOKEN"
```

### 46. `POST /api/v1/boards/{board_id}/webhooks` — Create Webhook

**Auth:** User with board write access  
**Body:**
```json
{
  "description": "GitHub push events for repo X",
  "enabled": true,
  "secret": "webhook-signing-secret",
  "signature_header": "X-Hub-Signature-256",
  "agent_id": "uuid-or-null"
}
```

`agent_id` optionally routes payloads to a specific agent instead of the board lead.

```bash
curl -s -X POST "$BASE/boards/<board-id>/webhooks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description":"GitHub push events","enabled":true}'
```

**Response:** Includes `endpoint_path` and `endpoint_url` for the ingest URL.

### 47. `GET /api/v1/boards/{board_id}/webhooks/{webhook_id}` — Get Webhook

**Auth:** User with board read access

```bash
curl -s "$BASE/boards/<board-id>/webhooks/<webhook-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 48. `PATCH /api/v1/boards/{board_id}/webhooks/{webhook_id}` — Update Webhook

**Auth:** User with board write access  
**Body (partial):**
```json
{
  "description": "Updated description",
  "enabled": false,
  "agent_id": "uuid-or-null",
  "secret": "new-secret",
  "signature_header": "X-Webhook-Signature"
}
```

```bash
curl -s -X PATCH "$BASE/boards/<board-id>/webhooks/<webhook-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled":false}'
```

### 49. `DELETE /api/v1/boards/{board_id}/webhooks/{webhook_id}` — Delete Webhook

**Auth:** User with board write access. Also deletes stored payloads.

```bash
curl -s -X DELETE "$BASE/boards/<board-id>/webhooks/<webhook-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 50. `GET /api/v1/boards/{board_id}/webhooks/{webhook_id}/payloads` — List Payloads (Paginated)

**Auth:** User with board read access

```bash
curl -s "$BASE/boards/<board-id>/webhooks/<webhook-id>/payloads?limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

### 51. `GET /api/v1/boards/{board_id}/webhooks/{webhook_id}/payloads/{payload_id}` — Get Payload

**Auth:** User with board read access

```bash
curl -s "$BASE/boards/<board-id>/webhooks/<webhook-id>/payloads/<payload-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 52. `POST /api/v1/boards/{board_id}/webhooks/{webhook_id}` — Ingest Webhook Payload

**Auth:** NONE (public endpoint). HMAC-SHA256 signature verified if webhook has a secret.  
**Rate limit:** 60 requests per 60 seconds per IP.  
**Max payload:** Configurable (default ~1 MB).  
**Status code:** `202 Accepted`

The webhook endpoint accepts any content type. JSON is parsed; other content is stored as string.

Signature verification checks (in order): `webhook.signature_header`, `X-Hub-Signature-256`, `X-Webhook-Signature`.

```bash
curl -s -X POST "http://localhost:8000/api/v1/boards/<board-id>/webhooks/<webhook-id>" \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=<hmac-hex>" \
  -d '{"action":"push","ref":"refs/heads/main"}'
```

**Response:**
```json
{
  "board_id": "uuid",
  "webhook_id": "uuid",
  "payload_id": "uuid"
}
```

**Side effects:**
- Stores payload in DB
- Creates board memory entry with payload preview
- Notifies target agent (or board lead) via gateway
- Enqueues for async delivery processing

**Errors:** `410` if webhook disabled, `413` if payload too large, `403` if signature invalid, `429` if rate limited.

---

## Board Onboarding

Structured onboarding flow for setting up boards with goals and lead agents.

### 53. `GET /api/v1/boards/{board_id}/onboarding` — Get Onboarding Session

**Auth:** User with board read access

```bash
curl -s "$BASE/boards/<board-id>/onboarding" -H "Authorization: Bearer $TOKEN"
```

**Response:** `BoardOnboardingRead` with status, messages, draft_goal.

### 54. `POST /api/v1/boards/{board_id}/onboarding/start` — Start Onboarding

**Auth:** User with board write access  
**Body:**
```json
{}
```

Initiates an onboarding conversation with the gateway agent. If an active session exists, resumes it.

```bash
curl -s -X POST "$BASE/boards/<board-id>/onboarding/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 55. `POST /api/v1/boards/{board_id}/onboarding/answer` — Answer Onboarding Question

**Auth:** User with board write access  
**Body:**
```json
{
  "answer": "Option A",
  "other_text": "additional context"
}
```

```bash
curl -s -X POST "$BASE/boards/<board-id>/onboarding/answer" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"answer":"balanced"}'
```

### 56. `POST /api/v1/boards/{board_id}/onboarding/agent` — Agent Onboarding Update

**Auth:** Agent (gateway-scoped, main agent only)  
**Body:** Either a question or a completion payload:

**Question:**
```json
{
  "question": "What is your primary goal?",
  "options": [
    {"id": "1", "label": "Ship a product"},
    {"id": "2", "label": "Research project"}
  ]
}
```

**Completion:**
```json
{
  "status": "complete",
  "board_type": "goal",
  "objective": "Ship v2 by June",
  "success_metrics": {"metric": "coverage", "target": "90%"},
  "target_date": "2026-06-01",
  "user_profile": {
    "preferred_name": "Alex",
    "pronouns": "they/them",
    "timezone": "America/Los_Angeles",
    "notes": "...",
    "context": "..."
  },
  "lead_agent": {
    "name": "Ava",
    "identity_profile": {"role": "Board Lead"},
    "autonomy_level": "balanced",
    "verbosity": "concise",
    "output_format": "bullets",
    "update_cadence": "daily",
    "custom_instructions": "..."
  }
}
```

**Errors:** `401` if not agent, `409` if already confirmed.

### 57. `POST /api/v1/boards/{board_id}/onboarding/confirm` — Confirm Onboarding

**Auth:** User with board write access  
**Body:**
```json
{
  "board_type": "goal",
  "objective": "Ship v2 by June",
  "success_metrics": {"metric": "uptime", "target": "99.9%"},
  "target_date": "2026-06-01"
}
```

Confirms onboarding, updates board config, provisions lead agent, applies user profile from draft.

```bash
curl -s -X POST "$BASE/boards/<board-id>/onboarding/confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"board_type":"goal","objective":"Ship v2","success_metrics":{"metric":"uptime","target":"99.9%"}}'
```

**Response:** Updated `BoardRead`.

---

## Board Groups

Board groups link related boards for cross-board coordination.

### 58. `GET /api/v1/board-groups` — List Board Groups (Paginated)

**Auth:** Org member

```bash
curl -s "$BASE/board-groups" -H "Authorization: Bearer $TOKEN"
```

### 59. `POST /api/v1/board-groups` — Create Board Group

**Auth:** Org admin  
**Body:**
```json
{
  "name": "Platform Team",
  "slug": "platform-team",
  "description": "All platform-related boards"
}
```

```bash
curl -s -X POST "$BASE/board-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Platform Team"}'
```

### 60. `GET /api/v1/board-groups/{group_id}` — Get Board Group

**Auth:** Org member with access to at least one group board

```bash
curl -s "$BASE/board-groups/<group-id>" -H "Authorization: Bearer $TOKEN"
```

### 61. `GET /api/v1/board-groups/{group_id}/snapshot` — Board Group Snapshot

**Auth:** Org member  
**Query:** `include_done` (bool), `per_board_task_limit` (int)

```bash
curl -s "$BASE/board-groups/<group-id>/snapshot?include_done=false&per_board_task_limit=5" \
  -H "Authorization: Bearer $TOKEN"
```

### 62. `POST /api/v1/board-groups/{group_id}/heartbeat` — Apply Group Heartbeat Settings

**Auth:** User (org admin) or Agent (board lead in group)  
**Body:**
```json
{
  "every": "5m",
  "include_board_leads": false
}
```

Applies heartbeat configuration to all agents in the group and syncs with gateways.

```bash
curl -s -X POST "$BASE/board-groups/<group-id>/heartbeat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"every":"10m","include_board_leads":false}'
```

**Response:**
```json
{
  "board_group_id": "uuid",
  "requested": {...},
  "updated_agent_ids": ["uuid", ...],
  "failed_agent_ids": []
}
```

### 63. `PATCH /api/v1/board-groups/{group_id}` — Update Board Group

**Auth:** Org admin

```bash
curl -s -X PATCH "$BASE/board-groups/<group-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Group Name"}'
```

### 64. `DELETE /api/v1/board-groups/{group_id}` — Delete Board Group

**Auth:** Org admin. Unlinks boards, deletes group memory, then deletes the group.

```bash
curl -s -X DELETE "$BASE/board-groups/<group-id>" -H "Authorization: Bearer $TOKEN"
```

---

## Board Group Memory

Shared memory across boards in a group. Accessible via group path or board path.

### 65. `GET /api/v1/board-groups/{group_id}/memory` — List Group Memory (Paginated)

**Auth:** Org member  
**Query:** `is_chat` (bool)

```bash
curl -s "$BASE/board-groups/<group-id>/memory?is_chat=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 66. `GET /api/v1/board-groups/{group_id}/memory/stream` — Stream Group Memory (SSE)

**Auth:** Org member  
**Query:** `since`, `is_chat`

```bash
curl -N "$BASE/board-groups/<group-id>/memory/stream" \
  -H "Authorization: Bearer $TOKEN"
```

### 67. `POST /api/v1/board-groups/{group_id}/memory` — Create Group Memory

**Auth:** Org member  
**Body:**
```json
{
  "content": "Cross-board status: all systems go",
  "tags": ["chat", "broadcast"],
  "source": "Alex"
}
```

Tags `"chat"` or `"broadcast"` trigger agent notifications. `@all` mentions broadcast to everyone.

```bash
curl -s -X POST "$BASE/board-groups/<group-id>/memory" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"@all standup: status please","tags":["chat","broadcast"]}'
```

### 68. `GET /api/v1/boards/{board_id}/group-memory` — List Group Memory (Board Context)

**Auth:** User or Agent with board read access  
**Query:** `is_chat` (bool)

Same as group memory but accessed via a board's linked group.

```bash
curl -s "$BASE/boards/<board-id>/group-memory?is_chat=false" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 69. `GET /api/v1/boards/{board_id}/group-memory/stream` — Stream Group Memory (Board Context, SSE)

**Auth:** User or Agent  
**Query:** `since`, `is_chat`

```bash
curl -N "$BASE/boards/<board-id>/group-memory/stream?is_chat=true" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 70. `POST /api/v1/boards/{board_id}/group-memory` — Create Group Memory (Board Context)

**Auth:** User or Agent with board write access  
**Body:** Same as group memory create.

```bash
curl -s -X POST "$BASE/boards/<board-id>/group-memory" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Dependency resolved for task X","tags":["chat"]}'
```

**Errors:** `422` if board is not in a group.

---

## Agents (Admin)

Organization-level agent management. Most endpoints require org admin.

### 71. `GET /api/v1/agents` — List Agents (Paginated)

**Auth:** Org admin  
**Query:** `board_id`, `gateway_id`

```bash
curl -s "$BASE/agents?board_id=<board-id>&limit=50" -H "Authorization: Bearer $TOKEN"
```

### 72. `GET /api/v1/agents/stream` — Stream Agent Updates (SSE)

**Auth:** Org admin  
**Query:** `board_id`, `since`

```bash
curl -N "$BASE/agents/stream?board_id=<board-id>" -H "Authorization: Bearer $TOKEN"
```

### 73. `POST /api/v1/agents` — Create Agent

**Auth:** User or Agent  
**Body:**
```json
{
  "name": "Worker Alpha",
  "board_id": "uuid",
  "gateway_id": "uuid",
  "is_board_lead": false,
  "identity_profile": {
    "role": "developer",
    "communication_style": "concise"
  },
  "heartbeat_config": {
    "every": "5m",
    "target": "last"
  }
}
```

```bash
curl -s -X POST "$BASE/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Worker Alpha","board_id":"<board-id>","gateway_id":"<gateway-id>"}'
```

### 74. `GET /api/v1/agents/{agent_id}` — Get Agent

**Auth:** Org admin

```bash
curl -s "$BASE/agents/<agent-id>" -H "Authorization: Bearer $TOKEN"
```

### 75. `PATCH /api/v1/agents/{agent_id}` — Update Agent

**Auth:** Org admin  
**Query:** `force` (bool, default false)  
**Body (partial):**
```json
{
  "name": "Worker Beta",
  "status": "online",
  "identity_profile": {"role": "tester"},
  "heartbeat_config": {"every": "10m"}
}
```

```bash
curl -s -X PATCH "$BASE/agents/<agent-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"online"}'
```

### 76. `POST /api/v1/agents/{agent_id}/heartbeat` — Agent Heartbeat (by ID)

**Auth:** User or Agent  
**Body:**
```json
{}
```

```bash
curl -s -X POST "$BASE/agents/<agent-id>/heartbeat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 77. `POST /api/v1/agents/heartbeat` — Heartbeat or Create Agent

**Auth:** User or Agent  
**Body:**
```json
{
  "name": "Worker Alpha",
  "board_id": "uuid",
  "gateway_id": "uuid",
  "status": "online"
}
```

Upserts: heartbeats an existing agent or creates/provisions one if needed.

```bash
curl -s -X POST "$BASE/agents/heartbeat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Worker Alpha","board_id":"<board-id>","status":"online"}'
```

### 78. `DELETE /api/v1/agents/{agent_id}` — Delete Agent

**Auth:** Org admin

```bash
curl -s -X DELETE "$BASE/agents/<agent-id>" -H "Authorization: Bearer $TOKEN"
```

---

## Agent API (Agent-Scoped)

These endpoints use `X-Agent-Token` authentication and are designed for autonomous agents. Board-scoped agents see only their assigned board; main agents see all org boards.

### 79. `GET /api/v1/agent/healthz` — Agent Auth Health Check

**Auth:** Agent token  
Verifies both service availability and token validity.

```bash
curl -s "$BASE/agent/healthz" -H "X-Agent-Token: $AGENT_TOKEN"
```

**Response:**
```json
{
  "ok": true,
  "agent_id": "uuid",
  "board_id": "uuid-or-null",
  "gateway_id": "uuid",
  "status": "online",
  "is_board_lead": true
}
```

### 80. `GET /api/v1/agent/boards` — List Accessible Boards (Paginated)

**Auth:** Agent token  
Board-scoped agents see only their board; main agents see all org boards.

```bash
curl -s "$BASE/agent/boards?limit=50" -H "X-Agent-Token: $AGENT_TOKEN"
```

### 81. `GET /api/v1/agent/boards/{board_id}` — Get Board

**Auth:** Agent token

```bash
curl -s "$BASE/agent/boards/<board-id>" -H "X-Agent-Token: $AGENT_TOKEN"
```

### 82. `GET /api/v1/agent/agents` — List Visible Agents (Paginated)

**Auth:** Agent token  
**Query:** `board_id`

```bash
curl -s "$BASE/agent/agents?board_id=<board-id>" -H "X-Agent-Token: $AGENT_TOKEN"
```

### 83. `GET /api/v1/agent/boards/{board_id}/tasks` — List Board Tasks (Paginated)

**Auth:** Agent token  
**Query:** `status` (comma-separated: inbox,in_progress,review,done), `assigned_agent_id`, `unassigned` (bool)

```bash
curl -s "$BASE/agent/boards/<board-id>/tasks?status=inbox,in_progress&limit=20" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 84. `GET /api/v1/agent/boards/{board_id}/tags` — List Board Tags

**Auth:** Agent token  
Returns tag IDs for use in task create/update payloads.

```bash
curl -s "$BASE/agent/boards/<board-id>/tags" -H "X-Agent-Token: $AGENT_TOKEN"
```

**Response:**
```json
[
  {"id": "uuid", "name": "bug", "slug": "bug", "color": "#ff0000"}
]
```

### 85. `GET /api/v1/agent/boards/{board_id}/webhooks/{webhook_id}/payloads/{payload_id}` — Get Webhook Payload

**Auth:** Agent token  
**Query:** `max_chars` (1-1000000, truncates payload if exceeded)

```bash
curl -s "$BASE/agent/boards/<board-id>/webhooks/<wh-id>/payloads/<payload-id>?max_chars=5000" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 86. `POST /api/v1/agent/boards/{board_id}/tasks` — Create Task (Lead Only)

**Auth:** Agent token (board lead only)  
**Body:**
```json
{
  "title": "Implement auth module",
  "description": "Build JWT-based authentication",
  "status": "inbox",
  "assigned_agent_id": "uuid-or-null",
  "depends_on_task_ids": [],
  "tag_ids": [],
  "custom_field_values": {}
}
```

Supports dependency-aware creation. Blocked tasks cannot be assigned or started.

```bash
curl -s -X POST "$BASE/agent/boards/<board-id>/tasks" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Implement auth module","status":"inbox"}'
```

**Errors:** `403` if not lead, `404` if assigned agent not found, `409` if blocked by dependencies.

### 87. `PATCH /api/v1/agent/boards/{board_id}/tasks/{task_id}` — Update Task

**Auth:** Agent token  
**Body (partial):**
```json
{
  "status": "in_progress",
  "assigned_agent_id": "uuid",
  "comment": "Starting work on this",
  "depends_on_task_ids": ["uuid"],
  "tag_ids": ["uuid"],
  "custom_field_values": {"priority": "high"}
}
```

**Lead agents** can: change status (review→done/inbox), assign agents, update dependencies/tags/custom fields. Cannot include `comment` in PATCH (use comment endpoint).

**Worker agents** can: change status, add comments, update custom field values. Cannot change assignment, dependencies, or tags.

```bash
curl -s -X PATCH "$BASE/agent/boards/<board-id>/tasks/<task-id>" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"in_progress"}'
```

### 88. `DELETE /api/v1/agent/boards/{board_id}/tasks/{task_id}` — Delete Task (Lead Only)

**Auth:** Agent token (board lead only)

```bash
curl -s -X DELETE "$BASE/agent/boards/<board-id>/tasks/<task-id>" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 89. `GET /api/v1/agent/boards/{board_id}/tasks/{task_id}/comments` — List Task Comments (Paginated)

**Auth:** Agent token

```bash
curl -s "$BASE/agent/boards/<board-id>/tasks/<task-id>/comments?limit=50" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 90. `POST /api/v1/agent/boards/{board_id}/tasks/{task_id}/comments` — Create Task Comment

**Auth:** Agent token  
**Body:**
```json
{ "message": "Completed unit tests, moving to integration." }
```

Board leads can only comment during review, when mentioned, or on tasks they created.

```bash
curl -s -X POST "$BASE/agent/boards/<board-id>/tasks/<task-id>/comments" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Tests passing, submitting for review."}'
```

### 91. `GET /api/v1/agent/boards/{board_id}/memory` — List Board Memory (Paginated)

**Auth:** Agent token  
**Query:** `is_chat` (bool)

```bash
curl -s "$BASE/agent/boards/<board-id>/memory?is_chat=false" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 92. `POST /api/v1/agent/boards/{board_id}/memory` — Create Board Memory

**Auth:** Agent token  
**Body:**
```json
{
  "content": "Decision: using Redis for caching",
  "tags": ["decision"],
  "source": "Lead Agent"
}
```

```bash
curl -s -X POST "$BASE/agent/boards/<board-id>/memory" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Completed phase 1","tags":["chat"]}'
```

### 93. `GET /api/v1/agent/boards/{board_id}/approvals` — List Board Approvals (Paginated)

**Auth:** Agent token  
**Query:** `status` (pending, approved, rejected)

```bash
curl -s "$BASE/agent/boards/<board-id>/approvals?status=pending" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 94. `POST /api/v1/agent/boards/{board_id}/approvals` — Create Approval Request

**Auth:** Agent token  
**Body:**
```json
{
  "action_type": "deploy_production",
  "payload": {"service": "api", "version": "2.1.0"},
  "confidence": 0.85,
  "rubric_scores": {"risk": 0.3, "impact": 0.9},
  "task_id": "uuid",
  "task_ids": ["uuid"],
  "status": "pending"
}
```

```bash
curl -s -X POST "$BASE/agent/boards/<board-id>/approvals" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action_type":"deploy","confidence":0.9,"task_id":"<task-id>","status":"pending"}'
```

**Errors:** `409` if task already has a pending approval.

### 95. `POST /api/v1/agent/boards/{board_id}/onboarding` — Agent Onboarding Update

**Auth:** Agent token  
Same as endpoint #56. Used by agents to submit onboarding questions/completions.

### 96. `POST /api/v1/agent/agents` — Create Agent (Lead Only)

**Auth:** Agent token (board lead only)  
**Body:** `AgentCreate` — board_id is forced to the lead's board.

```bash
curl -s -X POST "$BASE/agent/agents" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Specialist Worker","identity_profile":{"role":"tester"}}'
```

### 97. `POST /api/v1/agent/boards/{board_id}/agents/{agent_id}/nudge` — Nudge Agent (Lead Only)

**Auth:** Agent token (board lead only)  
**Body:**
```json
{ "message": "Please prioritize task X, it's blocking deployment." }
```

Sends a direct coordination message to a specific agent via gateway.

```bash
curl -s -X POST "$BASE/agent/boards/<board-id>/agents/<agent-id>/nudge" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Please update your status on task X"}'
```

**Errors:** `403` if not lead, `404` if target agent not found, `502` if gateway dispatch failed.

### 98. `POST /api/v1/agent/heartbeat` — Agent Heartbeat

**Auth:** Agent token  
Records liveness for the authenticated agent. Identity-bound to token's agent ID.

```bash
curl -s -X POST "$BASE/agent/heartbeat" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response:** `AgentRead` with updated status and last_seen_at.

### 99. `GET /api/v1/agent/boards/{board_id}/agents/{agent_id}/soul` — Get Agent SOUL

**Auth:** Agent token (board lead or same agent)  
Returns the agent's SOUL.md content as a string.

```bash
curl -s "$BASE/agent/boards/<board-id>/agents/<agent-id>/soul" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

**Errors:** `403` if not lead or self, `502` if gateway read failed.

### 100. `PUT /api/v1/agent/boards/{board_id}/agents/{agent_id}/soul` — Update Agent SOUL (Lead Only)

**Auth:** Agent token (board lead only)  
**Body:**
```json
{
  "content": "# SOUL.md\n\nYou are a testing specialist...",
  "source_url": "https://github.com/org/souls/tester.md",
  "reason": "Updated testing guidelines"
}
```

Persists SOUL template in DB and syncs to gateway.

```bash
curl -s -X PUT "$BASE/agent/boards/<board-id>/agents/<agent-id>/soul" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"# SOUL\nYou are a developer agent...","reason":"Role update"}'
```

### 101. `DELETE /api/v1/agent/boards/{board_id}/agents/{agent_id}` — Delete Agent (Lead Only)

**Auth:** Agent token (board lead only)

```bash
curl -s -X DELETE "$BASE/agent/boards/<board-id>/agents/<agent-id>" \
  -H "X-Agent-Token: $AGENT_TOKEN"
```

### 102. `POST /api/v1/agent/boards/{board_id}/gateway/main/ask-user` — Ask User via Gateway

**Auth:** Agent token (board lead only)  
**Body:**
```json
{
  "message": "Should I proceed with the database migration?",
  "context": "This will affect 3 production tables",
  "correlation_id": "migration-decision-001"
}
```

Escalates a question to the human user through the gateway-main interaction channel.

```bash
curl -s -X POST "$BASE/agent/boards/<board-id>/gateway/main/ask-user" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Permission to deploy to production?"}'
```

**Errors:** `403` if not lead, `502` if gateway handoff failed.

### 103. `POST /api/v1/agent/gateway/boards/{board_id}/lead/message` — Message Board Lead

**Auth:** Agent token (main agent)  
**Body:**
```json
{
  "message": "New priority from user: focus on security audit",
  "correlation_id": "priority-change-001"
}
```

Routes a direct message from main agent to a board's lead agent.

```bash
curl -s -X POST "$BASE/agent/gateway/boards/<board-id>/lead/message" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"User requests status update on board progress"}'
```

### 104. `POST /api/v1/agent/gateway/leads/broadcast` — Broadcast to All Leads

**Auth:** Agent token (main agent)  
**Body:**
```json
{
  "message": "System maintenance scheduled in 2 hours",
  "board_ids": ["uuid", "uuid"],
  "correlation_id": "maintenance-notice"
}
```

Sends to multiple board leads. Returns per-board dispatch status.

```bash
curl -s -X POST "$BASE/agent/gateway/leads/broadcast" \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Maintenance window starting"}'
```

---

## Tasks

Board-scoped task CRUD with dependency management, custom fields, and lifecycle rules.

### Task Statuses

| Status | Description |
|--------|-------------|
| `inbox` | New/unstarted task |
| `in_progress` | Actively being worked on |
| `review` | Submitted for lead review |
| `done` | Completed |

### 105. `GET /api/v1/boards/{board_id}/tasks` — List Tasks (Paginated)

**Auth:** User or Agent with board read access  
**Query:** `status` (comma-separated), `assigned_agent_id`, `unassigned` (bool)

```bash
curl -s "$BASE/boards/<board-id>/tasks?status=inbox,in_progress&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

**Response includes:** `depends_on_task_ids`, `tag_ids`, `tags`, `blocked_by_task_ids`, `is_blocked`, `custom_field_values`.

### 106. `GET /api/v1/boards/{board_id}/tasks/stream` — Stream Task Events (SSE)

**Auth:** User or Agent  
**Query:** `since` (ISO datetime)

Events include: `task.created`, `task.updated`, `task.status_changed`, `task.comment`.

```bash
curl -N "$BASE/boards/<board-id>/tasks/stream?since=2026-03-21T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

**SSE Event:** `task` with payload:
```json
{
  "type": "task.status_changed",
  "activity": {...},
  "task": {...}
}
```

For comments: `{"type": "task.comment", "activity": {...}, "comment": {...}}`

### 107. `POST /api/v1/boards/{board_id}/tasks` — Create Task

**Auth:** User with board write access  
**Body:**
```json
{
  "title": "Implement login page",
  "description": "Build JWT-based login with OAuth support",
  "status": "inbox",
  "assigned_agent_id": null,
  "depends_on_task_ids": [],
  "tag_ids": ["uuid"],
  "custom_field_values": {"priority": "high"}
}
```

Notifies board lead on creation. Notifies assigned agent if set.

```bash
curl -s -X POST "$BASE/boards/<board-id>/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Implement login page","status":"inbox"}'
```

**Errors:** `409` if blocked by dependencies and trying to assign/start.

### 108. `PATCH /api/v1/boards/{board_id}/tasks/{task_id}` — Update Task

**Auth:** User or Agent  
**Body (partial):**
```json
{
  "title": "Updated title",
  "description": "Updated description",
  "status": "in_progress",
  "assigned_agent_id": "uuid",
  "comment": "Starting work now",
  "depends_on_task_ids": ["uuid"],
  "tag_ids": ["uuid"],
  "custom_field_values": {"priority": "critical"}
}
```

**Board rules enforced:**
- `require_approval_for_done` — task needs approved approval before done
- `require_review_before_done` — must pass through review status
- `comment_required_for_review` — comment needed when moving to review
- `only_lead_can_change_status` — workers cannot change status
- `block_status_changes_with_pending_approval` — pending approval blocks status changes

**Status transitions:**
- `inbox` → `in_progress`: Claims task, sets `in_progress_at`
- `in_progress` → `review`: Unassigns, auto-assigns to lead
- `review` → `done` (lead only): Completes task
- `review` → `inbox` (lead only): Returns for rework, re-assigns to last worker
- Any → `inbox`: Clears assignment and in_progress_at

```bash
curl -s -X PATCH "$BASE/boards/<board-id>/tasks/<task-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"in_progress","comment":"Starting now"}'
```

### 109. `DELETE /api/v1/boards/{board_id}/tasks/{task_id}` — Delete Task

**Auth:** User with board write access  
Deletes task, comments, dependencies, tags, custom field values, approvals, fingerprints.

```bash
curl -s -X DELETE "$BASE/boards/<board-id>/tasks/<task-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 110. `GET /api/v1/boards/{board_id}/tasks/{task_id}/comments` — List Task Comments (Paginated)

**Auth:** User or Agent  
Returns comments in chronological order.

```bash
curl -s "$BASE/boards/<board-id>/tasks/<task-id>/comments?limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

### 111. `POST /api/v1/boards/{board_id}/tasks/{task_id}/comments` — Create Task Comment

**Auth:** User or Agent  
**Body:**
```json
{ "message": "Completed implementation, ready for review." }
```

Notifies @mentioned agents or the assigned agent. Board leads have comment restrictions (see #90).

```bash
curl -s -X POST "$BASE/boards/<board-id>/tasks/<task-id>/comments" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"@LeadAgent ready for review"}'
```

---

## Approvals

Board-scoped approval workflows for gated task operations.

### 112. `GET /api/v1/boards/{board_id}/approvals` — List Approvals (Paginated)

**Auth:** User or Agent  
**Query:** `status` (pending, approved, rejected)

```bash
curl -s "$BASE/boards/<board-id>/approvals?status=pending" \
  -H "Authorization: Bearer $TOKEN"
```

**Response includes:** `task_ids`, `task_titles`.

### 113. `GET /api/v1/boards/{board_id}/approvals/stream` — Stream Approvals (SSE)

**Auth:** User or Agent  
**Query:** `since`

```bash
curl -N "$BASE/boards/<board-id>/approvals/stream" \
  -H "Authorization: Bearer $TOKEN"
```

**SSE Event:** `approval` with:
```json
{
  "approval": {...},
  "pending_approvals_count": 3,
  "task_counts": {"task_id": "...", "approvals_count": 2, "approvals_pending_count": 1}
}
```

### 114. `POST /api/v1/boards/{board_id}/approvals` — Create Approval

**Auth:** User or Agent  
**Body:**
```json
{
  "action_type": "deploy_production",
  "payload": {"service": "api"},
  "confidence": 0.85,
  "rubric_scores": {"risk": 0.3},
  "task_id": "uuid",
  "task_ids": ["uuid"],
  "status": "pending",
  "agent_id": "uuid"
}
```

Each task can have only one pending approval.

```bash
curl -s -X POST "$BASE/boards/<board-id>/approvals" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action_type":"deploy","confidence":0.9,"task_id":"<id>","status":"pending"}'
```

**Errors:** `409` if task already has pending approval (returns conflict details).

### 115. `PATCH /api/v1/boards/{board_id}/approvals/{approval_id}` — Update Approval

**Auth:** User with board write access (user-only, not agents)  
**Body:**
```json
{ "status": "approved" }
```

When resolved (approved/rejected), notifies the board lead agent via gateway.

```bash
curl -s -X PATCH "$BASE/boards/<board-id>/approvals/<approval-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"approved"}'
```

---

## Tags

Organization-scoped tag management for task categorization.

### 116. `GET /api/v1/tags` — List Tags (Paginated)

**Auth:** Org member  
Includes `task_count` per tag.

```bash
curl -s "$BASE/tags" -H "Authorization: Bearer $TOKEN"
```

### 117. `POST /api/v1/tags` — Create Tag

**Auth:** Org admin  
**Body:**
```json
{
  "name": "bug",
  "slug": "bug",
  "color": "#ff0000",
  "description": "Bug reports"
}
```

```bash
curl -s -X POST "$BASE/tags" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"bug","color":"#ff0000"}'
```

**Errors:** `409` if slug already exists.

### 118. `GET /api/v1/tags/{tag_id}` — Get Tag

**Auth:** Org member

```bash
curl -s "$BASE/tags/<tag-id>" -H "Authorization: Bearer $TOKEN"
```

### 119. `PATCH /api/v1/tags/{tag_id}` — Update Tag

**Auth:** Org admin  
**Body (partial):**
```json
{ "name": "critical-bug", "color": "#cc0000" }
```

```bash
curl -s -X PATCH "$BASE/tags/<tag-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"color":"#cc0000"}'
```

### 120. `DELETE /api/v1/tags/{tag_id}` — Delete Tag

**Auth:** Org admin. Removes all tag assignments.

```bash
curl -s -X DELETE "$BASE/tags/<tag-id>" -H "Authorization: Bearer $TOKEN"
```

---

## Custom Fields

Organization-level task custom field definitions, assigned to specific boards.

### 121. `GET /api/v1/organizations/me/custom-fields` — List Custom Field Definitions

**Auth:** Org member  
Returns definitions with `board_ids` showing which boards use each field.

```bash
curl -s "$BASE/organizations/me/custom-fields" -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
[
  {
    "id": "uuid",
    "field_key": "priority",
    "label": "Priority",
    "field_type": "select",
    "ui_visibility": "visible",
    "validation_regex": null,
    "description": "Task priority level",
    "required": false,
    "default_value": "medium",
    "board_ids": ["uuid", "uuid"]
  }
]
```

### 122. `POST /api/v1/organizations/me/custom-fields` — Create Custom Field

**Auth:** Org admin  
**Body:**
```json
{
  "field_key": "priority",
  "label": "Priority",
  "field_type": "select",
  "ui_visibility": "visible",
  "validation_regex": null,
  "description": "Task priority",
  "required": false,
  "default_value": "medium",
  "board_ids": ["uuid"]
}
```

Field types: `text`, `number`, `select`, `boolean`, `date`, etc.

```bash
curl -s -X POST "$BASE/organizations/me/custom-fields" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"field_key":"priority","label":"Priority","field_type":"select","board_ids":["<board-id>"]}'
```

**Errors:** `409` if field_key already exists, `422` if board_ids invalid or empty.

### 123. `PATCH /api/v1/organizations/me/custom-fields/{definition_id}` — Update Custom Field

**Auth:** Org admin  
**Body (partial):**
```json
{
  "label": "Updated Label",
  "required": true,
  "board_ids": ["uuid", "uuid"]
}
```

```bash
curl -s -X PATCH "$BASE/organizations/me/custom-fields/<def-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"required":true}'
```

### 124. `DELETE /api/v1/organizations/me/custom-fields/{definition_id}` — Delete Custom Field

**Auth:** Org admin  
Cannot delete if task values exist for this field.

```bash
curl -s -X DELETE "$BASE/organizations/me/custom-fields/<def-id>" \
  -H "Authorization: Bearer $TOKEN"
```

**Errors:** `409` if task values exist.

---

## Activity

Activity feed and task-comment feed across boards.

### 125. `GET /api/v1/activity` — List Activity Events (Paginated)

**Auth:** User or Agent  
Users see events for accessible boards. Agents see only their own events.

```bash
curl -s "$BASE/activity?limit=50" -H "Authorization: Bearer $TOKEN"
```

**Response items include:** `route_name`, `route_params` for UI navigation.

### 126. `GET /api/v1/activity/task-comments` — List Task Comment Feed (Paginated)

**Auth:** Org member  
**Query:** `board_id` (optional filter)

Returns enriched task-comment feed with agent name, role, task title, board name.

```bash
curl -s "$BASE/activity/task-comments?board_id=<board-id>&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

### 127. `GET /api/v1/activity/task-comments/stream` — Stream Task Comments (SSE)

**Auth:** Org member  
**Query:** `board_id`, `since`

```bash
curl -N "$BASE/activity/task-comments/stream?since=2026-03-21T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

**SSE Event:** `comment` with `{"comment": {...}}` payload.

---

## Metrics

### 128. `GET /api/v1/metrics/dashboard` — Dashboard Metrics

**Auth:** Org member  
**Query:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `range` | string | `24h` | Time range: 24h, 3d, 7d, 14d, 1m, 3m, 6m, 1y |
| `board_id` | UUID | null | Filter to one board |
| `group_id` | UUID | null | Filter to a board group |

```bash
curl -s "$BASE/metrics/dashboard?range=7d&board_id=<board-id>" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "range": "7d",
  "generated_at": "2026-03-21T18:00:00Z",
  "kpis": {
    "active_agents": 5,
    "tasks_in_progress": 12,
    "inbox_tasks": 8,
    "in_progress_tasks": 12,
    "review_tasks": 3,
    "done_tasks": 45,
    "error_rate_pct": 2.5,
    "median_cycle_time_hours_7d": 4.2
  },
  "throughput": {
    "primary": {"range": "7d", "bucket": "day", "points": [...]},
    "comparison": {"range": "7d", "bucket": "day", "points": [...]}
  },
  "cycle_time": {...},
  "error_rate": {...},
  "wip": {
    "primary": {
      "points": [{"period": "...", "inbox": 5, "in_progress": 3, "review": 1, "done": 10}]
    },
    "comparison": {...}
  },
  "pending_approvals": {
    "total": 2,
    "items": [
      {
        "approval_id": "uuid",
        "board_id": "uuid",
        "board_name": "Infra",
        "action_type": "deploy",
        "confidence": 0.85,
        "created_at": "...",
        "task_title": "Deploy v2"
      }
    ]
  }
}
```

---

## Skills Marketplace

Manage skill packs and individual skills for gateway agents.

### 129. `GET /api/v1/skills/marketplace` — List Marketplace Skills

**Auth:** Org admin  
**Query:**
| Param | Type | Description |
|-------|------|-------------|
| `gateway_id` | UUID | **Required.** Annotates install state |
| `search` | string | Full-text search |
| `category` | string | Filter by category |
| `risk` | string | Filter by risk level |
| `pack_id` | UUID | Filter by skill pack |
| `limit` | int | Pagination limit (1-200) |
| `offset` | int | Pagination offset |

When `limit` is provided, response headers include `X-Total-Count`, `X-Limit`, `X-Offset`.

```bash
curl -s "$BASE/skills/marketplace?gateway_id=<gw-id>&search=docker&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

### 130. `POST /api/v1/skills/marketplace` — Register Marketplace Skill

**Auth:** Org admin  
**Body:**
```json
{
  "source_url": "https://github.com/org/skills/tree/main/docker",
  "name": "Docker Management",
  "description": "Manage Docker containers"
}
```

Upserts: updates existing skill if source_url matches.

```bash
curl -s -X POST "$BASE/skills/marketplace" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_url":"https://github.com/org/skills/tree/main/docker","name":"Docker"}'
```

### 131. `DELETE /api/v1/skills/marketplace/{skill_id}` — Delete Marketplace Skill

**Auth:** Org admin. Also removes install records.

```bash
curl -s -X DELETE "$BASE/skills/marketplace/<skill-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 132. `POST /api/v1/skills/marketplace/{skill_id}/install` — Install Skill

**Auth:** Org admin  
**Query:** `gateway_id` (required)

Dispatches install instruction to gateway main agent.

```bash
curl -s -X POST "$BASE/skills/marketplace/<skill-id>/install?gateway_id=<gw-id>" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "skill_id": "uuid",
  "gateway_id": "uuid",
  "installed": true
}
```

**Errors:** `502` if gateway dispatch failed.

### 133. `POST /api/v1/skills/marketplace/{skill_id}/uninstall` — Uninstall Skill

**Auth:** Org admin  
**Query:** `gateway_id` (required)

```bash
curl -s -X POST "$BASE/skills/marketplace/<skill-id>/uninstall?gateway_id=<gw-id>" \
  -H "Authorization: Bearer $TOKEN"
```

### 134. `GET /api/v1/skills/packs` — List Skill Packs

**Auth:** Org admin

```bash
curl -s "$BASE/skills/packs" -H "Authorization: Bearer $TOKEN"
```

**Response includes:** `skill_count` per pack.

### 135. `GET /api/v1/skills/packs/{pack_id}` — Get Skill Pack

**Auth:** Org admin

```bash
curl -s "$BASE/skills/packs/<pack-id>" -H "Authorization: Bearer $TOKEN"
```

### 136. `POST /api/v1/skills/packs` — Create Skill Pack

**Auth:** Org admin  
**Body:**
```json
{
  "source_url": "https://github.com/org/skill-pack",
  "name": "Core Skills",
  "description": "Essential skill collection",
  "branch": "main",
  "metadata_": {}
}
```

Only GitHub HTTPS URLs allowed. Upserts if source_url matches.

```bash
curl -s -X POST "$BASE/skills/packs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_url":"https://github.com/org/skills","name":"Core Skills"}'
```

**Errors:** `400` if URL validation fails.

### 137. `PATCH /api/v1/skills/packs/{pack_id}` — Update Skill Pack

**Auth:** Org admin  
**Body:** Same as create.

```bash
curl -s -X PATCH "$BASE/skills/packs/<pack-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Pack Name","branch":"develop"}'
```

### 138. `DELETE /api/v1/skills/packs/{pack_id}` — Delete Skill Pack

**Auth:** Org admin

```bash
curl -s -X DELETE "$BASE/skills/packs/<pack-id>" -H "Authorization: Bearer $TOKEN"
```

### 139. `POST /api/v1/skills/packs/{pack_id}/sync` — Sync Skill Pack

**Auth:** Org admin  
Clones the pack repository, discovers skills from `skills_index.json` or `**/SKILL.md` files, and upserts them into the marketplace.

```bash
curl -s -X POST "$BASE/skills/packs/<pack-id>/sync" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "pack_id": "uuid",
  "synced": 15,
  "created": 3,
  "updated": 2,
  "warnings": []
}
```

**Errors:** `400` if URL validation fails, `502` if clone fails.

---

## Souls Directory

Search and fetch soul template markdown from a community directory.

### 140. `GET /api/v1/souls-directory/search` — Search Souls

**Auth:** User or Agent  
**Query:** `q` (search text), `limit` (1-100, default 20)

```bash
curl -s "$BASE/souls-directory/search?q=developer&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "items": [
    {
      "handle": "openclaw",
      "slug": "developer",
      "page_url": "https://...",
      "raw_md_url": "https://..."
    }
  ]
}
```

### 141–142. `GET /api/v1/souls-directory/{handle}/{slug}` — Get Soul Markdown

**Auth:** User or Agent  
Also available as `GET /api/v1/souls-directory/{handle}/{slug}.md`

```bash
curl -s "$BASE/souls-directory/openclaw/developer" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "handle": "openclaw",
  "slug": "developer",
  "content": "# Developer Agent\n\nYou are a..."
}
```

**Errors:** `422` if handle/slug contains unsupported characters, `502` if fetch fails.

---

## SSE Streaming

MC1 uses Server-Sent Events (SSE) for real-time data streaming. All stream endpoints:

| Endpoint | Event Name | Auth |
|----------|------------|------|
| `GET /api/v1/boards/{id}/tasks/stream` | `task` | User/Agent |
| `GET /api/v1/boards/{id}/memory/stream` | `memory` | User/Agent |
| `GET /api/v1/boards/{id}/approvals/stream` | `approval` | User/Agent |
| `GET /api/v1/boards/{id}/group-memory/stream` | `memory` | User/Agent |
| `GET /api/v1/board-groups/{id}/memory/stream` | `memory` | Org member |
| `GET /api/v1/agents/stream` | `agent` | Org admin |
| `GET /api/v1/activity/task-comments/stream` | `comment` | Org member |

**Common query params:** `since` (ISO datetime), `board_id`, `is_chat`

**Polling interval:** 2 seconds  
**Ping interval:** 15 seconds  
**Deduplication window:** 2000 event IDs

### Connecting to SSE

```bash
curl -N "$BASE/boards/<board-id>/tasks/stream?since=2026-03-21T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

### SSE Data Format

```
event: task
data: {"type":"task.status_changed","activity":{...},"task":{...}}

event: memory
data: {"memory":{...}}

event: approval
data: {"approval":{...},"pending_approvals_count":2}
```

---

## Error Handling

### Error Response Shape

```json
{
  "detail": "Error message or structured object",
  "request_id": "uuid"
}
```

### Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `202` | Accepted (async processing) |
| `400` | Bad request |
| `401` | Not authenticated |
| `403` | Authenticated but not authorized |
| `404` | Resource not found |
| `409` | Conflict (duplicate, blocked task, pending approval) |
| `410` | Gone (disabled webhook) |
| `413` | Payload too large (webhook) |
| `422` | Validation error |
| `429` | Rate limited |
| `500` | Internal server error |
| `502` | Bad gateway (gateway dispatch failed) |

### Validation Errors (422)

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Blocked Task Error (409)

```json
{
  "detail": {
    "message": "Task is blocked by incomplete dependencies.",
    "code": "task_blocked_cannot_transition",
    "blocked_by_task_ids": ["uuid", "uuid"]
  }
}
```

### Pending Approval Conflict (409)

```json
{
  "detail": {
    "message": "Each task can have only one pending approval.",
    "conflicts": [
      {"task_id": "uuid", "approval_id": "uuid"}
    ]
  }
}
```

---

## Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| Agent auth (X-Agent-Token routes) | 20 requests | 60 seconds |
| Webhook ingest (POST .../webhooks/{id}) | 60 requests | 60 seconds |

**Response when exceeded:** `429 Too Many Requests`

**Backend options:**
- `memory` (default): Per-process, no external dependencies
- `redis`: Shared across workers via `RATE_LIMIT_REDIS_URL`

---

## Endpoint Index

Complete listing of all 142 endpoints by number:

| # | Method | Path | Auth | Category |
|---|--------|------|------|----------|
| 1 | GET | `/health` | None | Health |
| 2 | GET | `/healthz` | None | Health |
| 3 | GET | `/readyz` | None | Health |
| 4 | POST | `/api/v1/auth/bootstrap` | User | Auth |
| 5 | POST | `/api/v1/organizations` | User | Orgs |
| 6 | GET | `/api/v1/organizations/me/list` | User | Orgs |
| 7 | PATCH | `/api/v1/organizations/me/active` | User | Orgs |
| 8 | GET | `/api/v1/organizations/me` | OrgMember | Orgs |
| 9 | DELETE | `/api/v1/organizations/me` | OrgOwner | Orgs |
| 10 | GET | `/api/v1/organizations/me/member` | OrgMember | Orgs |
| 11 | GET | `/api/v1/organizations/me/members` | OrgMember | Orgs |
| 12 | GET | `/api/v1/organizations/me/members/{id}` | OrgMember | Orgs |
| 13 | PATCH | `/api/v1/organizations/me/members/{id}` | OrgAdmin | Orgs |
| 14 | PUT | `/api/v1/organizations/me/members/{id}/access` | OrgAdmin | Orgs |
| 15 | DELETE | `/api/v1/organizations/me/members/{id}` | OrgAdmin | Orgs |
| 16 | GET | `/api/v1/organizations/me/invites` | OrgAdmin | Orgs |
| 17 | POST | `/api/v1/organizations/me/invites` | OrgAdmin | Orgs |
| 18 | DELETE | `/api/v1/organizations/me/invites/{id}` | OrgAdmin | Orgs |
| 19 | POST | `/api/v1/organizations/invites/accept` | User | Orgs |
| 20 | GET | `/api/v1/users/me` | User | Users |
| 21 | PATCH | `/api/v1/users/me` | User | Users |
| 22 | DELETE | `/api/v1/users/me` | User | Users |
| 23 | GET | `/api/v1/gateways` | OrgAdmin | Gateways |
| 24 | POST | `/api/v1/gateways` | OrgAdmin | Gateways |
| 25 | GET | `/api/v1/gateways/{id}` | OrgAdmin | Gateways |
| 26 | PATCH | `/api/v1/gateways/{id}` | OrgAdmin | Gateways |
| 27 | POST | `/api/v1/gateways/{id}/templates/sync` | OrgAdmin | Gateways |
| 28 | DELETE | `/api/v1/gateways/{id}` | OrgAdmin | Gateways |
| 29 | GET | `/api/v1/gateways/status` | OrgAdmin | GwSessions |
| 30 | GET | `/api/v1/gateways/sessions` | OrgAdmin | GwSessions |
| 31 | GET | `/api/v1/gateways/sessions/{id}` | OrgAdmin | GwSessions |
| 32 | GET | `/api/v1/gateways/sessions/{id}/history` | OrgAdmin | GwSessions |
| 33 | POST | `/api/v1/gateways/sessions/{id}/message` | OrgAdmin | GwSessions |
| 34 | GET | `/api/v1/gateways/commands` | OrgAdmin | GwSessions |
| 35 | GET | `/api/v1/boards` | OrgMember | Boards |
| 36 | POST | `/api/v1/boards` | OrgAdmin | Boards |
| 37 | GET | `/api/v1/boards/{id}` | BoardRead | Boards |
| 38 | GET | `/api/v1/boards/{id}/snapshot` | BoardRead | Boards |
| 39 | GET | `/api/v1/boards/{id}/group-snapshot` | BoardRead | Boards |
| 40 | PATCH | `/api/v1/boards/{id}` | BoardWrite | Boards |
| 41 | DELETE | `/api/v1/boards/{id}` | BoardWrite | Boards |
| 42 | GET | `/api/v1/boards/{id}/memory` | BoardRead | Memory |
| 43 | GET | `/api/v1/boards/{id}/memory/stream` | BoardRead | Memory |
| 44 | POST | `/api/v1/boards/{id}/memory` | BoardWrite | Memory |
| 45 | GET | `/api/v1/boards/{id}/webhooks` | BoardRead | Webhooks |
| 46 | POST | `/api/v1/boards/{id}/webhooks` | BoardWrite | Webhooks |
| 47 | GET | `/api/v1/boards/{id}/webhooks/{wid}` | BoardRead | Webhooks |
| 48 | PATCH | `/api/v1/boards/{id}/webhooks/{wid}` | BoardWrite | Webhooks |
| 49 | DELETE | `/api/v1/boards/{id}/webhooks/{wid}` | BoardWrite | Webhooks |
| 50 | GET | `/api/v1/boards/{id}/webhooks/{wid}/payloads` | BoardRead | Webhooks |
| 51 | GET | `/api/v1/boards/{id}/webhooks/{wid}/payloads/{pid}` | BoardRead | Webhooks |
| 52 | POST | `/api/v1/boards/{id}/webhooks/{wid}` | None* | Webhooks |
| 53 | GET | `/api/v1/boards/{id}/onboarding` | BoardRead | Onboarding |
| 54 | POST | `/api/v1/boards/{id}/onboarding/start` | BoardWrite | Onboarding |
| 55 | POST | `/api/v1/boards/{id}/onboarding/answer` | BoardWrite | Onboarding |
| 56 | POST | `/api/v1/boards/{id}/onboarding/agent` | Agent | Onboarding |
| 57 | POST | `/api/v1/boards/{id}/onboarding/confirm` | BoardWrite | Onboarding |
| 58 | GET | `/api/v1/board-groups` | OrgMember | Groups |
| 59 | POST | `/api/v1/board-groups` | OrgAdmin | Groups |
| 60 | GET | `/api/v1/board-groups/{id}` | OrgMember | Groups |
| 61 | GET | `/api/v1/board-groups/{id}/snapshot` | OrgMember | Groups |
| 62 | POST | `/api/v1/board-groups/{id}/heartbeat` | User/Agent | Groups |
| 63 | PATCH | `/api/v1/board-groups/{id}` | OrgAdmin | Groups |
| 64 | DELETE | `/api/v1/board-groups/{id}` | OrgAdmin | Groups |
| 65 | GET | `/api/v1/board-groups/{id}/memory` | OrgMember | GroupMem |
| 66 | GET | `/api/v1/board-groups/{id}/memory/stream` | OrgMember | GroupMem |
| 67 | POST | `/api/v1/board-groups/{id}/memory` | OrgMember | GroupMem |
| 68 | GET | `/api/v1/boards/{id}/group-memory` | BoardRead | GroupMem |
| 69 | GET | `/api/v1/boards/{id}/group-memory/stream` | BoardRead | GroupMem |
| 70 | POST | `/api/v1/boards/{id}/group-memory` | BoardWrite | GroupMem |
| 71 | GET | `/api/v1/agents` | OrgAdmin | Agents |
| 72 | GET | `/api/v1/agents/stream` | OrgAdmin | Agents |
| 73 | POST | `/api/v1/agents` | User/Agent | Agents |
| 74 | GET | `/api/v1/agents/{id}` | OrgAdmin | Agents |
| 75 | PATCH | `/api/v1/agents/{id}` | OrgAdmin | Agents |
| 76 | POST | `/api/v1/agents/{id}/heartbeat` | User/Agent | Agents |
| 77 | POST | `/api/v1/agents/heartbeat` | User/Agent | Agents |
| 78 | DELETE | `/api/v1/agents/{id}` | OrgAdmin | Agents |
| 79 | GET | `/api/v1/agent/healthz` | Agent | AgentAPI |
| 80 | GET | `/api/v1/agent/boards` | Agent | AgentAPI |
| 81 | GET | `/api/v1/agent/boards/{id}` | Agent | AgentAPI |
| 82 | GET | `/api/v1/agent/agents` | Agent | AgentAPI |
| 83 | GET | `/api/v1/agent/boards/{id}/tasks` | Agent | AgentAPI |
| 84 | GET | `/api/v1/agent/boards/{id}/tags` | Agent | AgentAPI |
| 85 | GET | `/api/v1/agent/boards/{bid}/webhooks/{wid}/payloads/{pid}` | Agent | AgentAPI |
| 86 | POST | `/api/v1/agent/boards/{id}/tasks` | AgentLead | AgentAPI |
| 87 | PATCH | `/api/v1/agent/boards/{bid}/tasks/{tid}` | Agent | AgentAPI |
| 88 | DELETE | `/api/v1/agent/boards/{bid}/tasks/{tid}` | AgentLead | AgentAPI |
| 89 | GET | `/api/v1/agent/boards/{bid}/tasks/{tid}/comments` | Agent | AgentAPI |
| 90 | POST | `/api/v1/agent/boards/{bid}/tasks/{tid}/comments` | Agent | AgentAPI |
| 91 | GET | `/api/v1/agent/boards/{id}/memory` | Agent | AgentAPI |
| 92 | POST | `/api/v1/agent/boards/{id}/memory` | Agent | AgentAPI |
| 93 | GET | `/api/v1/agent/boards/{id}/approvals` | Agent | AgentAPI |
| 94 | POST | `/api/v1/agent/boards/{id}/approvals` | Agent | AgentAPI |
| 95 | POST | `/api/v1/agent/boards/{id}/onboarding` | Agent | AgentAPI |
| 96 | POST | `/api/v1/agent/agents` | AgentLead | AgentAPI |
| 97 | POST | `/api/v1/agent/boards/{bid}/agents/{aid}/nudge` | AgentLead | AgentAPI |
| 98 | POST | `/api/v1/agent/heartbeat` | Agent | AgentAPI |
| 99 | GET | `/api/v1/agent/boards/{bid}/agents/{aid}/soul` | Agent | AgentAPI |
| 100 | PUT | `/api/v1/agent/boards/{bid}/agents/{aid}/soul` | AgentLead | AgentAPI |
| 101 | DELETE | `/api/v1/agent/boards/{bid}/agents/{aid}` | AgentLead | AgentAPI |
| 102 | POST | `/api/v1/agent/boards/{id}/gateway/main/ask-user` | AgentLead | AgentAPI |
| 103 | POST | `/api/v1/agent/gateway/boards/{id}/lead/message` | AgentMain | AgentAPI |
| 104 | POST | `/api/v1/agent/gateway/leads/broadcast` | AgentMain | AgentAPI |
| 105 | GET | `/api/v1/boards/{id}/tasks` | BoardRead | Tasks |
| 106 | GET | `/api/v1/boards/{id}/tasks/stream` | BoardRead | Tasks |
| 107 | POST | `/api/v1/boards/{id}/tasks` | BoardWrite | Tasks |
| 108 | PATCH | `/api/v1/boards/{id}/tasks/{tid}` | User/Agent | Tasks |
| 109 | DELETE | `/api/v1/boards/{id}/tasks/{tid}` | BoardWrite | Tasks |
| 110 | GET | `/api/v1/boards/{id}/tasks/{tid}/comments` | User/Agent | Tasks |
| 111 | POST | `/api/v1/boards/{id}/tasks/{tid}/comments` | User/Agent | Tasks |
| 112 | GET | `/api/v1/boards/{id}/approvals` | BoardRead | Approvals |
| 113 | GET | `/api/v1/boards/{id}/approvals/stream` | BoardRead | Approvals |
| 114 | POST | `/api/v1/boards/{id}/approvals` | BoardWrite | Approvals |
| 115 | PATCH | `/api/v1/boards/{id}/approvals/{aid}` | BoardWrite | Approvals |
| 116 | GET | `/api/v1/tags` | OrgMember | Tags |
| 117 | POST | `/api/v1/tags` | OrgAdmin | Tags |
| 118 | GET | `/api/v1/tags/{id}` | OrgMember | Tags |
| 119 | PATCH | `/api/v1/tags/{id}` | OrgAdmin | Tags |
| 120 | DELETE | `/api/v1/tags/{id}` | OrgAdmin | Tags |
| 121 | GET | `/api/v1/organizations/me/custom-fields` | OrgMember | CustomFields |
| 122 | POST | `/api/v1/organizations/me/custom-fields` | OrgAdmin | CustomFields |
| 123 | PATCH | `/api/v1/organizations/me/custom-fields/{id}` | OrgAdmin | CustomFields |
| 124 | DELETE | `/api/v1/organizations/me/custom-fields/{id}` | OrgAdmin | CustomFields |
| 125 | GET | `/api/v1/activity` | User/Agent | Activity |
| 126 | GET | `/api/v1/activity/task-comments` | OrgMember | Activity |
| 127 | GET | `/api/v1/activity/task-comments/stream` | OrgMember | Activity |
| 128 | GET | `/api/v1/metrics/dashboard` | OrgMember | Metrics |
| 129 | GET | `/api/v1/skills/marketplace` | OrgAdmin | Skills |
| 130 | POST | `/api/v1/skills/marketplace` | OrgAdmin | Skills |
| 131 | DELETE | `/api/v1/skills/marketplace/{id}` | OrgAdmin | Skills |
| 132 | POST | `/api/v1/skills/marketplace/{id}/install` | OrgAdmin | Skills |
| 133 | POST | `/api/v1/skills/marketplace/{id}/uninstall` | OrgAdmin | Skills |
| 134 | GET | `/api/v1/skills/packs` | OrgAdmin | Skills |
| 135 | GET | `/api/v1/skills/packs/{id}` | OrgAdmin | Skills |
| 136 | POST | `/api/v1/skills/packs` | OrgAdmin | Skills |
| 137 | PATCH | `/api/v1/skills/packs/{id}` | OrgAdmin | Skills |
| 138 | DELETE | `/api/v1/skills/packs/{id}` | OrgAdmin | Skills |
| 139 | POST | `/api/v1/skills/packs/{id}/sync` | OrgAdmin | Skills |
| 140 | GET | `/api/v1/souls-directory/search` | User/Agent | Souls |
| 141 | GET | `/api/v1/souls-directory/{handle}/{slug}` | User/Agent | Souls |
| 142 | GET | `/api/v1/souls-directory/{handle}/{slug}.md` | User/Agent | Souls |

\* Webhook ingest (#52) has no auth but uses HMAC signature verification when configured.

---

## Agent Onboarding Flow

The complete flow for setting up a board with an AI lead agent:

```
1. POST /api/v1/boards                         → Create board with gateway_id
2. POST /api/v1/boards/{id}/onboarding/start    → Start onboarding conversation
3. Gateway agent sends questions via:
   POST /api/v1/boards/{id}/onboarding/agent    → Agent posts questions
4. User answers via:
   POST /api/v1/boards/{id}/onboarding/answer   → User sends answers
5. Steps 3-4 repeat (6-10 questions)
6. Agent sends completion:
   POST /api/v1/boards/{id}/onboarding/agent    → status=complete with goal/profile
7. POST /api/v1/boards/{id}/onboarding/confirm  → User confirms, lead agent provisioned
```

## Task Lifecycle

```
                    ┌─────────┐
                    │  inbox   │
                    └─┬───────┘
                      │ claim (worker)
                      │ assign+start (lead)
                      ▼
                ┌─────────────┐
                │ in_progress  │
                └─┬───────────┘
                  │ submit for review
                  ▼
              ┌─────────┐
              │  review  │ ← auto-assigned to lead
              └─┬───┬───┘
                │   │ reject → inbox (re-assigned to last worker)
                │   ▼
                │ ┌──────┐
                └►│ done  │ ← requires approval if board rule enabled
                  └──────┘
```

## Gateway Integration

MC1 communicates with OpenClaw gateways via RPC:
- **Template sync**: Push agent configurations to gateway
- **Session management**: List/inspect/message live agent sessions
- **Agent dispatch**: Send messages to agents via their sessions
- **Heartbeat sync**: Push heartbeat config changes to gateway agents
- **SOUL management**: Read/write agent SOUL.md through gateway

---

*This skill file was generated from source code analysis of all 22 backend router modules. Coverage: 142/142 endpoints (100%).*
