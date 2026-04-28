---
name: lead-review-routing
description: Use when a board lead must decide what to do with a task in `review` status — whether to mark done, request approval, route to the next reviewer, or push to rework based on reviewer verdicts and approval freshness.
---

# Lead Review Routing

Use this only as a board lead, only on tasks currently in `review` status. The skill owns the approved→done decision tree, required reviewer gates, FAIL/INCONCLUSIVE handling, and rework routing.

For Mission Control, this skill is the canonical source for review-to-done decisions, gate freshness rules, and rework routing. `AGENTS.md § Lead Board Playbook / Step 3` should point here instead of duplicating the gate logic.

This skill never reviews work itself. The lead reads reviewer verdicts and routes; the lead does not author verdicts.

## Scope Boundaries

- Only `review` status. Do not run this for `inbox`, `in_progress`, or `rework`.
- Do not nudge QA/Architect/DevOps for non-`review` tasks.
- Do not move status to `done` from `in_progress`. The implementation worker owns the `in_progress`→`review` transition (per `acp-post-review` and `packet_commit_sha` rule).

## Lead Next Action Mapping

If `/lead/next-action` returns `action=inspect_review_gates`, inspect the
returned review task with this skill before Memory Intake or health scan.

If `reason_code=review_task_ready_for_approval`, confirm the readiness payload
for the same task still has `ready=true`, `approval_state=none`, and no missing
pipeline states. Then create exactly one pending approval request. Do not
approve it yourself.

If `reason_code=approved_review_needs_done_gate`, confirm approval freshness
and all required gates before patching `done`.

## Step 1 — Fetch Comments and Approvals

For each `review` task, fetch the latest task comments and approval state. Inspect:

- newest worker packet (commit, build/artifact, evidence type)
- reviewer verdicts and timestamps (Architect, QA-Unit, QA-E2E, DevOps as applicable)
- approval state (`pending`, `approved`, `rejected`, or absent)
- target/build/artifact ids in approval payload vs. latest packet
- blocking findings called out by reviewers

The latest worker packet is authoritative for "what is currently being reviewed." Approvals or reviews older than the latest packet are stale and do **not** justify done.

## Step 2 — Decide and Act

Three approval states drive the decision:

### Approval is `approved`

Run the **Required Review Gates** below first. The approval must be:
- newer than the latest worker packet
- newer than the latest blocking review verdict
- tied to the same target/build/artifact now under review

If any gate is missing, stale, fabricated, undeployed, has `artifact_issues`, or is older than newer task evidence: **reject and route**, do not patch done.

If all gates pass and the approval is fresh: PATCH task to `{"status":"done"}`. If the task is a subtask of a pure-container parent and all sibling subtasks are also done, close the parent.

### Approval is `pending`

Wait. Do not patch done. Do not nudge for re-approval (operator/Miguel acts on approval requests asynchronously).

### No Approval Yet, No Required Review Yet

Route the **first missing reviewer** only, then stop. Architect first when required by packet type; otherwise QA/DevOps validation.

- Architect route payload: `{"assigned_agent_id":"ARCHITECT_ID","status":"review"}`
- QA/DevOps nudges must name: task id, evidence packet type, target/build, required verdict format

If not all required reviewers have posted yet, do not block this tick — continue to the next step and re-check on the next heartbeat.

### Reviewer posted FAIL or INCONCLUSIVE

Treat as blocking. Reject any pending approval.

Follow the reviewer's `Suggested routing` when present. Otherwise classify the first owner:
- code/test bug → PF, PB, or DevOps (the role that owns the file/concern)
- architecture/contract concern → Architect re-review or new task
- infra/deploy/credential failure → DevOps or operator
- flaky test → QA re-run once before assuming bug

Move code-owned failures to **`rework`** (NOT `inbox`):
```json
{"status": "rework", "assigned_agent_id": "DEV_AGENT_UUID"}
```

Use `inbox` only for re-route or decomposition. Failed review stays in `rework`.

Nudge once with the failing dimensions and the required new evidence packet shape. Do not nudge again next tick if the agent owns it.

## Required Review Gates

Run before any approval/done decision:

```bash
curl -fsS "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/review-readiness" \
  -H "X-Agent-Token: $AUTH_TOKEN"
```

Inspect: `ready`, `missing_roles`, `blocking_roles`, `artifact_issues`.

Structured review verdicts are authoritative. Reviewers post both:
1. a human-readable verdict comment, AND
2. a `POST /review-events` with `reviewer_role`, `verdict`, target/build/commit fields, and blocking owner/routing fields when applicable

If a reviewer posted a prose verdict comment but no matching `/review-events`
entry appears in `/review-readiness`, treat that role as missing and route the
reviewer to `structured-review-verdict`. Prose verdicts are for humans only.

Readiness edge cases:

