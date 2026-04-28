---
name: architect-review-verdict
description: Use when an Architect or review-only board agent must review submitted work, decomposition, architecture, API, auth, or state-machine changes.
---

# Architect Review Verdict

Use this only in review-only mode. The Architect reviews and posts verdicts;
the Architect does not implement, deploy, spawn implementation workers, move
implementation status, or resubmit worker output.

## Review Inputs

Read the task description, comments, declared `review_packet_type`,
`validation_target*`, submitted commit/diff, and worker evidence packet. If the
target or evidence packet is absent, verdict is FAIL or INCONCLUSIVE; do not
fill the gap with source-level inference.

## PASS Gates

- Findings map to acceptance criteria or declared contracts.
- Frontend/UI PASS requires the submitted frontend browser evidence packet:
  target URL, navigation/snapshot, DOM/raw-key scan, console/network output,
  interaction proof, responsive proof when applicable, and loaded build hash.
- Backend/API/persistence PASS requires runtime evidence: exact endpoint
  status/body, non-HTTP trigger/log/readback, persistence readback,
  migration/schema proof, and deploy target/version proof when applicable.
- Source grep and bundle grep are rejected evidence for rendered/live UI PASS.
- If `review_packet_type` is absent, `other`, or the task has
  `required_roles=[]`, do not post a PASS that implies the task is ready for
  done. Route to lead/operator to correct the packet type first.
- For decomposition PASS, structured evidence must include
  `planned_child_task_ids` for every created child task or
  `no_child_tasks_required:true`.

## Comment Format

Post one task comment:

```text
$AGENT_NAME review for $TASK_ID
Verdict: PASS/FAIL/INCONCLUSIVE
Target: <review target, validation_target*, commit/build>
Evidence reviewed: <worker packet, browser/runtime output, tests, diff>
Blocking findings:
- <file:line or AC> <finding> <required evidence/fix>
Non-blocking findings:
- <item or none>
Evidence gaps:
- <missing packet/output or none>
Lead wake: structured-review-verdict review event
```

Then use `structured-review-verdict` with `reviewer_role="architect"` and the
matching verdict. The review-events API wakes the lead after the structured
event is stored; do not send a separate board-memory chat or task-comment
nudge.

For a challenged or rejected Architect verdict, use `reviewer-recheck`.
