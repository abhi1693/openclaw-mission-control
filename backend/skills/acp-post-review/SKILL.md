---
name: acp-post-review
description: Use when an OpenClaw board agent has received an ACP child completion event and must verify the child result before posting evidence or routing the task.
---

# ACP Post Review

Use this only after an ACP child returns a completion event. It is the parent/orchestrator check, not a replacement for `acp-delegation`.

Do not post completion evidence or move task status until this skill's gates pass.

For Mission Control boards, this skill is the canonical parent-side review gate
after ACP child completion. `AGENTS.md` should point here rather than duplicate
contamination handling, evidence packet shape, re-spawn rules, or final routing
checks.

## Scope Boundaries

- Implementation owners may verify child output and route according to their board role.
- QA, Architect, Supervisor, and Gateway do not use this as an implementation path.
- Review-only roles must not re-spawn implementers unless their template explicitly authorizes it.
- The child output is evidence to inspect, not proof to trust.

## Universal Gates

Before posting evidence or moving to review:

1. Confirm the child actually completed and capture its output, changed files, diff/commit, and test/check results.
2. Map every acceptance criterion to observed evidence.
3. Verify the relevant role evidence packet below using fresh parent-side checks when possible.
4. For feature, bugfix, refactor, or behavior-change work, parent evidence must include RED/GREEN TDD proof from the child or parent: failing automated test output before production-code changes, then passing output after the smallest implementation. Missing RED output blocks review unless the packet gives a specific no-test-feasible reason plus equivalent runtime/browser regression proof captured before routing.
5. Check that the child did not move board status or omit required evidence.
6. If a stage-2 review is required by role flow, spawn it with the full `acp-delegation` payload shape.
7. Route only after parent verification and required review return PASS.

If evidence is missing, do not describe the child run as successful. Re-spawn only when allowed, with a fresh label and complete payload per `acp-delegation`.

## Child Write Contamination Gate

Check whether the child wrote Mission Control state:

- task comments
- task status
- board memory/chat
- heartbeat/routing side effects

Children are not allowed to write board state. If a child did so, the parent
must not treat that write as a valid completion packet. Verify the repo/runtime
state directly, then post one parent-owned packet if the work is valid. If the
child used stale API forms (`/boards/.../comments`, `{body, agent_id}`,
`Authorization: Bearer` for agent APIs), record it as ACP process failure and
continue only from parent-verified source/runtime evidence.

Correct parent comment API, when posting is allowed by the board role.
The backend auto-wakes the Supervisor when a task PATCHes to `review`
(via `_notify_lead_on_end_work_event`). Parent-owned ACP handoff comments
must include `@lead`; the task-comment mention wakes the Supervisor immediately
and is defense-in-depth after the PATCH `review` wake. This applies
only for parent-owned ACP handoffs and blockers. QA/Architect/DevOps review verdict
handoffs use `structured-review-verdict`; reviewers post the structured event
instead of using this ACP handoff path.

**Preferred:** use the typed `mc-board-api` skill — `mc_comment_create`
(MCP tool, inside ACP children with the MC MCP server wired) or
`mc_client.py comment-create` (CLI on the gateway host). Both wrap
this endpoint with auth, board enforcement, and JSON encoding. Don't
hand-roll curl unless `mc-board-api` is unavailable.

```bash
# Preferred (CLI fallback when MCP tools aren't available)
mc_client.py comment-create --task "$TASK_ID" --message "TEXT @lead"
```

Raw HTTP fallback (e.g., debugging from a host without `mc_client.py`):

```bash
curl -fsS -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "TEXT @lead"}'
```

## Re-spawn Contract

Every follow-up `sessions_spawn` must comply with `acp-delegation`:

- include `runtime: "acp"`, `agentId`, `mode: "run"`, unique `label`, `cleanup: "keep"`, and `runTimeoutSeconds: 3600`
- include task summary, all acceptance criteria, current evidence, missing evidence, and role evidence packet
- use labels like `mc-task-<TASK_ID>-impl-a2` or `mc-task-<TASK_ID>-review-a1`
- post `ACP_EXECUTOR_STARTED` only after spawn returns `accepted`
- if spawn is rejected, do not post `ACP_EXECUTOR_STARTED`; record the rejection payload/error and escalate or retry by policy
- check for an existing unfinished `ACP_EXECUTOR_STARTED` for the same task/stage before spawning

Never silently switch from ACP to local implementation when ACP delegation is the assigned workflow.

## Frontend Developer

Required parent-side verification:

