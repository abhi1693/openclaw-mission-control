---
name: rework-resubmit
description: Use when an OpenClaw board implementation task has been returned to rework after QA, Architect, Lead, or Supervisor rejection.
---

# Rework Resubmit

Use this only for implementation-owner rework. QA, Architect, Supervisor, and Gateway do not use this as an implementation path.

The goal is to fix the confirmed rejection scope, prove the fix with runtime evidence, and route only when the board role permits it.

## Boundaries

- Read every rejection before editing.
- Fix confirmed defects and missing-evidence gaps from the rejection; do not expand scope.
- Do not resubmit unchanged code.
- Do not perform production deploy, `scp`, or `systemctl restart` unless your task explicitly assigns deployment ownership to your role.
- Do not force a board transition if the role template or Supervisor requires review routing.
- Do not hardcode reviewer IDs; use the board-visible reviewer/lead routing rules.

## Step 1: Diagnose First

Before fixing, post or prepare a DIAGNOSIS entry:

```text
DIAGNOSIS for <TASK_ID> rejection:
Reviewer/verdict: <QA|Architect|Lead|Supervisor> <PASS|FAIL|INCONCLUSIVE|INFRA BLOCKED>
Reviewer said: "<verbatim rejection or blocker>"
Rejected acceptance criteria: <AC ids/text>
Root cause found: <file:line or runtime cause>
All reviewer findings: <list EVERY finding from the original FAIL, not just the latest routing mention>
Fix plan: <bounded changes>

**IMPORTANT:** Re-read the FULL original reviewer FAIL verdict. Your fix must address ALL findings listed there, not just the ones mentioned in the latest Supervisor routing. Check every flagged key before resubmitting.
Evidence required before resubmit: <role packet below>
```

If multiple reviewers rejected the task, address each rejection separately. If the rejection is unclear or contradictory, ask `@lead` for routing instead of guessing.

## Step 2: Fix The Rejection Scope

- Make the smallest code/config/doc change that resolves the confirmed rejection.
- Keep unrelated refactors out.
- Verify the diff is non-empty against the rejected revision.
- If no code change is required because the rejection was missing evidence, explicitly label the resubmission as evidence-only and provide the missing observed output.
- If three consecutive rejections occurred on the same task, stop and escalate to `@lead` or the configured operator before another submission.

## Step 3: Verify With Role Evidence

Evidence must be observed output, not source-code descriptions.

### Frontend Developer

Required:

- target URL and viewport
- browser navigation proof to the affected page
- browser snapshot output pasted verbatim
- visible DOM text scan proving no raw namespace/key-shaped i18n literals such as `landing.features.items[0].title`, `landing.foo.bar`, or `common.save`
- console error check
- failed-network check
- click/observe evidence for functional or interactive ACs
- responsive/layout check when UI changed
- build hash or served asset proof when deployment/bundle behavior matters

### Backend Developer

Required:

- exact API, CLI, worker, queue, DB, or runtime target
- command output for changed behavior, including status and body where relevant
- readback verification for persistence, state changes, migrations, or API writes
- non-HTTP proof for worker, queue, DB-only, file-system, or scheduled behavior
- migration/schema evidence when a migration ran
- regression test output, or an explicit blocker explaining why it could not run
- deploy parity evidence only when Backend is explicitly assigned deployment ownership; otherwise hand off to DevOps

### DevOps Engineer

Required:

- source revision and artifact/build proof
- service/process state before and after deploy
- live HTTP/API/CLI proof against the deployed target
- logs for the changed service window
- rollback or preflight notes for risky changes
- frontend build hash when frontend artifacts are deployed
- explicit production target/host/service names

## Step 4: Resubmit Safely

Before routing:

1. Confirm every rejected AC now has evidence.
2. Confirm the diff is non-empty unless this is explicitly evidence-only rework.
3. Run the relevant local checks plus required runtime/browser/deploy checks.
4. Include the DIAGNOSIS, changed files, verification commands, observed outputs, and remaining risks in the task comment.

Use the status transition allowed by your current board template. If the template requires `rework -> in_progress -> review`, perform both transitions only after the evidence packet is ready. If Supervisor or Lead owns routing, post the evidence and request routing instead of moving status yourself.

Do not use `git add -A` blindly. Stage only files intentionally changed for the rework. Commit only if the task workflow requires a commit. When moving to review after rework, include `"packet_commit_sha":"<SHA>"` in the task PATCH; the backend rejects missing or unchanged commit SHA.

PATCH to `review` first — the backend auto-wakes the Supervisor on
`rework → review` transitions via `deliver=True`. Then post the evidence
comment with `@lead` as defense-in-depth. Do not use board memory chat
for this handoff.

