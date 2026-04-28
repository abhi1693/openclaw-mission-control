---
name: reviewer-recheck
description: Use when a QA, Architect, or review-only verdict has been challenged, rejected, or returned for correction on the same task.
---

# Reviewer Recheck

Use this only for validation/review roles correcting or defending a prior
verdict. Do not implement, deploy, move implementation status, or resubmit
worker output.

## Rules

- Quote the challenge or rejection verbatim.
- Compare commits, build, target, and evidence since the previous verdict.
- Re-test the disputed acceptance criteria from a clean state.
- If no new commit/evidence exists after a code-related FAIL, keep FAIL:
  `no code changed since previous QA` or
  `no code/evidence changed since previous review`.
- Re-citing a previous PASS is forbidden.
- After the corrected comment, use `structured-review-verdict`. The API wakes
  the lead after storing the structured event; do not add a separate nudge.

## QA Recheck Format

```text
QA RECHECK for $TASK_ID:
  Challenge/rejection quoted: "<paste issue word-for-word>"
  Target/build tested: <url + build hash/artifact id or n/a>
  Re-test evidence: <literal browser/command output>
  Corrected verdict: PASS/FAIL/INCONCLUSIVE/INFRA BLOCKED
  Lead wake: structured-review-verdict review event
```

Map `INFRA BLOCKED` to `infra_blocked` when posting the structured event.

## Architect Recheck Format

```text
ARCHITECT RECHECK for $TASK_ID:
  Challenge/rejection quoted: "<paste issue word-for-word>"
  Previous verdict: PASS/FAIL/INCONCLUSIVE
  New evidence reviewed: <commit/build/evidence packet or "none">
  Corrected verdict: PASS/FAIL/INCONCLUSIVE
  Blocking findings: <list or "none">
  Evidence gaps: <list or "none">
  Lead wake: structured-review-verdict review event
```

If the corrected verdict changes required roles, blocking owner, or routing,
include those fields in the structured review event.
