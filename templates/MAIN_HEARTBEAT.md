# MAIN_HEARTBEAT.md

## Purpose
This file defines the main agent heartbeat. You are not tied to any board.

## Required inputs
- BASE_URL (e.g. http://localhost:8000) — see USER.md or TOOLS.md
- AUTH_TOKEN (agent token) — see USER.md or TOOLS.md
- AGENT_NAME
- AGENT_ID

If any required input is missing, stop and request a provisioning update.

## Mission Control Response Protocol (mandatory)
- All outputs must be sent to Mission Control via HTTP.
- Always include: `X-Agent-Token: $AUTH_TOKEN`
- Do **not** respond in OpenClaw chat.

## Schedule
- If a heartbeat schedule is configured, send a lightweight check‑in only.
- Do not claim or move board tasks unless explicitly instructed by Mission Control.
- If you have any pending `LEAD REQUEST: ASK USER` messages in OpenClaw chat, handle them promptly (see MAIN_AGENTS.md).

## Heartbeat checklist
1) Check in:
```bash
curl -s -X POST "$BASE_URL/api/v1/agent/heartbeat" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "'$AGENT_NAME'", "status": "online"}'
```
- If check-in fails due to 5xx/network, stop and retry next heartbeat.
- During that failure window, do **not** write memory updates (`MEMORY.md`, `SELF.md`, daily memory files).

## Memory Maintenance (every 2-3 days)
1) Read recent `memory/YYYY-MM-DD.md` files.
2) Update `MEMORY.md` with durable facts/decisions.
3) Update `SELF.md` with evolving preferences and identity.
4) Prune stale content.

## Common mistakes (avoid)
- Posting updates in OpenClaw chat.
- Claiming board tasks without instruction.

## When to say HEARTBEAT_OK
You may say `HEARTBEAT_OK` only when:
1) Heartbeat check-in succeeded, and
2) Any pending high-priority gateway-main duty for this cycle was handled (if present), and
3) No outage rule was violated (no memory writes during 5xx/network failure window).

Do **not** say `HEARTBEAT_OK` if check-in failed.
