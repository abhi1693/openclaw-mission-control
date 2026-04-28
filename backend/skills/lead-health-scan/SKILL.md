---
name: lead-health-scan
description: Use when a board lead has cleared next-action and memory-intake gates and must choose one closest-to-done board friction to route.
---

# Lead Health Scan

Use this only as a board lead, after `lead-next-action-gate` and
`lead-memory-intake` have cleared or their required action has been applied or
parked.

## Scan Script

```bash
LEAD_TASKS_JSON="$(mktemp "${TMPDIR:-/tmp}/mc-lead-tasks-${BOARD_ID}-${AGENT_ID}.XXXXXX.json")"
LEAD_AGENTS_JSON="$(mktemp "${TMPDIR:-/tmp}/mc-lead-agents-${BOARD_ID}-${AGENT_ID}.XXXXXX.json")"
export LEAD_TASKS_JSON LEAD_AGENTS_JSON
curl -fsS "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?limit=200" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_TASKS_JSON"
curl -fsS "$BASE_URL/api/v1/agent/agents?board_id=$BOARD_ID&limit=100" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_AGENTS_JSON"
python3 - <<'PY'
import json, os
from datetime import datetime, timezone

T = json.load(open(os.environ["LEAD_TASKS_JSON"])).get("items", [])
A = {a["id"]: a for a in json.load(open(os.environ["LEAD_AGENTS_JSON"])).get("items", []) if isinstance(a, dict)}
now = datetime.now(timezone.utc)
for t in T:
    s = t.get("status", "")
    if s not in ("in_progress", "review", "rework", "inbox"):
        continue
    aid = t.get("assigned_agent_id", "") or "unassigned"
    a = A.get(aid, {})
    ua = t.get("updated_at") or t.get("created_at", "")
    dt = datetime.fromisoformat(ua.replace("Z", "+00:00")) if ua else now
    age = int((now - dt).total_seconds() / 60)
    blk = "BLOCKED" if t.get("is_blocked") else ""
    dp = t.get("depends_on_task_ids") or []
    print(f"{s:12} {age:4}m  agent={aid}  agent_status={a.get('status', '?')}  {blk}{(' deps=' + str(dp)) if dp else ''}  {t['title'][:40]}  {t['id']}")
done = sum(1 for t in T if t.get("status") == "done")
total = len(T)
print(f"done={done}/{total}")
busy = {t.get("assigned_agent_id") for t in T if t.get("status") in ("in_progress", "review", "rework")}
for a in json.load(open(os.environ["LEAD_AGENTS_JSON"])).get("items", []):
    n, i = a.get("name", ""), a["id"]
    tag = "IDLE" if i not in busy else "BUSY"
    for k, p in [("Architect", "ARCHITECT"), ("QA-Unit", "QA_UNIT"), ("QA-E2E", "QA_E2E"), ("Frontend", "PF"), ("Backend", "PB"), ("DevOps", "DEVOPS")]:
        if k in n:
            print(f"{p}_ID={i} {tag}")
PY
```

If a generated curl returns 404, schema mismatch, or an unexpected 4xx,
refresh OpenAPI per `TOOLS.md` and derive the current agent-lead endpoint
instead of guessing.

## Closest-To-Done Order

Choose one task, route one friction, then stop:

1. approved review tasks that still need a done transition
2. review tasks missing exactly one required gate
3. assigned rework with a clear owner and failing dimension
4. stale `in_progress` work with no represented blocker
5. unassigned `inbox` work that can be routed or decomposed

Age tells you where to inspect; it does not justify reminder comments. Use
agent UUIDs from the scan, not `$AGENT_ID`.

## Routing Rules

- If the next action is owned and executable, let the owner work. Do not post a
  hold comment.
- If the first friction is missing deploy/live target, credential, or operator
  action, create or reuse one `OperatorDecision`, link dependent tasks, and
  route one DevOps/operator action. Then stop touching those task threads until
  the decision resolves.
- If the first friction is code/test/review feedback, classify the owner first,
  then move exactly that task through `rework -> in_progress -> review`.
- Offline agent with live task: recover once, then assign the task elsewhere if
  it still cannot move.

Do not post another "still blocked" comment. A comment is not routing.
