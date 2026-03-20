# Heartbeat Token Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce idle heartbeat token consumption by ~80-90% using OpenClaw's native config mechanisms — isolated sessions, lightContext, and conservative template trimming that preserves the existing heartbeat contract.

**Architecture:** The gateway's heartbeat system sends HEARTBEAT.md as prompt context to the LLM on every cycle. The cost comes from (a) accumulated session history being sent as context, and (b) verbose template instructions repeated every cycle. OpenClaw supports `isolatedSession: true` (fresh session per heartbeat = ~2-5K tokens instead of ~100K) and `lightContext: true` (limits bootstrap to HEARTBEAT.md only). These must be persisted in BOTH the MC codebase defaults AND the gateway config to survive re-provisioning.

**Tech Stack:** OpenClaw gateway config (`openclaw.json`), MC constants (`constants.py`), MC agent API, Jinja2 templates

**What this does NOT do:** Does not skip the LLM call when idle (that requires a gateway-level change). Does not implement event-driven wakeups. Token savings come entirely from smaller context per call, not fewer calls.

---

## Current State

| Setting | Current Value | Problem |
|---------|---------------|---------|
| `DEFAULT_HEARTBEAT_CONFIG` in constants.py | `every: 10m, target: last, includeReasoning: false` | Missing `isolatedSession` and `lightContext` |
| `heartbeat.isolatedSession` | not set (false) | Every heartbeat inherits full session history (~100K tokens) |
| `heartbeat.lightContext` | set on gateway only, not in MC defaults | Ephemeral — will be overwritten on next provisioning sync |
| `compaction.mode` | `"safeguard"` | Helps but doesn't prevent history accumulation |
| Agent `heartbeat_config` in DB | `every` varies per agent (3-10m) | Not optimized for role |

---

### Task 1: Update MC codebase defaults (durable change)

This ensures `isolatedSession` and `lightContext` persist across agent provisioning cycles.

**Files:**
- Modify: `backend/app/services/openclaw/constants.py`
- Test: `backend/tests/test_heartbeat_config_defaults.py` (new, for the config)

**Step 1: Write the failing test**

```python
# backend/tests/test_heartbeat_config_defaults.py
"""Verify heartbeat defaults include isolation and light context."""

from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG


def test_default_heartbeat_config_has_isolated_session():
    assert DEFAULT_HEARTBEAT_CONFIG.get("isolatedSession") is True


def test_default_heartbeat_config_has_light_context():
    assert DEFAULT_HEARTBEAT_CONFIG.get("lightContext") is True


def test_default_heartbeat_config_has_every():
    assert DEFAULT_HEARTBEAT_CONFIG.get("every") == "10m"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_heartbeat_config_defaults.py -v`
Expected: FAIL — `isolatedSession` not in DEFAULT_HEARTBEAT_CONFIG

**Step 3: Update the defaults**

In `backend/app/services/openclaw/constants.py`, replace the `DEFAULT_HEARTBEAT_CONFIG`:

```python
DEFAULT_HEARTBEAT_CONFIG: dict[str, Any] = {
    "every": "10m",
    "target": "last",
    "includeReasoning": False,
    "isolatedSession": True,
    "lightContext": True,
}
```

**Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_heartbeat_config_defaults.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `cd backend && uv run pytest tests/ -x -q`
Expected: All tests pass (469+)

**Step 6: Commit**

```bash
git add backend/app/services/openclaw/constants.py backend/tests/test_heartbeat_config_defaults.py
git commit -m "feat: add isolatedSession and lightContext to default heartbeat config"
```

---

### Task 2: Update per-agent heartbeat intervals via MC API

Persist role-appropriate intervals in the MC database so they survive re-provisioning. Use the existing agent PATCH API.

**Files:**
- No code changes — API calls only

**Important safety note:** `heartbeat_config` is patched as a full object, not deep-merged field-by-field. Do **not** send a partial object unless you first merge it with the agent's current `heartbeat_config`, or you may accidentally delete settings like `model`, `target`, `accountId`, or `activeHours`.

**Step 1: Read current agent heartbeat_config values first**

```bash
curl -s -H "Authorization: Bearer <token>" \
  "<mc-base-url>/api/v1/agents?board_id=<board-id>&limit=50" > /tmp/agents.json
```

Review the current config before patching:

```bash
python3 - <<'PY'
import json

with open('/tmp/agents.json') as f:
  data = json.load(f)

for agent in data.get('items', []):
  print(
      agent['id'],
      agent['name'],
      agent.get('is_board_lead'),
      agent.get('identity_profile'),
      agent.get('heartbeat_config'),
  )
PY
```

Build an `agent_id -> interval` mapping from this inventory. Use stable UUIDs from the API response, not human-readable display names.

**Step 2: Merge and PATCH agent heartbeat_config via MC API**

For each agent, PATCH the merged `heartbeat_config`. This updates the MC database, and the next template sync propagates it to the gateway.

