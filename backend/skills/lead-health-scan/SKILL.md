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
- If the first friction is runtime/deploy/source/contract friction (missing
  deploy/live target, credential, source artifact, API endpoint, or validation
  evidence), create or reuse one structured `Blocker` on the task with
  `reason_code`, `owner_role`, and the narrowest useful
  `required_artifact`/`target_env`/`reopen_condition`. Then route one owner
  action and stop touching that task thread until the blocker resolves.
- If the first friction is a human/operator choice, create or reuse one
  first-class `OperatorDecision`, link dependent tasks, and stop touching those
  task threads until the decision resolves.
- Do not set legacy `operator_decision_required` on active assigned work.
- If the first friction is code/test/review feedback, classify the owner first,
  then move exactly that task through `rework -> in_progress -> review`.
- Offline agent with live task: recover once, then assign the task elsewhere if
  it still cannot move.

Do not post another "still blocked" comment. A comment is not routing.

## Stale Operator-Blocker Revalidation

When the scan finds a task with `is_blocked=true`, check whether the
underlying blocker can be revalidated rather than left waiting
indefinitely. The agent task-scan endpoint
(`/api/v1/agent/boards/$BOARD_ID/tasks`) returns each task with two
inline lists:

- `open_blocker_reason_codes` — codes from open structured `Blocker` rows
- `pending_operator_decision_reason_codes` — codes from pending
  `OperatorDecision` entities linked to the task

The task is also blocked if `operator_decision_required=true` (the legacy
boolean on `Task` that predates the structured entities). Such tasks
have no `reason_code` to dispatch on — they appear in the scan with
`is_blocked=true` but both code lists empty. Treat them as the **legacy
unstructured class** below.

### Per-code revalidation threshold and action

| `reason_code` | Stale-after | Probe + action |
|---|---|---|
| `gateway_ws_timeout` | 6h | Probe gateway WS handshake; if `HTTP/1.1 101 Switching Protocols` returns within 5 seconds, post one comment: `REVALIDATION_CANDIDATE reason_code=gateway_ws_timeout: gateway WS healthy at <ts>; @<assigned_owner> please retry one ACP spawn per acp-delegation § WS Timeout Idempotency, then update the blocker.` |
| `deploy_drift` | 6h | If the live target's loaded build hash now matches the source-of-truth commit, post `REVALIDATION_CANDIDATE reason_code=deploy_drift: live build matches source at <commit>; @DevOps confirm and resolve blocker.` |
| `external_dependency` | 24h | Post `REVALIDATION_CANDIDATE reason_code=external_dependency: <ageH>h old; @<owner> please confirm dependency status.` |
| `operator_policy`, `requirements_clarification`, `credential_required`, `infra_other` | n/a | Durable human decisions — do **not** auto-revalidate. Surface in the daily operator digest only. |
| unknown / null | n/a | Do not auto-revalidate. The canonical recognised set lives in `app/services/blocker_reason_codes.py`; treat anything else as opaque. |

The 24h threshold for `external_dependency` is intentionally longer than
the 6h infra threshold — vendor waits are normal; nudging at 6h would
spam. Codes not yet listed here default to "do not auto-revalidate".

### Legacy unstructured class

A task with `is_blocked=true`, both reason-code lists empty, AND
`operator_decision_required=true` is a legacy row from before the
structured `reason_code` field landed (alembic `f2b3c4d5e6a7`). The
skill cannot probe it — there's no machine signal to act on. **Surface
it once per 24h** with:

```
LEGACY_BLOCKED_TASK_NEEDS_TRIAGE: task=<id> updated_at=<ts> assigned=<owner>
@<lead> structured reason_code is missing on this task. Inspect the
latest blocker comment, file a `Blocker` or `OperatorDecision` with a
recognised `reason_code`, and resolve `operator_decision_required` so
revalidation dispatch can act on this task in the future.
```

This converts the legacy gap into a queue rather than a silent miss.

### Anti-spam rules

- Post at most one `REVALIDATION_CANDIDATE` (or `LEGACY_BLOCKED_TASK_NEEDS_TRIAGE`)
  comment per task per the per-code stale-after window. If a prior
  comment of the same kind exists newer than that window, skip and proceed
  to the next task. (Implementation: read the most recent N task
  comments for the marker prefix; compare timestamps. Use the
  comment-stream endpoint, not memory.)
- Never clear `operator_decision_required`, never `PATCH`
  `Blocker.resolved_at`, and never close an `OperatorDecision` from this
  skill — only the blocker's owner or operator can resolve.
- If the probe fails (gateway still unhealthy, build hash still
  mismatched), do not post anything. Silence is the correct signal that
  the blocker is still active.
- If a task carries multiple codes (one Blocker + one OperatorDecision),
  pick the highest-priority code per this order:
  `gateway_ws_timeout > deploy_drift > external_dependency > operator_durable codes > legacy`. Do
  not post one comment per code — one task, one revalidation candidate.
