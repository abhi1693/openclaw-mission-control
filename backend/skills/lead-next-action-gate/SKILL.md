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
LEAD_NEXT_ACTION_HDRS="$(mktemp "${TMPDIR:-/tmp}/mc-lead-next-action-hdrs-${BOARD_ID}-${AGENT_ID}.XXXXXX.txt")"
export LEAD_NEXT_ACTION_JSON LEAD_NEXT_ACTION_HDRS
curl -fsS -D "$LEAD_NEXT_ACTION_HDRS" "$BASE_URL/api/v1/agent/boards/$BOARD_ID/lead/next-action" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_NEXT_ACTION_JSON"
LEAD_NEXT_ACTION_REQUEST_ID="$(grep -i '^x-request-id:' "$LEAD_NEXT_ACTION_HDRS" | head -1 | awk '{print $2}' | tr -d '\r')"
export LEAD_NEXT_ACTION_REQUEST_ID
echo "LEAD_NEXT_ACTION_REQUEST_ID $LEAD_NEXT_ACTION_REQUEST_ID"
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

The `LEAD_NEXT_ACTION_REQUEST_ID` echoed by the gate script is a
unique-per-call value the FastAPI middleware stamps on every
response. It is **not derivable from prior context** — every fresh
curl produces a new id. Quoting it in the heartbeat reply proves
the gate actually ran on this tick. If you ever produce a
heartbeat reply that names a blocker id from a `LEAD_NEXT_ACTION`
response without also quoting the matching `LEAD_NEXT_ACTION_REQUEST_ID`,
the operator's trajectory audit will catch it as fabricated
(see HEARTBEAT.md § Lead Next Action Gate / Mandatory evidence).

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

  **Gateway session signal.** `details.gateway_session` is the
  slice-4 projection of the agent's OpenClaw gateway session and tells
  you whether the worker is actually exchanging messages with the
  gateway right now or has gone silent. Branch:

  | `gateway_session` | What it means | Action |
  |---|---|---|
  | absent (key missing) | The MC backend wasn't built with slice-5 wiring. Treat as `null`. | Default nudge behaviour above. |
  | `null` | The subscriber has no row for this agent yet — newly-paired agent, subscriber recently restarted, or agent never opened a session. | Default nudge behaviour above. Do not infer agent health from absence. |
  | `aborted_last_run: true` | The agent's last gateway turn aborted (process crash, OOM, or gateway-side failure). Cite this in the nudge so the worker knows to recover, not just resume. | Nudge once with the abort context. If the same task surfaces with `aborted_last_run: true` on the next two heartbeats, escalate to a `Blocker` (`reason_code=worker_session_aborted`) and stop nudging. |
  | `last_changed_at_ms` recent (within ~2× heartbeat interval) | The agent IS actively working on the gateway side; the task DB just hasn't moved. | Pure nudge — the worker is alive, just slow. Do NOT reassign on this tick. |
  | `last_changed_at_ms` stale (>10 min, regardless of `last_phase`) | The agent is silent on the gateway. Combined with stale `in_progress_at`, the worker is likely wedged. | Nudge once, then watch. If `last_changed_at_ms` doesn't advance by the next heartbeat, escalate via `Blocker` (`reason_code=worker_silent_on_gateway`) and let DevOps recovery take over. |

  Convert `last_changed_at_ms` to America/Fortaleza pt-BR when posting
  the comment so the operator can read it directly. Never act on a
  partial signal: if `gateway_session` is present but you can't
  interpret the values (e.g. `last_phase` is unrecognised), proceed
  with default nudge behaviour and flag the unknown phase to the
  operator.
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
- `route_inbox`: use `lead-inbox-routing` for the returned task. If
  `reason_code=assigned_inbox_needs_lead_triage`, do not assume the assignee can
  self-advance it. Assigned inbox is lead-owned triage: either move it to
  `review` for review/QA intake, move it to `in_progress` only when assigning
  an implementation owner, create/decompose child work, or add a structured
  blocker/operator decision if it is intentionally parked. Do not leave
  `is_blocked=false` parked inbox tasks assigned to review-only agents.
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