Task-comment mentions wake the named board agent. Use a task comment for this
handoff, not board memory, so the Supervisor receives the immediate nudge tied
to the task being resubmitted.

Do not hardcode hosts, tokens, reviewer ids, or bearer auth for agent
task APIs.

## ACP Interaction

If rework was performed through ACP:

- use `acp-delegation` for any follow-up child spawn
- use `acp-post-review` after the child completion event
- do not re-spawn without a fresh label and complete payload
- do not accept child-reported success without parent-side verification
- do not let ACP children post task comments or move board status
- treat section/chunk "Done" notes as partial evidence only
- stop after the planned chunks finish; do not keep spawning new section workers
  unless `@lead` approves a changed chunk plan

## Rework Stop Condition

For every rejection, define the active blocker before editing:

```text
Active blocker: <one-line blocker from reviewer>
Original failing evidence: <quote or command/browser output>
Expected clearing evidence: <exact browser/runtime proof required>
```

After the fix, re-run the same failure probe or a stricter equivalent. For
cross-locale/i18n rework, parity and raw-key checks are not enough: include a
rendered browser text scan that checks the wrong-language phrases called out by
the reviewer.

Resubmission is allowed only when there is one parent-owned packet beginning:

```text
Active blocker cleared: <same blocker>
```

The packet must include the new commit/build, the original failing probe, the
new passing probe, and any required browser/runtime evidence. Do not resubmit
from isolated ACP child comments, per-section build results, or unchanged code.

## Verdict Handling

- `PASS`: all rejected ACs have observed evidence and required review passed.
- `FAIL`: confirmed defect remains, evidence is still missing after allowed retry, or the fix is out of scope.
- `INCONCLUSIVE`: evidence is insufficient but the defect is not confirmed.
- `INFRA BLOCKED`: required environment/tool/runtime is unavailable.

Never convert missing evidence into PASS, and never resubmit the same artifact as though it were fixed.

## i18n Locale Verification (Rework-Specific)

**Mandatory when the rejection involves wrong-language content in locale files.**

Before resubmitting after i18n rework:

1. Switch the validation target to **each locale** (EN, PT, ES, FR) and verify:
   - Content renders in the **correct target language** (not source language)
   - No raw translation keys visible as text
   - No English leaks into non-English locales (unless intentional brand names)

2. For each ACP executor prompt during i18n rework, include:
   ```
   TRANSLATION RULE: Each locale file must contain content ONLY in its target language.
   - en.json → English | pt.json → Portuguese | es.json → Spanish | fr.json → French
   Current problem: some values are in the wrong language. Translate, do not copy.
   ```

3. After each executor completes, sample 3+ keys from each affected locale file to confirm correct language before declaring the section fixed.

4. Do NOT resubmit until ALL sections across ALL locales render the correct language. Partial fixes → another QA FAIL.

## Build & Deploy Gate (Rework-Specific)

**After fixing code during rework, the live target will NOT update automatically.**

Before checking live evidence or posting a rework-complete packet:

1. **Build**: run `npm run build` (or equivalent) in your workspace. Confirm the output artifact filename changed from the rejected build.
2. **Deploy**: If deployment is handled by another role (e.g., DevOps), you MUST nudge that agent to deploy your fresh build. Include:
   - Workspace path to `dist/`
   - New artifact filename
   - Commit SHA
   - Deploy target (e.g., `.63:3002 via taskflow-web.service`)
3. **Wait for deploy confirmation**: Do NOT check live evidence until DevOps confirms the new artifact is served.
4. **Verify**: After deploy confirmation, check the live target serves the NEW artifact filename (not the old one).

For `frontend_ui` or `mixed` rework, also update structured pipeline state
before resubmitting. In the agent/gateway runtime set
`HQCTL=${HQCTL:-"python3 /root/.openclaw/workspace/hqctl.py"}`. If unavailable,
stop and report `@lead HQCTL unavailable on this runtime`.

Use the canonical command list in `acp-post-review` section
`Structured Pipeline Evidence`. Do not copy or invent a variant. The server
validates required fields at event creation; at minimum this includes commit
for code/build/deploy states, artifact hash for build/deploy states, deploy
target for deploy/live/runtime states, and runtime evidence for
`runtime_verified`.

If another role owns build/deploy, nudge DevOps and wait for `built` and
`deployed` events before resubmitting. Then run
`$HQCTL pipeline-state <TASK_ID> --check-ready`.
If it exits nonzero or prints `PIPELINE_READY=false`, do not resubmit.

**Common rework trap**: seeing the old failure on the live site and spawning more code fixers. If your git HEAD has all fixes but the live site shows old content, the problem is deployment — not code. Build and deploy, do not spawn more executors.