```bash
python3 - <<'PY'
import json
import subprocess

TOKEN = '<token>'
BASE = '<mc-base-url>'

with open('/tmp/agents.json') as f:
  agents = json.load(f).get('items', [])

# Build this from Step 1 using agent ids that are stable for this board.
intervals_by_id = {
  '<lead-agent-id>': '5m',
  '<architect-agent-id>': '10m',
  '<frontend-agent-id>': '10m',
  '<backend-agent-id>': '10m',
  '<qa-unit-agent-id>': '15m',
  '<qa-e2e-agent-id>': '15m',
  '<devops-agent-id>': '15m',
}

for agent in agents:
  agent_id = agent['id']
  if agent_id not in intervals_by_id:
    continue
  heartbeat = dict(agent.get('heartbeat_config') or {})
  heartbeat['every'] = intervals_by_id[agent_id]
  heartbeat['isolatedSession'] = True
  heartbeat['lightContext'] = True
  payload = json.dumps({'heartbeat_config': heartbeat})
  result = subprocess.run([
    'curl', '-sf', '-X', 'PATCH',
    '-H', f'Authorization: Bearer {TOKEN}',
    '-H', 'Content-Type: application/json',
    f'{BASE}/api/v1/agents/{agent_id}',
    '-d', payload,
  ], check=True, capture_output=True, text=True)
  print(f'patched {agent_id} ({agent["name"]}): {heartbeat}')
  print(f'  response: {result.stdout[:200]}')
PY
```

If your deployment already stores stable role metadata in `identity_profile`, you can generate `intervals_by_id` from that field first, then review the UUID mapping before patching. Do not rely on `name`, because it is an editable display field.

**Step 3: Verify by reading agent config back**

```bash
curl -s -H "Authorization: Bearer <token>" "<mc-base-url>/api/v1/agents?board_id=<board-id>&limit=50" | \
  python3 -c "import sys,json; [print(f'{a[\"id\"]} {a[\"name\"]}: {a.get(\"heartbeat_config\")}') for a in json.load(sys.stdin).get('items',[])]"
```

Expected: Each agent shows the updated `heartbeat_config` with `isolatedSession: true`.

