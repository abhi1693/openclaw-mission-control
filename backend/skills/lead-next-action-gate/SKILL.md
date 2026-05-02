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
  If `details.pipeline_ready` is false and `details.missing_pipeline_states`
  is non-empty, fetch the task pipeline and nudge the worker by role-owner.
  Use `details.missing_worker_pipeline_states` for the implementation worker
  (PF/PB) — these are events the worker owns (`code_changed`, `committed`,
  `live_build_verified`, `runtime_verified`). Use
  `details.missing_deploy_pipeline_states` for the DevOps owner — these are
  build/deploy events (`built`, `deployed`). The worker nudge should ask the
  worker to record its own events and to nudge DevOps for the deploy events;
  do not list deploy-owned states in the worker comment as if the worker owns
  them.
  The split assumes the default OpenClaw topology
  (`details.pipeline_owner_assumption == "default_openclaw_topology"`): DevOps
  owns build/deploy and the implementation worker owns code/runtime. If your
  board explicitly assigns deploy ownership to the implementation worker,
  treat both lists as worker-owned and nudge accordingly. Do not push pipeline states or HQCTL events on behalf of any owner —
  each role must emit its own provenance. Do not call `/review-readiness` for
  an `in_progress` task.
  The backend already enforces a grace window (`details.in_progress_grace_minutes`)
  before this action fires for missing pipeline events, so when you see this
  reason_code the task has been `in_progress` long enough to nudge — do not
  second-guess the threshold; record `details.in_progress_minutes` in the
  nudge comment for context.
- `inspect_stale_blocker`: the returned task has at least one open
  structured `Blocker` aged past `details.stale_blocker_grace_minutes`
  (currently 20 min, aligned with the in_progress nudge grace).
  ``_is_waiting()`` filters blocked tasks out of the lead's normal
  active queue, so without this tier they go invisible — AC5 incident
  at 2026-05-02 01:39 UTC sat blocked + invisible for ~12h. The lead
  must nudge the Blocker owner once, then stop. Owner resolution
  order:
  1. `details.acknowledged_by_agent_id` if non-null — that's the agent
     who claimed responsibility via PATCH `/blockers/{id}` with
     `status_transition=acknowledge`. Nudge them by direct message.
  2. Else `details.owner_role` if non-null — POST a comment on the
     task tagging the role (`@Programmer-Frontend`, `@DevOps`, etc.).
  3. Else fall back to the task's `assigned_agent_id` — open the task
     comments, post one nudge naming the open Blocker IDs (from
     `details.blocker_ids`) and reason codes (from
     `details.reason_codes`), and ask the assignee to either resolve
     each via PATCH `/blockers/{id}` `{status_transition: resolve}`
     once the unblock condition is met or post evidence of the
     blocker's continuing validity. Record
     `details.oldest_blocker_age_minutes` in the nudge so the owner
     sees the age. Do NOT silently resolve the Blocker yourself — the
     pipeline-shaped reason codes
     (`pipeline_missing_review_gate`,
     `in_progress_pipeline_missing_review_gate`) already auto-resolve
     once `pipeline.ready=true`, so a stale-blocker action with those
     reason_codes means the worker still hasn't filled in the missing
     events. For other reason codes (operator-policy, content-gate,
     etc.) the owner is the only valid resolver. After nudging, do
     not re-fire the action on the same task within the same tick —
     drain-loop dedup catches consecutive identical tuples.
- `route_inbox`: use `lead-inbox-routing` for the returned task.
- `materialize_decomposition_plan`: the returned task is in `inbox`,
  assigned to a reviewer (typically Architect), and has no children
  yet. The decomposition handshake is mid-flight: the assignee was
  asked to post a decomposition plan and the lead now needs to
  materialize it. Read the most recent decomposition comment on the
  task (look for "Architect decomposition for {task_id}" or similar
  marker), parse the per-AC subtask list, then for each subtask:
  POST `/tasks` with `assigned_agent_id`, `parent_task_id` (the
  current task's id), `depends_on_task_ids` (sibling ordering), and
  copied acceptance criteria. After all subtasks are created, retire
  the umbrella per `lead-inbox-routing`'s Umbrella Lifecycle. If no
  decomposition comment exists yet, post one nudge to the assignee
  asking for the plan, then stop. `details.assigned_agent_id` is
  echoed back in the action payload for convenience.
- `cancel_orphan_child`: the returned task is a non-terminal child whose
  parent reached a terminal state (`done`/`cancelled`). The parent's
  decomposition is over and this child is obsolete unless it carries
  independent work the parent didn't subsume. Verify by reading the
  task description + recent comments. If genuinely obsolete, post one
  `@operator` comment quoting `details.parent_task_id` and asking the
  operator to PATCH `{"status":"cancelled"}` (lead-cancel returns 403).
  If the child has independent work that should outlive the parent's
  decomposition, comment the rationale and ask the operator to either
  cancel the child or — if reparenting becomes a real need — to file
  a follow-up so engineering can add a re-parent endpoint
  (`parent_task_id` is currently immutable post-create). Do not
  attempt to PATCH `parent_task_id` yourself; the field is not in the
  ``TaskUpdate`` schema and the change will be silently dropped.
  `details.orphan_count` reports the total orphan candidates so the
  lead can decide whether to drain via the per-tick cap.
- `clear`: no structured lead action is currently required. Continue to memory
  intake, then health scan.

## Drain Loop (Process Multiple Ready Actions Per Tick)

After successfully applying an action, re-run the gate script in the same tick
to fetch the next action. Continue draining until one of these stop conditions
holds:

- The endpoint returns `action="clear"` (`reason_code=only_waiting_or_no_active_work`).
  Print `LEAD_NEXT_ACTION_DRAIN_CLEAR <count>` and continue to Memory Intake.
- The per-tick cap of **5 applied actions** is reached. Print
  `LEAD_NEXT_ACTION_DRAIN_CAP_REACHED <count>` with the list of applied
  task ids and stop the drain. The next heartbeat tick will pick up the
  remainder.
- An applied action raises an exception, returns 4xx/5xx from the backend,
  or hits the per-action failure path in `Failure Handling`. Record the
  friction once with `LEAD_NEXT_ACTION_DRAIN_FRICTION <count>` and stop.
  Do not retry the failed action in the same tick.

Each drain iteration fetches fresh state, so transitions that unblock other
tasks (e.g. moving one approved task to `done` clears it from the queue and
the next iteration sees the second approved task) flow through naturally
without waiting for the next heartbeat tick.

The drain loop **only** re-applies actions the lead would normally apply in
a single tick. It is not a retry mechanism. Operator approvals that landed
during the tick are visible to subsequent iterations because the gate fetches
authoritative state each call. Do not exit to Memory Intake after the first
successful action — keep draining until one of the three exit conditions
above holds.

## Failure Handling

Do not convert a required next action into a generic health scan. If the action
cannot be applied because an owner, target, approval, pipeline field, or
runtime/deploy/source/contract fact is missing, create or reuse one structured
`Blocker` with the owner and unblock condition, then stop. If the missing input
is a human/operator choice, create or reuse one first-class `OperatorDecision`,
then stop. Do not set legacy `operator_decision_required` on active assigned
work.
