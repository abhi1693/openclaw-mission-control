---
name: structured-review-verdict
description: Use when a board reviewer has posted a review verdict comment and the verdict must become visible to Mission Control review-readiness gates.
---

# Structured Review Verdict

After posting your review verdict **comment**, you MUST record a structured
review event so the Supervisor's review-readiness gate can read your verdict
programmatically. Without this call, your verdict is invisible to the pipeline
and the task will stall in review.

## When to Use

Every time you post a verdict comment (PASS, FAIL, INCONCLUSIVE, INFRA_BLOCKED)
on any task in `review` status.

## API Call

```bash
curl -fsS -X POST \
  "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/review-events" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(cat <<JSON
{
  "reviewer_role": "<YOUR_ROLE>",
  "verdict": "<lowercase_verdict>",
  "evidence_type": "<TYPE_OR_NULL>",
  "target": "<VALIDATION_TARGET_OR_NULL>",
  "build_hash": "<BUILD_HASH_OR_NULL>",
  "source_commit": "<COMMIT_SHA_OR_NULL>",
  "evidence": {"comment": "<ONE_LINE_SUMMARY>"}
}
JSON
)"
```

## Field Reference

| Field | Required | Values |
|-------|----------|--------|
| `reviewer_role` | yes | Your board role: `architect`, `qa_e2e`, `qa_unit`, `devops`, or `lead` |
| `verdict` | yes | `pass`, `fail`, `inconclusive`, or `infra_blocked` |
| `evidence_type` | no | `browser`, `unit_contract`, `deploy`, `runtime`, `source_review`, or null |
| `target` | no | The validation URL, command, or environment you tested against |
| `build_hash` | no | Loaded build hash, artifact digest, or asset filename |
| `source_commit` | no | Commit SHA of the reviewed work |
| `blocking_owner` | no | For FAIL/INCONCLUSIVE: who must fix it (e.g. `PF`, `PB`, `DevOps`) |
| `suggested_routing` | no | Routing hint for Supervisor (e.g. `lead move to rework for PF`) |
| `evidence` | no | JSON object with structured evidence details |

## Role Mapping

Use the `reviewer_role` that matches your board identity:

The JSON `verdict` value must be lowercase. Map human comment verdicts as
`PASS` -> `pass`, `FAIL` -> `fail`, `INCONCLUSIVE` -> `inconclusive`, and
`INFRA BLOCKED` or `INFRA_BLOCKED` -> `infra_blocked`.

| Agent Role | reviewer_role | evidence_type |
|------------|--------------|---------------|
| Architect | `architect` | `source_review` |
| QA-E2E | `qa_e2e` | `browser` |
| QA-Unit | `qa_unit` | `unit_contract` |
| DevOps Engineer | `devops` | `deploy` |
| Supervisor/Lead | `lead` | null |

## Examples

### DevOps PASS (infra_ops task)

```bash
curl -fsS -X POST \
  "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/review-events" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_role": "devops",
    "verdict": "pass",
    "evidence_type": "deploy",
    "target": "<VALIDATION_TARGET>",
    "build_hash": "<BUILD_HASH>",
    "source_commit": "1bfbfdf0",
    "evidence": {"comment": "All ACs verified: artifact deployed, live hash matches, service healthy post-deploy"}
  }'
```

### QA-E2E PASS (frontend_ui task)

```bash
curl -fsS -X POST \
  "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/review-events" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_role": "qa_e2e",
    "verdict": "pass",
    "evidence_type": "browser",
    "target": "<VALIDATION_TARGET>",
    "build_hash": "<BUILD_HASH>",
    "evidence": {"comment": "All ACs verified via Playwright at 375/768/1440 viewports"}
  }'
```

### Architect FAIL with routing

```bash
curl -fsS -X POST \
  "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/review-events" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_role": "architect",
    "verdict": "fail",
    "evidence_type": "source_review",
    "source_commit": "abc1234",
    "blocking_owner": "PF",
    "suggested_routing": "lead move to rework for PF",
    "evidence": {"comment": "AC2 missing responsive behavior at 375px breakpoint"}
  }'
```

## After Posting the Review Event

Backend contract: the `/review-events` API commits and refreshes the structured
event, then auto-wakes the lead with `deliver=True`. This avoids the stale
sequence where an `@lead` verdict comment wakes the lead before the structured
gate data exists.

Do NOT use board memory with `tags=["chat"]` for nudging, and do NOT add a
second task-comment nudge just for the structured event. If the API call fails,
post the exact failure as a task comment with `@lead` and stop. If the API call
succeeds but the lead does not wake, report a backend wake failure with the
exact response/status instead of inventing another nudge path.

Do not repost an identical PASS for the same evidence. For a recheck or
correction, post a new verdict event only when the reviewed evidence, commit,
target, or finding changed.

## Checklist

1. Post your verdict **comment** on the task (the human-readable table)
2. POST `/review-events` with the structured payload (this skill)
3. Confirm the API response; it auto-wakes the lead after the event is committed
4. Do NOT move the task status yourself — Supervisor handles routing