**Step 4: Sync templates to propagate to gateway**

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  "<mc-base-url>/api/v1/gateways/<gateway-id>/templates/sync?board_id=<board-id>"
```

The sync calls `_heartbeat_config()` which merges `DEFAULT_HEARTBEAT_CONFIG` (now including `isolatedSession`, `lightContext`) with the per-agent `heartbeat_config` from the DB, then writes to the gateway.

**Step 5: Verify gateway config updated**

```bash
ssh <gateway-host> "cat <gateway-openclaw-config> | python3 -c '
import sys, json
for a in json.load(sys.stdin).get(\"agents\",{}).get(\"list\",[]):
    name = a.get(\"name\",\"?\")
    hb = a.get(\"heartbeat\",{})
    print(f"{name}: {json.dumps(hb, sort_keys=True)}")
'"
```

Expected: The relevant agents show `isolatedSession: true` and the correct `every` interval. Cross-check the printed names against the inventory you captured in Step 1 instead of hardcoding name filters in the verification command.

---

### Task 3: Trim HEARTBEAT.md conservatively for isolated sessions

With `isolatedSession: true` + `lightContext: true`, HEARTBEAT.md is the agent's primary injected instruction source during heartbeat runs. AGENTS.md, SOUL.md, and other bootstrap files are not injected automatically. This means the optimization must be conservative.

- **MUST keep:** Pre-Flight Checks, Non-Negotiable Rules, Worker/Lead Loop, HEARTBEAT_OK criteria
- **MUST keep:** Task comment rules/format, board rule snapshot, and a memory-maintenance note
- **Safe to shorten:** Repeated OpenAPI discovery blocks, duplicate explanatory prose, and low-value narrative text

**Files:**
- Modify: `backend/templates/BOARD_HEARTBEAT.md.j2`

**Step 1: Condense the OpenAPI discovery blocks (keep inline, shorten)**

With `lightContext: true`, HEARTBEAT.md is the agent's only injected instruction source — TOOLS.md is NOT in the prompt context. The agent CAN read TOOLS.md from the workspace via tool use, but cannot be assumed to know it exists unless told. Therefore, the inline jq blocks must stay as the agent's self-contained API discovery mechanism.

Instead of removing the jq blocks entirely, condense each one into a single compact command. Replace the multi-line `jq -r '...'` filter blocks (lead-focused and worker-focused) with a shorter version that produces the same output:

```markdown
Before API-heavy work, refresh the endpoint list:

` ` `bash
curl -fsS "{{ base_url }}/openapi.json" -o /tmp/openapi.json
jq -r '.paths | to_entries[] | .key as $p | .value | to_entries[] | select((.value.tags // []) | index("agent-worker")) | "\(.key|ascii_upcase) \($p) \(.value.summary // "")"' /tmp/openapi.json | sort
` ` `
```

This preserves the API-safety contract (agents discover endpoints at runtime) while halving the jq block size (~10 lines → ~4 lines per role).

**Step 2: Compress memory maintenance, but keep it in HEARTBEAT.md**

Replace the Memory Maintenance section with:
```markdown
## Memory Maintenance
Do not perform memory maintenance on every heartbeat. Only do it when explicitly instructed, when there is clear net-new durable information to preserve, or on slower cadences where the heartbeat interval is greater than 1 hour.
```

This keeps the behavior visible to the agent while avoiding routine token burn.

**Step 3: Do not remove task comment or board-rule sections**

Keep these sections intact:
- `## Non-Negotiable Rules`
- `### Board Rule Snapshot`
- `## Task Comment Format`
- `## When to Return HEARTBEAT_OK`

These are part of the operational contract when HEARTBEAT.md is the primary injected instruction source.

**Step 4: Verify template renders and check size**

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
before_size = 5500  # approximate current size
after_size = len(output)
print(f'Template size: {after_size} chars (~{after_size//4} tokens)')
print(f'Reduction: {before_size - after_size} chars saved')
assert 'Pre-Flight' in output, 'Pre-Flight Checks must remain'
assert 'Non-Negotiable' in output, 'Non-Negotiable Rules must remain'
assert 'Board Worker Loop' in output or 'Board Lead Loop' in output, 'Work loop must remain'
assert 'Task Comment Format' in output, 'Task Comment Format must remain'
assert 'HEARTBEAT_OK' in output, 'HEARTBEAT_OK criteria must remain'
print('All required sections present')
"
```

Target: meaningful reduction without breaking the heartbeat contract. A 15-30% prompt reduction is acceptable if it keeps the behavioral guarantees intact.

**Step 5: Run test suite**

```bash
cd backend && uv run pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add backend/templates/BOARD_HEARTBEAT.md.j2
git commit -m "feat: slim HEARTBEAT.md for isolated session heartbeats"
```

---

### Task 4: Deploy and validate

**Step 1: Deploy updated files**

```bash
scp backend/app/services/openclaw/constants.py <mc-host>:<mc-repo-root>/backend/app/services/openclaw/constants.py
scp backend/templates/BOARD_HEARTBEAT.md.j2 <mc-host>:<mc-repo-root>/backend/templates/BOARD_HEARTBEAT.md.j2
```

**Step 2: Restart MC backend (NOT the gateway)**

```bash
ssh <mc-host> "pkill -f 'uvicorn app.main:app'; sleep 2; cd <mc-repo-root>/backend && nohup <uv-bin> run uvicorn app.main:app --host 0.0.0.0 --port <mc-port> > /tmp/mc-backend.log 2>&1 &"
```

Verify: `curl -s <mc-base-url>/health` returns `{"ok":true}`

**Step 3: Run Task 2 merge-safe API calls to persist per-agent intervals**

Execute the PATCH calls from Task 2 Step 2.

**Step 4: Sync templates**

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  "<mc-base-url>/api/v1/gateways/<gateway-id>/templates/sync?board_id=<board-id>"
```

**Step 5: Verify HEARTBEAT.md on gateway**

```bash
ssh <gateway-host> "find <gateway-workspace-root> -path '*/HEARTBEAT.md' -print0 | xargs -0 wc -c"
```

Prefer narrowing the `find` path to the specific board workspace if your gateway hosts multiple boards. The rendered file should be smaller than before, roughly ~3-4K chars instead of ~5.5K.

**Step 6: Resume board and observe**

Resume via `/resume` in MC UI. Watch:

```bash
ssh <gateway-host> "tail -f <gateway-log-dir>/openclaw-$(date +%Y-%m-%d).log | grep -i 'embedded_run\|agent_end'"
```

**What to look for:**
- Heartbeat runs complete in 5-30s (not 2-5 min)
- No 600s timeouts (isolated session = no accumulated history)
- Agents come online within 1-2 heartbeat cycles
- Gateway log shows `isolatedSession` or `cron:` session keys (not the main session key)

---

## Rollback

If `isolatedSession` causes issues (agents can't complete multi-step work in one heartbeat):

1. Revert `constants.py` to remove `isolatedSession` and `lightContext`
2. Restart MC backend (so reverted constants are live in the running process)
3. PATCH each agent's `heartbeat_config` using the same merge-safe workflow from Task 2, removing only the new fields you intend to roll back
4. Run template sync (now reads the reverted defaults from the restarted process)

---

## Expected Impact

| Metric | Before | After | Why |
|--------|--------|-------|-----|
| Context per heartbeat | ~30-100K tokens | ~2-5K tokens | `isolatedSession` eliminates history |
| Template size | ~5.5K chars (~1,375 tokens) | ~4-4.5K chars | Conservative trimming while preserving contract |
| Heartbeat duration | 2-5 min (often timeout) | 5-30s | Smaller context = faster inference |
| Session bloat | Grows unbounded | Resets each run | Isolated = no accumulation |
| 600s timeouts | Frequent | None expected | Context fits comfortably |
| Token cost/day (7 agents) | ~10M+ tokens | ~1-2M tokens | ~80-90% reduction |

## Future Enhancements (not in scope)

- **Per-agent model override:** Use `heartbeat.model` to assign a smaller model for heartbeat runs (e.g., qwen2.5:7b for heartbeats, main model for real work).
- **Webhook-driven wakeup:** Fire agent runs only when tasks are assigned.
- **Cron-based monitoring:** Replace heartbeat with cron jobs for pure status checks.
