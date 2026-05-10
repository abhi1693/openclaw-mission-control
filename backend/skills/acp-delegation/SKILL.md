---
name: acp-delegation
description: Use when a board agent must delegate coding, review, or validation work through OpenClaw ACP sessions_spawn instead of doing it locally.
---

# ACP Delegation

This skill defines the `sessions_spawn` payload for Claude Code or Codex ACP runs. Transport routing belongs to the current runtime and `TOOLS.md`; if no documented `sessions_spawn` transport is available, stop and report `@lead ACP transport unavailable`.

Use ACP only for bounded child work. The board owner remains responsible for verifying the child output and moving task status.

For Mission Control boards, this skill is the canonical source for ACP spawn
mechanics. `AGENTS.md`, `HEARTBEAT.md`, and `SOUL.md` should only point here
instead of duplicating payload JSON, child-write firewalls, contamination
handling, retry budgets, or chunk strategy. Board lifecycle rules, lead routing,
structured review events, and task status transitions remain in the board
templates/API.

## Hard Rules

Every `sessions_spawn` payload must include:

- `runtime: "acp"`
- explicit `agentId`
- `mode: "run"`
- unique `label`
- `cleanup: "keep"`
- `runTimeoutSeconds: 3600`
- real task description, all acceptance criteria, constraints, repo/workspace context, and current evidence
- explicit PASS/FAIL for each acceptance criterion

Never include fake slash commands, unverified skill names, vague "fix everything" requests, or instructions that conflict with the role's board responsibilities.

Do not ask the child executor to move board status. The child prints evidence only. The parent agent posts the `ACP_EXECUTOR_STARTED` marker after spawn acceptance, verifies the child result, adds its own evidence, and only then performs allowed board routing.

### Ralph Loop Rule

Parallelism is per task, not per acceptance criterion. One ACP executor session
owns one task and must walk that task's acceptance criteria sequentially. Do not
spawn extra ACP children, sub-sessions, or worktrees for individual acceptance
criteria.

For implementation payloads, require this feedback loop inside the same
executor session:

```text
TDD discipline is required for implementation children.
For feature, bugfix, refactor, or behavior-change code: write or update a
failing automated test first, run it, and capture the RED output before
touching production code. Do not implement production code before capturing the
RED result. Then implement the smallest code change, rerun the targeted test and
checks, and include the RED/GREEN output in final evidence. If no automated test
is feasible, state why before coding and provide equivalent runtime/browser
regression proof.

For each acceptance criterion in order:
1. implement the smallest slice for that AC
2. build/check the changed code
3. run the relevant test or runtime/browser/deploy validation
4. fix failures before starting the next AC
5. mark that AC PASS/FAIL with literal evidence

After all ACs have completed their own loop, review the full diff, commit, and
return one final result.
```

This avoids per-AC spawn overhead and worktree merge surfaces while preserving
one complete feedback cycle per AC.

### Worktree Task Mode

Worktree task parallelism is explicit opt-in only. Use it only when the parent
heartbeat or lead instruction says worker worktree mode is enabled for this
board and provides or derives the worktree path. Never invent a `cwd` outside
that gate. A heartbeat-derived `WT_PATH` counts as the supplied worktree path.
If the scheduler created `WT_PATH`, do not omit `cwd` because the lead did not
spell out the path.
This applies to workers with `identity.worker_parallel_mode=worktree` or the
legacy `identity.frontend_parallel_mode=worktree` flag.

When worktree mode is enabled:

- The parent owns `git worktree add`, stale cleanup, merge-back, branch removal,
  and blocker comments.
- The child owns only implementation inside the supplied `cwd`.
- There is one worktree per task, not per acceptance criterion.
- The Ralph Loop Rule still applies inside the executor session.
- Add `"cwd": "$WT_PATH"` to the implementation payload after the scheduler
  defines `WT_PATH="/tmp/mc-${BOARD_SHORT}-wt-$TASK_SHORT"`.
- Do not add `cwd` for review-only payloads unless the parent explicitly says
  the review must inspect that worktree before merge.

## Child Board API Firewall

ACP children must not write to Mission Control. Every implementation or review
payload must include this block verbatim:

