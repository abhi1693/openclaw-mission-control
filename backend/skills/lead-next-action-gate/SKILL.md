---
name: lead-next-action-gate
description: Use when a board lead heartbeat must check Mission Control's structured next lead action before memory intake, health scans, or manual task routing.
---

# Lead Next Action Gate

Use this only as a board lead. This gate runs first on every lead heartbeat,
before memory intake, health scans, task-list scans, or ad hoc nudges.

## Contract

The backend ranks the board by closest-to-done state and returns one explicit
action candidate. If the gate prints `LEAD_NEXT_ACTION_REQUIRED`, do not return
`HEARTBEAT_OK` until this tick applies that action or records the first concrete
friction that prevents it.

## Gate Script

```bash
LEAD_NEXT_ACTION_JSON="$(mktemp "${TMPDIR:-/tmp}/mc-lead-next-action-${BOARD_ID}-${AGENT_ID}.XXXXXX.json")"
export LEAD_NEXT_ACTION_JSON
curl -fsS "$BASE_URL/api/v1/agent/boards/$BOARD_ID/lead/next-action" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_NEXT_ACTION_JSON"
python3 - <<'PY'
import json, os
action=json.load(open(os.environ["LEAD_NEXT_ACTION_JSON"]))
print("LEAD_NEXT_ACTION", json.dumps(action, sort_keys=True))
if action.get("action_required"):
    print("LEAD_NEXT_ACTION_REQUIRED", action.get("action"), action.get("reason_code"), action.get("task_id"))
    raise SystemExit(2)
print("LEAD_NEXT_ACTION_CLEAR", action.get("reason_code"))
PY
```

If the curl returns 401/403/404/429, 5xx, or a schema mismatch, report
`HEARTBEAT_FAILED` with the status/body and refresh OpenAPI per `TOOLS.md`
before guessing an endpoint.

## Action Mapping

- `mark_done`: run `lead-review-routing` for the returned task. Patch `done`
  only after required review gates, approval freshness, and container/subtask
  lifecycle are confirmed. If the patch fails, report the HTTP body as the
  friction.
- `inspect_review_gates`: run `lead-review-routing` for the returned task
  before any other review task.
- `review_task_ready_for_approval`: confirm readiness still has `ready=true`,
  `approval_state=none`, and no missing pipeline states; then create exactly
  one pending approval request. Do not approve it yourself.
- `approved_review_needs_done_gate`: confirm approval freshness and all
  required gates before patching `done`.
- `route_rework`: inspect the latest blocking review verdict, route or nudge
  the assigned owner once, then stop.
- `inspect_stale_in_progress`: if `details.pipeline_ready` is true, the
  implementation worker owns the `in_progress` to `review` transition. Post one
  direct comment/nudge asking that worker to PATCH `review` with
  `packet_commit_sha` and final packet context. Do not patch review as lead.
  If `details.missing_pipeline_states` is present, fetch the task pipeline and
  request the worker to fix the missing structured implementation event fields.
  Do not push pipeline states or HQCTL events on behalf of the worker — the
  implementation owner must emit their own provenance. Do not call
  `/review-readiness` for an `in_progress` task.
- `route_inbox`: use `lead-inbox-routing` for the returned task.
- `clear`: no structured lead action is currently required. Continue to memory
  intake, then health scan.

## Failure Handling

Do not convert a required next action into a generic health scan. If the action
cannot be applied because an owner, target, approval, pipeline field, or
operator decision is missing, record that specific friction once and stop.
