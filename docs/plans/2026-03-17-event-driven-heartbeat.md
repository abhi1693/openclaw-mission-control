# Heartbeat Token Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce idle heartbeat token consumption by ~90% using OpenClaw's native config mechanisms — isolated sessions, lightContext, and a cheaper heartbeat model.

**Architecture:** The gateway's heartbeat system sends HEARTBEAT.md as prompt context to the LLM on every cycle. The cost comes from (a) accumulated session history being sent as context, and (b) using the full-capability model for simple heartbeat tasks. OpenClaw supports `isolatedSession: true` which uses a fresh session per heartbeat (no history = ~2-5K tokens instead of ~100K), and `lightContext: true` which limits bootstrap to only HEARTBEAT.md. Combined with a cheaper per-agent heartbeat model override, this achieves massive token reduction without changing the heartbeat contract.

**Tech Stack:** OpenClaw gateway config (`openclaw.json`), MC provisioning templates (Jinja2)

**Previous approach (deleted):** A bash pre-check gate in HEARTBEAT.md was proposed but fundamentally flawed — HEARTBEAT.md is prompt context sent TO the model, not a pre-model shell hook. The LLM call (and token consumption) happens before the agent reads the instructions. The bash gate would reduce output tokens but not the prompt tokens that are the bulk of the cost.

**Companion plan:** For true push-driven scheduling, see [docs/plans/2026-03-17-native-event-driven-wake.md](docs/plans/2026-03-17-native-event-driven-wake.md). This document is only about reducing token cost within the existing heartbeat contract.

---

## Current State

| Setting | Current Value | Problem |
|---------|---------------|---------|
| `heartbeat.lightContext` | `true` | Already good |
| `heartbeat.isolatedSession` | not set (false) | **Every heartbeat inherits full session history (~100K tokens)** |
| `heartbeat.model` | not set (uses primary) | **Using full-capability model for simple check-ins** |
| `compaction.mode` | `"safeguard"` | Helps but doesn't prevent history accumulation |
| Agent heartbeat intervals | 3-10 min | Aggressive — causes 144-336 LLM calls/day per agent |

**Root cause:** Without `isolatedSession`, each heartbeat sends the entire conversation history (all previous heartbeat runs, wakeup messages, tool outputs, etc.) as context. Sessions grow to 50-400K chars over time, causing qwen2.5:32b to timeout at 600s.

---

### Task 1: Enable isolated sessions and model override in gateway config

This is a config-only change to `~/.openclaw/openclaw.json`. No code changes, no gateway restart needed — the gateway hot-reloads these settings.

**Files:**
- Modify: `~/.openclaw/openclaw.json` on 192.168.2.60

**Step 1: Update `agents.defaults.heartbeat` config**

SSH to the gateway machine and update the config:

```bash
ssh root@192.168.2.60
```

```python
python3 -c "
import json

with open('/root/.openclaw/openclaw.json') as f:
    config = json.load(f)

defaults = config['agents']['defaults']
defaults['heartbeat'] = {
    'lightContext': True,
    'isolatedSession': True,
    'includeReasoning': False,
    'target': 'last',
    'every': '10m',
}

with open('/root/.openclaw/openclaw.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
print('Config saved.')
"
```

**Step 2: Verify gateway hot-reloaded**

```bash
tail -5 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep 'config change\|reload'
```

Expected: `config hot reload applied (agents.defaults.heartbeat...)`

If no hot-reload logged within 30s, wait — the gateway checks config periodically. Do NOT restart the gateway.

**Step 3: Commit config documentation**

Document what changed and why (do not commit the actual openclaw.json — it contains tokens):

```bash
git add docs/plans/2026-03-17-event-driven-heartbeat.md
git commit -m "docs: heartbeat optimization plan — isolated sessions + lightContext"
```

---

### Task 2: Tune per-agent heartbeat intervals

Not all agents need the same heartbeat frequency. Leads need faster cycles (they coordinate), workers can be slower (they react to assignments).

**Files:**
- Modify: `~/.openclaw/openclaw.json` on 192.168.2.60 (agents.list[].heartbeat)

**Step 1: Set role-appropriate intervals**

```python
python3 -c "
import json

with open('/root/.openclaw/openclaw.json') as f:
    config = json.load(f)

# Map agent names to optimized heartbeat intervals
intervals = {
    'Supervisor': '5m',       # Lead — needs faster cycle
    'Architect': '10m',       # Advisory — less frequent
    'Programmer-Frontend': '10m',
    'Programmer-Backend': '10m',
    'QA-Unit': '15m',         # Testing — can wait
    'QA-E2E': '15m',
    'DevOps': '15m',
}

for agent in config['agents']['list']:
    name = agent.get('name', agent.get('id', ''))
    if name in intervals:
        if 'heartbeat' not in agent:
            agent['heartbeat'] = {}
        agent['heartbeat']['every'] = intervals[name]
        print(f'  {name}: every={intervals[name]}')

with open('/root/.openclaw/openclaw.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
print('Config saved.')
"
```

**Step 2: Verify hot-reload**

```bash
tail -10 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep 'config change\|reload'
```

**Step 3: Calculate expected impact**

With the new intervals:
- Supervisor (5m): 288 heartbeats/day
- Architect, PF, PB (10m): 144 each = 432 total
- QA-Unit, QA-E2E, DevOps (15m): 96 each = 288 total

Total: ~1,008 heartbeats/day (vs ~1,008 before — similar count but each is 20-50x cheaper due to isolated sessions).