- target URL and viewport
- browser navigation proof to the changed page
- ONE `browser` aria-snapshot (`format=aria`) at the top of the run, output pasted verbatim, not summarized — reuse `axN` refs for subsequent clicks/screenshots/evaluates instead of re-snapshotting between actions (axN refs stay bound to live nodes via Playwright DOM ids)
- visible DOM text scan for raw namespace/key-shaped i18n literals such as `landing.features.items[0].title`, `landing.foo.bar`, or `common.save`
- console error check
- failed-network check
- click/interaction evidence for changed behavior
- responsive/layout check when UI changed
- build hash or served asset proof when deployment/bundle behavior matters
- AC-specific quantitative measurement when the AC names a measurable quantity (clearance in px, gap in px, contrast ratio, viewport-bound rect, etc.) — bounding-box rect, computed style, or pixel measurement against the AC threshold; the packet must include the actual number, not "looks fine" or "approximately ~Npx"

Test artifacts cited as evidence must reference the **current task or its AC ids** in their filename or test names (e.g. `tests/vp-12-...spec.ts` or `it("VP-12 AC1 hero descender clearance >= 5px", ...)`). Reusing a sibling task's spec because it superficially overlaps is FAIL on the AC-mapping check, regardless of whether the borrowed spec passes — Architect/QA cannot verify AC coverage from a spec that names a different task. If no VP/AC-specific spec exists, write one before submitting evidence.

When the spec uses `Preserve`, `must match`, `keep`, or quotes specific values
(`rotateY(-14deg)`, `mb-12`, `lg:left-8`, `perspective: 2200px`,
`transform-origin: left center`), the implementation must match those values
exactly. The `or measured equivalent` clause covers numeric variation only
(e.g., `rotateY(-16deg)` for `-14deg`, `perspective: 2400` for `2200`,
`mb-10` for `mb-12` if subtitle clearance is met). It does **not** cover
direction inversion, pivot-axis flip, mirrored origins, or substitution of
named CSS classes. Treat direction-mirrored transforms (`rotateY(+N)` at
`right center` vs `rotateY(-N)` at `left center`) as a structural change, not
an equivalent. If a different visual direction looks better, do not flip it
in the implementation — surface it as an explicit spec-amendment request to
`@lead` and wait for spec approval before changing direction.

If any AC lacks browser proof, re-spawn the implementer only with a complete `acp-delegation` implementation payload. Tell the child exactly which AC lacks evidence and require browser navigation plus literal snapshot/DOM output.

If the role flow requires Codex review, spawn Codex review only after parent browser evidence is captured. Provide the diff, ACs, child output, parent evidence, and unresolved risks. If Codex returns FAIL or INCONCLUSIVE, keep the task out of review and route according to board rules.

Only when parent browser checks and required review PASS: post the consolidated evidence packet, then PATCH to `review` (which auto-wakes the Supervisor). Include `@lead` in the evidence comment as defense-in-depth.

## Final Evidence Packet Gate

Chunk or section outputs are not task completion. Before routing a task to
review, the parent must post exactly one consolidated evidence packet that
starts with one of:

- `FINAL_EVIDENCE_PACKET`
- `Active blocker cleared: <one-line blocker>` for rework

That packet must include:

- final commit SHA and loaded/deployed build artifact when applicable
- changed files grouped by task scope, not by child
- RED/GREEN TDD output for feature, bugfix, refactor, or behavior-change code, or a specific no-test-feasible reason plus equivalent runtime/browser regression proof
- every acceptance criterion mapped to fresh parent-observed evidence
- for frontend/UI/i18n: target URL, browser navigation/snapshot output, visible
  DOM text/raw-key scan, console and failed-network output, interaction proof
  when applicable, responsive/layout proof when applicable, and build hash
- for backend/API: target, status/body/readback/runtime evidence
- remaining risks or `none`

Do not move to `review` from a child "Done" section comment, build-only packet,
locale parity output, or source grep. If only section packets exist, keep the
task in implementation/rework and build the final packet first.
Post the consolidated evidence packet with `@lead`, or include `@lead` in the
same routing comment.
When moving to review, include `"packet_commit_sha":"<SHA>"` in the task PATCH.
Rework resubmission is rejected if this SHA is missing or unchanged.

For `frontend_ui` or `mixed` tasks, the final packet is not sufficient by
itself. In the agent/gateway runtime set
`HQCTL=${HQCTL:-"python3 /root/.openclaw/workspace/hqctl.py"}`. If unavailable,
stop and report `@lead HQCTL unavailable on this runtime`. Record structured
pipeline events before routing:

## Structured Pipeline Evidence

This is the canonical pipeline command list. `rework-resubmit` references this
section instead of copying a variant; keep field requirements here aligned with
server-side pipeline validation.