```text
Board API boundary:
- Do not POST task comments, PATCH task status, write board memory, send heartbeats, or route this task.
- Do not use guessed endpoints such as /boards/.../tasks/.../comments or payload fields such as body/agent_id.
- Do not use Authorization: Bearer for agent task APIs.
- Return evidence in your final stdout only. The parent agent is the only writer of task comments/status.
- If you must read board context, use only GET endpoints already provided by the parent or documented in TOOLS.md with X-Agent-Token.
```

If a child writes a task comment or changes board state anyway, treat the child
run as contaminated. The parent must verify the repo diff, ignore the child
comment as completion evidence, and run `acp-post-review` before any routing.

## Workflow Selector

Prefer role defaults first. Use `dev_acp_flow` only as an explicit override.

| `IDENTITY.md` role | Default workflow |
|---|---|
| `Frontend Developer` | Claude implements, Codex reviews |
| `Backend Developer` | Codex implements, Claude reviews |
| `DevOps Engineer` | Codex implements, optional Claude review for risky infra/deploy/auth/migration/cross-host work |
| `System Architect and Code Reviewer` | Review-only Claude Code |
| `QA` roles | Do not delegate by default; validate behavior directly |
| `Supervisor` or `Gateway` | Do not delegate by default; route work |
| anything else | Default Claude implementation |

Recognized `dev_acp_flow` overrides:

| `dev_acp_flow` | Use this mode |
|---|---|
| `review_only` | Review-only Claude Code |
| `codex_then_claude_review` | Two-stage Codex implement, then Claude review |
| `claude_then_codex_review` | Two-stage Claude implement, then Codex review |
| `claude_with_skills` | Claude implementation, optionally using confirmed local skills |
| `codex_with_optional_claude_review` | Codex implementation, with Claude review only for risky infra/deploy/auth/migration/cross-host work |

## Complete Payload Patterns

Use these as the minimum shape. Replace placeholders before spawning.

### Implementation

```json
{
  "runtime": "acp",
  "agentId": "claude",
  "mode": "run",
  "label": "mc-task-<TASK_ID>-impl-a1",
  "cleanup": "keep",
  "runTimeoutSeconds": 3600,
  "task": "<task summary>\n\nAcceptance criteria:\n[PASTE ALL ACCEPTANCE CRITERIA]\n\nContext:\n[PASTE RELEVANT EVIDENCE, CONSTRAINTS, REPO PATHS, CONTRACT NOTES]\n\nRole evidence requirements:\n[PASTE THE APPLICABLE ROLE EVIDENCE PACKET FROM THIS SKILL]\n\nImplement only the in-scope changes. Do not move board status. TDD discipline is required for implementation children: for feature, bugfix, refactor, or behavior-change code, write or update a failing automated test first, run it, and capture the RED output before touching production code. Do not implement production code before capturing the RED result. Then implement the smallest code change, rerun the targeted test and checks, and include the RED/GREEN output in final evidence. If no automated test is feasible, state why before coding and provide equivalent runtime/browser regression proof.\n\nWork one acceptance criterion at a time inside this same executor session: implement the smallest slice for AC1, build/check, test or validate with runtime/browser/deploy evidence, fix failures, then mark AC1 PASS/FAIL before starting AC2. Continue this loop for every AC. Do not spawn extra ACP children, sub-sessions, or worktrees for individual ACs. After all ACs pass their own loop, review the full diff, commit, and return.\n\nPrint:\n1. files changed\n2. RED/GREEN TDD output or no-test-feasible reason\n3. test/check results with command output summaries\n4. required runtime/browser/deploy evidence\n5. each acceptance criterion with PASS/FAIL\n6. unresolved risks or blockers"
}
```

For Codex implementation, change only `agentId` to `"codex"` unless the board task explicitly requires a different runtime.

When the parent has explicitly enabled worktree task mode and created the
worktree, add this field to the implementation payload:

```json
{
  "cwd": "$WT_PATH"
}
```

### Review Only

```json
{
  "runtime": "acp",
  "agentId": "claude",
  "mode": "run",
  "label": "mc-task-<TASK_ID>-review-a1",
  "cleanup": "keep",
  "runTimeoutSeconds": 3600,
  "task": "Review task <TASK_ID>.\n\nScope:\n[PASTE TASK SUMMARY, ACCEPTANCE CRITERIA, DIFF/COMMIT/FILES, AND KNOWN EVIDENCE]\n\nThis is review-only. Do not implement fixes. Do not move board status. Give verdict first. Use exactly one verdict: PASS, FAIL, INCONCLUSIVE, or INFRA BLOCKED. Print:\n1. verdict\n2. findings by severity\n3. acceptance-criteria coverage gaps\n4. evidence used\n5. suggested routing, if any"
}
```