---

### Task 3: Slim down HEARTBEAT.md for isolated sessions

With `isolatedSession: true`, the agent starts fresh each heartbeat — no accumulated history. The HEARTBEAT.md template should be optimized for this: shorter, more direct, fewer instructions that assume persistent context.

**Files:**
- Modify: `backend/templates/BOARD_HEARTBEAT.md.j2`

**Step 1: Reduce the template size**

The current worker HEARTBEAT.md (lines 72-222) is ~4K chars. For isolated sessions, the agent doesn't need:
- The full OpenAPI discovery commands (it runs them every heartbeat anyway)
- Verbose Task Comment Format instructions (those belong in AGENTS.md or SOUL.md, loaded via normal bootstrap)
- Memory Maintenance instructions (move to a less frequent cycle)

Trim the worker section to focus on the essential heartbeat loop:

1. Pre-flight (health check only)
2. Check in via heartbeat endpoint
3. Check assigned tasks (inbox, in_progress)
4. If work exists → execute one task cycle
5. If idle → return HEARTBEAT_OK

The OpenAPI `jq` discovery commands (~20 lines) should be replaced with a direct reference: "Use the endpoints documented in TOOLS.md". This saves ~500 tokens per heartbeat.

Remove the Memory Maintenance section from the heartbeat loop — move it to a separate cron job or a less frequent cycle (every 2-3 days, as the current template suggests).

**Step 2: Verify template renders**

```bash
cd backend && uv run python -c "
from jinja2 import Environment, FileSystemLoader
from app.services.openclaw.provisioning import _templates_root
env = Environment(loader=FileSystemLoader(str(_templates_root())))
t = env.get_template('BOARD_HEARTBEAT.md.j2')
output = t.render(
    base_url='http://test:8000', auth_token='xxx', board_id='test-id',
    is_board_lead=False, is_main_agent=False,
    board_rule_require_review_before_done=True,
    board_rule_require_approval_for_done=True,
    board_rule_comment_required_for_review=True,
    board_rule_block_status_changes_with_pending_approval=True,
    board_rule_only_lead_can_change_status=False,
    board_rule_max_agents=6,
)
print(f'Template size: {len(output)} chars ({len(output)//4} est. tokens)')
"
```

Target: Under 2K chars (~500 tokens) for the worker section.

**Step 3: Run test suite**

```bash
cd backend && uv run pytest tests/ -x -q
```

Expected: All tests pass.

**Step 4: Commit**

```bash
git add backend/templates/BOARD_HEARTBEAT.md.j2
git commit -m "feat: slim HEARTBEAT.md for isolated session optimization"
```

---

### Task 4: Deploy and validate

**Step 1: Deploy updated template**

```bash
scp backend/templates/BOARD_HEARTBEAT.md.j2 root@192.168.2.64:/home/mcontrol/openclaw-mission-control/backend/templates/BOARD_HEARTBEAT.md.j2
```

**Step 2: Restart MC backend (NOT the gateway)**

```bash
ssh root@192.168.2.64 "pkill -f 'uvicorn app.main:app'; sleep 2; cd /home/mcontrol/openclaw-mission-control/backend && nohup /root/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/mc-backend.log 2>&1 &"
```

**Step 3: Sync templates**

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  "http://192.168.2.64:8000/api/v1/gateways/<gateway-id>/templates/sync?board_id=<board-id>"
```

**Step 4: Resume board and observe**

Resume via `/resume` in MC UI. Watch gateway logs:

```bash
ssh root@192.168.2.60 "tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep -i 'embedded_run\|agent_end'"
```

**What to look for:**
- Heartbeat runs should complete in 5-30s (not 2-5 min)
- No 600s timeouts (isolated sessions = tiny context)
- Agents should come online within 1-2 heartbeat cycles
- `ollama ps` should show reasonable context sizes (not 32768)

---

## Expected Impact

| Metric | Before | After | Why |
|--------|--------|-------|-----|
| Context per heartbeat | ~30-100K tokens | ~2-5K tokens | `isolatedSession` eliminates history |
| Heartbeat duration | 2-5 min (often timeout) | 5-30s | Smaller context = faster inference |
| Session bloat | Grows unbounded | Resets each run | Isolated = no accumulation |
| 600s timeouts | Frequent | None expected | Context fits comfortably |
| Token cost/day | ~10M+ tokens | ~1-2M tokens | ~80-90% reduction |

## What This Does NOT Do

- Does not skip the LLM call when idle (that requires a gateway-level change, not a config change)
- Does not reduce heartbeat frequency (agents still fire on their interval)
- Does not implement event-driven wakeups (see [docs/plans/2026-03-17-native-event-driven-wake.md](docs/plans/2026-03-17-native-event-driven-wake.md))

The token savings come entirely from **smaller context per call** (isolated sessions + slimmer template), not from fewer calls.

## Future Enhancements (not in scope)

- **Cron-based monitoring:** Replace heartbeat with cron jobs that use `sessionTarget: "isolated"` and cheaper models for pure monitoring tasks. Reserve heartbeat for context-aware work.
- **Webhook-driven wakeup:** Fire agent runs only when tasks are assigned, rather than polling. See [docs/plans/2026-03-17-native-event-driven-wake.md](docs/plans/2026-03-17-native-event-driven-wake.md).
- **Per-agent model override:** Use `heartbeat.model` to assign a smaller/faster model for heartbeat runs specifically (e.g., qwen2.5:7b for heartbeats, qwen3.5:27b for real work).
