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

## AC Quoting Rule (verbatim, no paraphrase)

The AC text in your verdict's evidence table must be **copied verbatim** from
the task description's `Acceptance criteria:` section. Do not summarize,
reword, simplify, or describe what the live state shows in place of the AC
text — that lets a deviation pass review by quietly matching what was
implemented instead of what was specified.

If the spec AC says `Preserve/verify dashboard wrapper perspective tilt from
VP-13: rotateY(-14deg), transform-origin: left center`, your AC column quotes
exactly that. If the live state has `rotateY(+14deg)` at `right center`, your
evidence column reports the live value and your verdict is FAIL — not a
reworded AC like "right edge near / left edge recedes" that turns a deviation
into a description.

When the spec AC names specific values (transforms, classNames, breakpoint
prefixes, pixel measurements), the evidence column must show both the spec
value and the measured value. Differences are FAIL unless the spec explicitly
allows variation (`or measured equivalent`, `or above`, `at least`).

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
Infra issues (not code bugs): <list or "none">
@Supervisor <one-line routing intent — see "Required @ citation" below>
Lead wake: structured-review-verdict review event
```

## Required @ citation

Every verdict comment MUST end with `@Supervisor` plus a one-line routing
intent BEFORE the `Lead wake:` line. The structured `/review-events` API
auto-wakes the lead for routing logic, but the prose comment is what the
operator sees in the dashboard, agent text dumps, and scrollback. Without
an explicit `@Supervisor` citation, the wake is invisible to the human-
facing channel.

**Routing-intent shapes:**

- PASS, all required reviewer roles passed →
  `@Supervisor lead approve and move to done`
- PASS, more reviewers still need to run →
  `@Supervisor @<NextReviewer> next gate is <role>`
- FAIL → `@Supervisor lead move to rework for <owner> (<one-line reason>)`
- INCONCLUSIVE / packet-missing →
  `@Supervisor lead route DevOps/operator (<reason>)`
- INFRA BLOCKED → `@Supervisor lead route DevOps (infra: <tool/target>)`

The lead is the universal router; QA does not PATCH status itself. If a
next reviewer is named (e.g., `@Architect`), it's a hint for the lead —
the lead's `lead-review-routing` skill makes the actual assignment.

Then use `structured-review-verdict` to record the matching structured event.
The review-events API wakes the lead after the structured event is stored; do
not send a separate board-memory chat or task-comment nudge for this handoff.

For a challenged or rejected QA verdict, use `reviewer-recheck`.