### Two Stage

Run two separate spawns:

1. Implementation with label `mc-task-<TASK_ID>-impl-a1`.
2. Review with label `mc-task-<TASK_ID>-review-a1`, after the implementation child finishes and the parent has captured its output/diff.

Do not start stage 2 from stale assumptions. Paste the implementation output, diff/commit/files, and evidence into the review payload.

## Role Evidence Packets

Add the matching packet text to the payload. Evidence must be observed output, not source-code descriptions.

### Frontend Developer

Require:

- dev server or deployed URL target
- browser navigation to the changed page
- browser snapshot after navigation, with the actual snapshot output pasted in the child result
- DOM/raw i18n scan of visible rendered text for namespace/key-shaped literals, proving no raw keys such as `landing.features.items[0].title`, `landing.foo.bar`, or `common.save`
- console and failed-network check
- click/interaction evidence for changed behavior
- responsive/layout check when UI changed
- build hash or artifact proof when deployment/bundle behavior matters

For i18n or locale-file work, the implementation payload must include this
translation rule verbatim:

```text
TRANSLATION RULE: Each locale file must contain content only in its target language.
- en.json -> English
- pt.json -> Portuguese
- es.json -> Spanish
- fr.json -> French
Translate values; do not copy source-language prose into another locale.
Do not declare success until rendered browser output proves each touched locale
shows the target language and no raw i18n keys.
```

Locale verification must use the product's real locale switcher, route, or
documented persisted setting. Do not assume query parameters such as `?lng=`
work. For TaskFlow, use the visible language controls, then capture rendered
text for each locale.

### Backend Developer

Require:

- exact API/CLI/runtime target, chosen from task `validation_target*`, then
  task-declared `BASE_URL`, then an explicitly labeled local runtime
- command output for changed behavior, including status and body where relevant
- readback verification for persistence, state changes, migrations, or API writes
- non-HTTP proof when behavior is worker/queue/DB/file-system based
- regression test output or explicit reason a test could not be run
- original failure evidence for bugfixes when safe, or equivalent regression
  proof with a safe non-repro explanation

Source grep, local tests, generated OpenAPI, and `healthz` are supporting
evidence only. They do not replace runtime target output, status/body, trigger
observation, or readback proof.

### DevOps Engineer

Require:

- task classification before acting: deploy implementation, deploy validation,
  infra drift, credential/operator action, service config, migration, rollback,
  source bug, or external outage
- source host/path, branch, commit SHA, and proof that production source was not
  patched directly
- approved deploy script/command, exit status, target host/env/service, and
  expected artifact/build id
- artifact/build proof: hash, digest, build id, package path, or loaded frontend
  build hash when frontend artifacts are deployed
- service/process state before and after deploy: systemd/container/process
  status, start time, version/env, and relevant log tail
- live HTTP/API/CLI proof against the deployed target with exact command, status,
  and body
- migration/config readback and before/after behavior when deploy changes schema,
  config, auth/session, routing, cache, or service state
- persistence/state failure classification: migration not applied, wrong DB/env,
  stale process, config mismatch, source bug, external outage, or
  credential/operator issue
- rollback command/path or backup/snapshot reference for risky deploy/auth/
  migration/cross-host work

If the selected task is already in `review`, validate deployed state only. Do
not implement, redeploy, or move status unless the lead routes it back to an
implementation state.

### QA Or Architect Review

Require:

- review-only verdict: `PASS`, `FAIL`, `INCONCLUSIVE`, or `INFRA BLOCKED`
- acceptance-criteria-to-evidence mapping
- clear separation between confirmed defects and uncertainty
- no production code edits
- suggested routing only; parent/Supervisor moves status

## Spawn Invariants

### Label Scheme

Every `sessions_spawn` call must use a unique label:

```text
mc-task-<TASK_ID>-<STAGE>-a<N>
```

`<STAGE>` is `impl`, `review`, or `task`. `<N>` starts at `1`. Use `a2` only for an authorized retry. Never reuse labels; terminal sessions reserve their labels forever.

### Accepted Marker

After spawn returns `accepted`, post exactly one task comment:

```text
ACP_EXECUTOR_STARTED child=<childSessionKey> run=<runId> label=mc-task-<TASK_ID>-<STAGE>-a<N>
```

