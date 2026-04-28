---
name: devops-deploy-validation
description: Use when a DevOps board agent must validate deployed state, classify infra/deploy drift, or diagnose a DevOps-owned review or rework failure.
---

# DevOps Deploy Validation

Use this as DevOps for deploy/live-target validation, infra drift, service
state, migration/config readback, and DevOps-owned rework diagnosis.

## Boundaries

- Deploy target comes from the task description, `validation_target*`, explicit
  environment fields, service inventory, or lead/operator instruction. Do not
  guess paths, hosts, or environments.
- Work only through approved source host/path and deploy scripts. Never edit
  production source directly.
- If task status is `review`, validate deployed state only and post a verdict
  or suggested routing. Do not redeploy or move status unless the lead routes
  rework.
- For implementation/rework, use `acp-delegation` for the concrete deploy/infra
  action and `acp-post-review` for the required DevOps deploy evidence packet.

## Validation Evidence

Classify first:

- deploy implementation
- deploy validation
- infra drift
- credential/operator action
- service config
- migration
- rollback
- source bug
- external outage

Required validation evidence includes source revision, artifact/build proof,
target host/env/service, approved deploy command when deployment occurred,
service/process state, logs for the changed window, live HTTP/API/CLI proof,
rollback or preflight notes for risky work, and frontend build hash when
frontend artifacts are deployed.

For deploys that change data, config, status, cache, migration, routing,
auth/session, or service state, verify write/change plus readback/live behavior.
If it fails, classify the first cause before routing: migration not applied,
wrong DB/env, stale process, config mismatch, source bug, external outage, or
credential/operator issue.

## Review Verdict

When validating a task already in `review`, post PASS/FAIL/INCONCLUSIVE/INFRA BLOCKED with:

- target/build/artifact checked
- live command output and status/body
- service/process state
- source/artifact parity or drift
- suggested routing for any failure

Do not treat local build success as deploy validation.

Then use `structured-review-verdict` with `reviewer_role="devops"` and the
matching verdict. The review-events API wakes the lead after the structured
event is stored; do not send a separate board-memory chat or task-comment
nudge.

## Rejection Diagnosis

Before changing anything after a DevOps-owned rejection, post:

```text
DEVOPS DIAGNOSIS for $TASK_ID rejection:
  Reviewer said (verbatim quote): "<paste rejection reason word-for-word>"
  Classification: infra drift / deploy failure / config mismatch / migration not applied / wrong target-env / source bug / external outage / credential-operator action
  Evidence: <command/output proving classification>
  Fix or routing: <deploy/config/rollback action taken, or "lead route to PB/PF/operator because ...">
  Re-test evidence: <literal deploy/live command output proving the original failure no longer reproduces, or blocking target/error>
```

Only fix deploy/infra-owned failures. If classification is source bug or
missing product behavior, do not patch production or resubmit as DevOps PASS;
post routing evidence for the lead.

After posting a rework diagnosis with a corrected verdict, use
`structured-review-verdict` with `reviewer_role="devops"` so the
review-readiness gate reflects the updated verdict.