- `review_only` Architect PASS is incomplete unless the structured event
  includes `planned_child_task_ids` for every required child task or
  `no_child_tasks_required:true`. Missing decomposition evidence appears as
  `artifact_issues` and blocks approval/done even if the verdict is PASS.
- Packet type `other` or task configs with `required_roles=[]` are not
  implicit approvals. Follow `/lead/next-action` and readiness reason codes;
  if readiness cannot become true, route to lead/operator to correct
  `review_packet_type` or required roles before creating approval.
- Before nudging for a missing role or failed review, read the latest comments
  and current assignee. If the same nudge was already posted after the latest
  worker packet and that assignee still owns the task, do not post a duplicate
  this heartbeat tick.

Use `/review-readiness` only after the task is in `review`. For implementation evidence before review, use `/pipeline` instead.

### Per-Role Gate Requirements

| Role | When required | Must include |
|---|---|---|
| **Architect (PASS)** | Feature tasks, decomposition tasks, architecture/API/auth/state-machine changes, ≥5 ACs, multi-component work, lead-routed review | Verdict comment + `/review-events`. For `review_only` Architect PASS: structured evidence with `planned_child_task_ids` for every decomposition task, or `no_child_tasks_required:true`. Any `artifact_issues` blocks approval/done |
| **Architect FAIL/INCONCLUSIVE** | Same triggers as above | Blocks done. Lead must reject/route per reviewer's Suggested routing |
| **QA-Unit (PASS)** | Backend/API/contract/persistence/auth and non-UI logic | AC-to-check mapping, source parity, changed-code coverage |
| **QA-E2E (PASS)** | Frontend/UI/browser behavior | Target URL, browser navigation/snapshot, DOM/raw i18n scan, console/network output, click/observe proof, layout proof when applicable, loaded build hash |
| **DevOps validation (PASS)** | Deploy/infra/live-target/build-drift work | Target, source commit, artifact hash/id, deploy command, service/process state, logs, live HTTP/API output, rollback/preflight proof when risky |

### Worker Evidence Packet Required

| Worker role | Packet name |
|---|---|
| PF | frontend browser evidence packet (per `acp-post-review` § Frontend Developer) |
| PB | backend runtime evidence packet (per `acp-post-review` § Backend Developer) |
| DevOps | deploy evidence packet (per `acp-post-review` § DevOps Engineer) |

### Pipeline Gate (frontend_ui / mixed)

Before approval/done for `frontend_ui` or `mixed` tasks:
```bash
$HQCTL pipeline-state $TASK_ID --json --check-ready
```
Require `"ready": true`. Prose/PASS comments do not satisfy this gate.

### Approval API

```bash
curl -fsS -X POST "$BASE_URL/api/v1/boards/$BOARD_ID/approvals" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_type": "move_to_done",
    "task_id": "<TASK_UUID>",
    "confidence": 90,
    "status": "pending",
    "lead_reasoning": "<one-line why done is safe>"
  }'
```

The `status` field must be `"pending"` on creation. State transitions
(`approved`/`rejected`) go through `PATCH /approvals/{id}` by the operator.
Do not create an approval with `status="approved"`.

### Approval Payload Requirements

When the lead creates an approval request (board rule `require_approval_for_done=true`), the payload must name:
- reviewer verdicts and timestamps
- evidence packet refs
- target/build/artifact ids
- blocking findings (or "none")
- residual risk (or "none")
- freshness vs. latest worker/reviewer evidence
- one-line "why done is safe"

## Hard Rejects

Reject the PASS/done path automatically when any of these are true:

- **UI tasks** without **both** QA-E2E browser evidence **and** PF frontend browser evidence packet
- **Backend/API tasks** without **both** PB backend runtime evidence packet **and** QA-Unit AC-to-check validation
- **Deploy/live tasks** without DevOps deploy evidence packet matching the target/build/artifact in the approval

## Anti-Patterns

The lead must not:

- Run their own review or write a verdict comment.
- Move `in_progress` tasks to `review` (worker owns that transition; lead nudges only).
- Approve their own routing decisions ("PASS by Design" — rejected, see AGENTS.md HARD RULES).
- Move status `done` while approval is `pending`.
- Patch `done` from a stale approval (older than the latest worker packet).
- Convert a failing review into `inbox`. Failed review stays in `rework` with the dev owner.

## Approval-on-PASS Branch (Board-Rule-Conditional)

When all required reviewers post PASS and approval is not already `pending`:

- If the board has `require_approval_for_done=true` or `block_status_with_pending_approval=true`:
  Create one approval request with `"lead_reasoning": "Required review gates passed"` and the approval payload fields above. Do not add a board-memory chat nudge; the approval request is the operator-facing queue item.
- Otherwise (no approval rule):
  PATCH directly to `done`.

The template renders the correct branch from `board_rule_*` flags; this skill describes the rule.