Then wait for the child completion event. Do not poll in a loop.

If spawn is rejected, do not post `ACP_EXECUTOR_STARTED`. Record the rejection payload/error in the task evidence and follow the retry/escalation rules below.

### No Double Spawn

Before spawning, check the latest `ACP_EXECUTOR_STARTED` comment for the same `TASK_ID` and stage:

- If no completion event exists, wait.
- If the prior attempt failed or timed out, run the WS Timeout Idempotency check below before respawning. Only after the idempotency check confirms no child exists may you respawn once with `a2`.
- If two attempts fail, escalate to `@lead`; do not spawn `a3` unless the lead/operator changes a causal condition.

Do not silently switch to local implementation when ACP delegation is the assigned workflow.

### WS Timeout Idempotency

A `sessions_spawn` that returns `gateway timeout after 10000ms` (or any
WS/RPC timeout after the initial accept) does **not** prove the child
failed to start. The gateway may have accepted the spawn and created a
live child session, but the WS reply was lost in transit. Retrying with a
fresh label in that state creates a duplicate child running the same work
— wasted compute, divergent diffs, and confused parent state.

Before retrying after any WS/RPC timeout, run the idempotency check:

1. Wait 5 seconds (the gateway may still be flushing the spawn reply).
2. List recent child sessions:

   ```bash
   openclaw sessions --agent "$CHILD_AGENT_ID" --active 5 --json
   ```

   `$CHILD_AGENT_ID` is the spawn's `agentId` value (e.g. `claude` or
   `codex`).
3. Look for an entry whose label matches the spawn's label exactly, or
   whose label prefix matches `mc-task-<TASK_ID>-<STAGE>-a<N>` for the
   attempt that timed out.
4. If a matching session exists, the spawn worked despite the lost reply.
   Do **not** retry. Post the standard `ACP_EXECUTOR_STARTED` marker with
   that session's key/runId and continue waiting for the completion
   event.
5. If no matching session exists after the wait + list, the spawn truly
   failed. Proceed to the retry rule under `No Double Spawn`.

Classify the timeout type before deciding the retry shape:

- **Transport failure** (WS handshake never completed, `ECONNREFUSED`,
  TLS error, gateway port not reachable): safe to retry once after a
  30-second backoff with the **same** label — the gateway never
  acknowledged, so reusing the label is idempotent. Skip the sessions
  check; there is nothing to find.
- **Accepted-but-silent** (WS handshake OK, no spawn reply within the
  10-second timeout): always run the sessions check above first. Never
  retry with a fresh label until the check confirms no child exists.
- **Resource-pressure** (gateway returns 503/429, `capacity exceeded`,
  or DevOps confirms WS overload): do **not** retry. Post one task
  comment `@DevOps ACP_INFRA_BLOCKER: <exact error envelope>` and stop.
  Retry only after DevOps signals recovery via a board comment naming
  this task.

One classification per timeout, one action per classification. Do not
flap between retry and park within the same tick.

## Large File Strategy

If a target file is over 500 lines or the task requires over 50 edits, split the work:

- Write a chunk plan before the first spawn: chunk labels, owned line ranges/files, expected edits, shared files, and final merge owner.
- Prefer fewer larger chunks over many small chunks. Default maximum is four implementation chunks for one task; a fifth chunk requires `@lead` approval or a parent-owned scope split.
- Give each chunk a disjoint write set. If chunks share locale/config files, children must write temp delta files or clearly delimited sections; the parent performs one final merge.
- Each chunk must end with `CHUNK_DONE` or `CHUNK_BLOCKED` in final stdout, plus changed files and checks. Chunk comments are forbidden; only the parent posts task comments.
- After each chunk, the parent verifies non-empty diff, expected edit count, and relevant checks. A chunk that reports success with zero relevant diff is a failed attempt.
- After all chunks, stop spawning implementation children. The parent must run a final integration pass and `acp-post-review`; do not keep launching "one more section" executors.
- For implementation roles only, run one final review executor after parent integration evidence exists. Review children are review-only.

### Retry Budget

Retries are per task, not just per label. After two failed implementation
attempts, switch to a written chunk plan. After two failed chunks or any timeout
after chunking starts, stop and post `@lead ACP chunk plan blocked: <cause>`.
Do not create `retry3`, `retry4`, or unbounded section labels without a changed
causal condition approved by the lead/operator.
