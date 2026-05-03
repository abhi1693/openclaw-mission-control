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
  @Supervisor <one-line routing intent — see "Required @ citation" below>
  Lead wake: structured-review-verdict review event
```

Map `INFRA BLOCKED` to `infra_blocked` when posting the structured event.

## Architect Recheck Format

```text
ARCHITECT RECHECK for $TASK_ID:
  Challenge/rejection quoted: "<paste issue word-for-word>"
  Previous verdict: PASS/FAIL/INCONCLUSIVE on <packet/build>
  New evidence reviewed: <commit/build/evidence packet or "none">
  Diff from previous: <one-line summary, e.g. "AC3 lighthouserc threshold
                       fixed; AC1 still missing webp coverage" or
                       "scope unchanged, evidence updated">
  Corrected verdict: PASS/FAIL/INCONCLUSIVE
  Blocking findings: <list or "none">
  Evidence gaps: <list or "none">
  @Supervisor <one-line routing intent — see "Required @ citation" below>
  Lead wake: structured-review-verdict review event
```

The `Diff from previous` line replaces the fragility of a per-AC delta
column — Architect findings often regress on one dimension and improve
on another, which a single classification can't capture. A one-line
narrative summary lets the lead/operator scan the change without
parsing a column of mostly `unchanged` entries.

If the corrected verdict changes required roles, blocking owner, or routing,
include those fields in the structured review event.

## Required @ citation

Every recheck comment (QA or Architect) MUST end with `@Supervisor` plus
a one-line routing intent BEFORE the `Lead wake:` line. The structured
`/review-events` API auto-wakes the lead for routing logic, but the prose
comment is what the operator sees in the dashboard, agent text dumps, and
scrollback. Without an explicit `@Supervisor` citation, the wake is
invisible to the human-facing channel.

**Routing-intent shapes** (same as the original verdict skills):

- Corrected PASS, all required reviewer roles now passing →
  `@Supervisor lead approve and move to done`
- Corrected PASS, more reviewers still need to run →
  `@Supervisor @<NextReviewer> next gate is <role>`
- Corrected FAIL →
  `@Supervisor lead move to rework for <owner> (<one-line reason>)`
- INCONCLUSIVE / packet-missing →
  `@Supervisor lead route DevOps/operator (<reason>)`
