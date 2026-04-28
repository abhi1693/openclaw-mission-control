---
name: qa-validation-verdict
description: Use when a QA board agent must validate a task in review status and post a PASS, FAIL, INCONCLUSIVE, or INFRA BLOCKED verdict.
---

# QA Validation Verdict

Use this only as QA-Unit or QA-E2E on tasks in `review`. QA validates and posts
verdicts; QA does not implement, deploy, delegate implementation, or move
failed tasks to `rework`.

## Universal Gates

- Fetch the task and verify status is `review`. If not, post
  `@lead task not in review` and stop.
- List every acceptance criterion. Missing validation for any criterion blocks
  PASS.
- Validate against declared `review_packet_type` and `validation_target*`; do
  not invent a new target or evidence packet.
- For any persistence/state AC, perform a write/change and then read back the
  resource. Missing readback is FAIL.
- For FAIL, post `Suggested routing: lead move to rework for
  <owner/reason>`. For INCONCLUSIVE or infra/tool/target failures, post
  `Suggested routing: lead route DevOps/operator`.

## QA-E2E PASS Evidence

PASS for UI/frontend behavior requires literal browser evidence:

- exact target URL
- browser navigation and snapshot output for every route/state under test
- DOM text dump and raw i18n-key scan
- console error and failed-network output
- exact action plus before/after observation for every interactive AC
- responsive/layout evidence when applicable
- browser-observed UI state plus API/readback proof for API-backed UI
- loaded build hash or artifact id

If target/browser tooling is unreachable, verdict is `INFRA BLOCKED` or
`INCONCLUSIVE`, not PASS.

For `frontend_ui` or `mixed` PASS, after posting browser evidence record
runtime pipeline evidence:

```bash
$HQCTL pipeline-event $TASK_ID runtime_verified --deploy-target URL --evidence qa_browser_snapshot=posted --evidence qa_dom_scan=posted --source $AGENT_NAME
```

## QA-Unit PASS Evidence

PASS for non-UI logic requires:

- submitted commit, diff, or files under review
- source parity with the submitted evidence
- AC-to-check mapping
- at least one check that exercises changed code
- backend runtime evidence packet when backend/API/persistence behavior is under
  review
- negative/regression checks for invalid input, auth denial, boundary cases, or
  original bug reproduction when relevant

Local source inspection, broad unrelated green tests, OpenAPI presence, and
`healthz` are supporting evidence only.

## Comment Format

Post one task comment:

```text
VERDICT: PASS/FAIL/INCONCLUSIVE/INFRA BLOCKED
$AGENT_NAME validation for $TASK_ID
Target: <url/command/contract target>
Build/source: <loaded build hash/artifact id, submitted commit, or source parity evidence>
| # | AC | Result | Category | Evidence |
|---|-----|--------|----------|----------|
| 1 | <criterion> | PASS/FAIL | unit/contract/api/auth/persist/regression/edge/infra | <literal command/API/readback/browser output> |
Verdict basis: PASS means all AC rows PASS; FAIL means any code/AC FAIL; INCONCLUSIVE means missing evidence/source drift; INFRA BLOCKED means target/tool unavailable.
Suggested routing: lead keep in review / lead move to rework for <owner/reason> / lead route DevOps/operator
Infra issues (not code bugs): <list or "none">
Lead wake: structured-review-verdict review event
```

Then use `structured-review-verdict` to record the matching structured event.
The review-events API wakes the lead after the structured event is stored; do
not send a separate board-memory chat or task-comment nudge for this handoff.

For a challenged or rejected QA verdict, use `reviewer-recheck`.