- The endpoint returns `action="clear"`. The `reason_code` distinguishes the
  sub-state — emit `LEAD_NEXT_ACTION_DRAIN_CLEAR <count> <reason_code>` and
  continue to Memory Intake. Recognized clear reason_codes:
  - `no_active_work` — queue is empty (only `done`/`cancelled` tasks, or no tasks).
  - `only_pending_approval` — at least one review task is awaiting operator
    approval; nothing else is lead-actionable. Operator owns next move.
  - `only_blocked` — every active-state task is filtered by a structured
    `Blocker`, dependency, or `OperatorDecision`. Owners must resolve before
    the lead has work.
  - `only_fresh_in_progress` — every in_progress task is within the
    `IN_PROGRESS_PIPELINE_NUDGE_GRACE` window; backend is intentionally
    holding off the nudge.
  - `only_waiting_or_no_active_work` — legacy fallback for any state the
    classifier above didn't match. Treat as idle.

  Use the `details.pending_approval_count` / `blocked_count` /
  `fresh_in_progress_count` / `active_state_count` fields for telemetry —
  they tell the operator at a glance whether the board is genuinely idle or
  parked on someone else's action.
- The per-tick cap of **5 applied actions** is reached. Print
  `LEAD_NEXT_ACTION_DRAIN_CAP_REACHED <count>` with the list of applied
  task ids and stop the drain. The next heartbeat tick will pick up the
  remainder.
- An applied action raises an exception, returns 4xx/5xx from the backend,
  or hits the per-action failure path in `Failure Handling`. Record the
  friction once with `LEAD_NEXT_ACTION_DRAIN_FRICTION <count>` and stop.
  Do not retry the failed action in the same tick.
- The previous iteration's `(action, reason_code, task_id)` tuple
  matches the current one. Several mapped actions are pure
  comment/nudge operations (`inspect_stale_in_progress`,
  `cancel_orphan_child` when the child needs operator cancel,
  `materialize_decomposition_plan` when no plan comment exists yet) and
  do not change the gate's selector ranking — so two consecutive
  identical tuples mean the loop is wedged. The check is **consecutive
  only**, not "ever seen before": a non-consecutive repeat (A→B→A) is
  fine because something else changed in between. Implementation:
  - Hold a single `prev_tuple` slot, not a set.
  - Before applying the action, compute the current tuple. If
    `current_tuple == prev_tuple`, stop the drain with
    `LEAD_NEXT_ACTION_DRAIN_NOOP_REPEAT <count> <action> <task_id>`.
  - Otherwise apply the action, set `prev_tuple = current_tuple`,
    and re-fetch the gate.
  - The next heartbeat tick starts fresh; per-tick scope is the only
    scope that matters for tight-loop prevention.

Each drain iteration fetches fresh state, so transitions that unblock other
tasks (e.g. moving one approved task to `done` clears it from the queue and
the next iteration sees the second approved task) flow through naturally
without waiting for the next heartbeat tick.

The drain loop **only** re-applies actions the lead would normally apply in
a single tick. It is not a retry mechanism. Operator approvals that landed
during the tick are visible to subsequent iterations because the gate fetches
authoritative state each call. Do not exit to Memory Intake after the first
successful action — keep draining until one of the four exit conditions
above holds.

## Failure Handling

Do not convert a required next action into a generic health scan. If the action
cannot be applied because an owner, target, approval, pipeline field, or
runtime/deploy/source/contract fact is missing, create or reuse one structured
`Blocker` with the owner and unblock condition, then stop. If the missing input
is a human/operator choice, create or reuse one first-class `OperatorDecision`,
then stop. Do not set legacy `operator_decision_required` on active assigned
work.