- after source changes: `$HQCTL pipeline-event <TASK_ID> code_changed --commit <SHA> --source <AGENT_NAME>`
- after commit: `$HQCTL pipeline-event <TASK_ID> committed --commit <SHA> --source <AGENT_NAME>`
- after build: `$HQCTL pipeline-event <TASK_ID> built --commit <SHA> --artifact-hash <HASH> --source <AGENT_NAME>`
- after deploy or `/deploy/notify`: `$HQCTL pipeline-event <TASK_ID> deployed --commit <SHA> --artifact-hash <HASH> --deploy-target <URL_OR_ENV> --source <AGENT_NAME>`
- after live build check: `$HQCTL pipeline-event <TASK_ID> live_build_verified --live-sha <SHA_OR_HASH> --deploy-target <URL_OR_ENV> --source <AGENT_NAME>`
- after browser/runtime checks: `$HQCTL pipeline-event <TASK_ID> runtime_verified --deploy-target <URL_OR_ENV> --evidence browser_snapshot=posted --evidence dom_scan=posted --source <AGENT_NAME>`

If another role owns build/deploy, nudge DevOps and wait for `built` and
`deployed` events before routing. Run
`$HQCTL pipeline-state <TASK_ID> --check-ready`.
If it exits nonzero or prints `PIPELINE_READY=false`, do not move to review;
record/fix the missing state. If lead/operator action is needed, post one
blocker comment with `@lead` and the exact pipeline-state output.

## Backend Developer

Required parent-side verification:

- exact API, CLI, worker, queue, DB, or runtime target
- command output for changed behavior, including status and body where relevant
- DB/readback verification for persistence, state changes, migrations, or API writes
- non-HTTP proof for worker, queue, DB-only, file-system, or scheduled behavior
- migration/schema evidence when a migration ran
- regression test output, or an explicit blocker explaining why it could not run
- deploy parity evidence only when backend owner is explicitly responsible for deploy; otherwise hand off to DevOps

If any AC lacks runtime proof, re-spawn the implementer only with a complete `acp-delegation` implementation payload. Tell the child the exact runtime target and missing command/readback evidence.

If the role flow requires Claude review, spawn Claude review only after parent runtime evidence is captured. Provide the diff, ACs, child output, parent evidence, and unresolved risks. If Claude returns FAIL or INCONCLUSIVE, keep the task out of review and route according to board rules.

Do not perform production deploy, `scp`, or `systemctl restart` from Backend unless the task explicitly assigns that deployment responsibility to Backend.

Only when parent runtime checks and required review PASS: post the consolidated evidence packet, then PATCH to `review` (which auto-wakes the Supervisor). Include `@lead` in the evidence comment as defense-in-depth.

## DevOps Engineer

Required parent-side verification:

- task classification: deploy implementation, deploy validation, infra drift,
  credential/operator action, service config, migration, rollback, source bug, or
  external outage
- source host/path, branch, commit SHA, and proof that production source was not
  patched directly
- artifact/build proof: hash, digest, build id, package path, or loaded frontend
  build hash when frontend artifacts are deployed
- approved deploy script/command output and exit status
- target host/env/service names
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
- explicit production target/host/service names

Default DevOps implementation re-spawn uses Codex unless the task or `dev_acp_flow` explicitly selects Claude. Claude review is for risky infra/deploy/auth/migration/cross-host work.

If any AC lacks live-deploy proof, re-spawn only with a complete `acp-delegation` implementation payload. Tell the child the exact missing live probe, target host/service, and evidence format.

Only when parent deploy checks and required review PASS: post the consolidated evidence packet, then PATCH to `review` (which auto-wakes the Supervisor). Include `@lead` in the evidence comment as defense-in-depth.

## Review Outcomes

Use verdicts consistently:

- `PASS`: every AC has observed evidence and required review passed.
- `FAIL`: confirmed defect, missing evidence after allowed retry, or child made out-of-scope changes.
- `INCONCLUSIVE`: evidence is insufficient but not enough to confirm a defect.
- `INFRA BLOCKED`: required environment/tool/runtime is unavailable.

Never convert missing evidence into PASS. Missing browser/runtime/deploy proof blocks routing to review.

## i18n Locale Rendering Gate

**Mandatory for any task involving locale/translation files (en.json, pt.json, es.json, fr.json).**

Before posting evidence or moving to review, verify each non-default locale renders content in the correct target language:

1. Switch to each locale using the app's actual locale control, route, or documented persisted setting. Do not assume `?lng=` works; TaskFlow uses visible language controls.
2. For each locale, verify visible text is in the **correct language** — not the source language, not raw keys
3. Quick CLI fallback: grep locale files for source-language content. If source is Portuguese:
   ```bash
   grep -c "configuração\|funcionalidade\|página\|seção" src/locales/es.json  # must be 0
   grep -c "configuração\|funcionalidade\|página\|seção" src/locales/fr.json  # must be 0
   ```
4. If any locale renders wrong-language content, do NOT submit. Re-spawn ACP executor to fix with explicit translation instructions per `acp-delegation` i18n rules.

This gate blocks review routing. Missing locale verification = INCONCLUSIVE, not PASS.
