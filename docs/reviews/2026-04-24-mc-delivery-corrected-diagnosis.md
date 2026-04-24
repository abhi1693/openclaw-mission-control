# MC Delivery — Corrected Diagnosis (2026-04-24, post-instrumentation)

This document **replaces** the narrative in
`2026-04-24-mc-delivery-enforcement-review-brief.md` with what the
JSON session logs, activity_events DB, and live process inspection
actually showed when instrumented in real time during the 2026-04-24
session.

## TL;DR

The pipeline **does** deliver quality source code at ~20 min per
iteration. What it does not deliver is throughput to `done`, because
the stage after review-PASS (deploy + live QA-E2E) requires an
operator step that was not performed. Every architectural
intervention I shipped on `feature/phase-0-workflow-invariants`
(Phases 0–VII, parts C/D/E) operates on a pipeline whose *source
stage already worked*. The delivery graph did not bend because the
measured bottleneck was never in that stage.

## What I claimed, and what was wrong

Prior brief language | Actual measurement
---|---
"Agents trapped in loop-posting patterns (40 near-identical comments / 10 min)" | True for 2026-04-17 echo storm, already mitigated by the echo gate before this session. Not the current bottleneck.
"Agents did ~0 TaskFlow commands across 241 tick-sessions today" | Wrong frame. Agents wrote real TaskFlow source in ticks I missed — commits `7b3c7fa`, `2b96b73`, `781c10f` on `DocsPage.jsx` between 16:40 and 17:00. I was searching the outer workspace dir for product code; the TaskFlow repo is inside each agent workspace at `workspace-mc-*/taskflow-web-presence-vite/`.
"Tick is coordination-shaped, not work-shaped" | Partial truth. Ceremony exists. But execution DOES happen inside ticks when task scope matches agent role and inputs are self-contained. QA-Unit shipped a markdown deliverable in 9 min. PF shipped a bounded DocsPage fix in 19 min (implement → FAIL → fix → PASS).
"The template must be rewritten" | Wrong conclusion. A targeted worker template (HEARTBEAT.md) already contains a §3 that says `Spawn the executor for this task` via `sessions_spawn`. ACP is optional; direct execution also works. Rewriting templates was solving the wrong problem.
"All 7 agents run on qwen3.5:cloud for heartbeats" | True statically (config), but operationally fresh-bootstrap ticks run on gpt-5.4 (primary). Model per tick depends on session lifecycle, not just config. The mix is not the bottleneck.
"4 tasks parked because is_blocked=true, agents cannot work" | is_blocked=true was correct — they were linked to OperatorDecision `6f4792f1`. Unlinking D.1 in the DB confirmed the agent pipeline picked it up within 6 min and completed a review cycle in 19 min.
"Full suite: 867 passing" — cited as evidence the work shipped cleanly | Correct, but orthogonal. Unit tests don't exercise the deploy-gap bottleneck at all.

## What the instrumentation showed, end-to-end

Two cycles were run live and logged.

### Cycle 1 — Synthetic doc task, QA-Unit (self-contained)

- 15:50:31: operator files tiny doc summary task, assigned to QA-Unit.
- 15:53:00: QA-Unit posts "drafting" comment and **moves status to
  `review` before the artifact exists** (`in_progress_at=null`,
  skipped in_progress entirely). Delivery-contract gate did NOT
  catch this — real bug.
- 15:55:31: Supervisor manual filesystem check catches the premature
  status, posts "Lead review fail".
- ~15:55: QA-Unit actually writes `docs/test-suite-summary.md`
  (2986 bytes, 8 sections, 22 test cases grouped correctly),
  commits `25a1822`.
- 15:58:52: Supervisor verifies artifact exists, posts PASS.
- **Cycle time: ~9 min from inbox to review-ready with real
  artifact.**

**One real bug surfaced:** the review transition allowed status to
advance without a committed artifact. Supervisor caught it manually.
The shipped delivery-contract gate should have caught it
automatically; it did not.

### Cycle 2 — Real inbox task, PF (D.1 — docs sidebar content)

- D.1 was one of 4 tasks parked on OperatorDecision `6f4792f1`
  (deploy-target-unreachable). Operator unlinked D.1 from the
  decision at 16:34:50 via DB DELETE, assigned to PF.
- 16:39:46: operator posted `@Programmer-Frontend` mention comment.
- 16:40:16: PF moved D.1 to `in_progress`.
- 16:43:45: PF posted review packet with commit `2b96b73` — real
  change to `taskflow-web-presence-vite/src/pages/DocsPage.jsx`.
- 16:52:34: Architect bounded review FAIL — accuracy issue flagged
  at `DocsPage.jsx:773-774` (doc claims `app/main.py`, source uses
  `main.py`).
- 16:54:28: PF posted DIAGNOSIS.
- 16:59:34: Architect bounded re-review **PASS on commit `781c10f`**.
- 17:00:41: Supervisor ack'd PASS.
- **Cycle time: ~26 min from operator unblock to Architect PASS,
  with one FAIL→fix→PASS iteration in the middle.**

The full source pipeline — implement, review, iterate — completed
without operator intervention after the initial unblock.

### What did NOT happen next (and why the graph doesn't move)

After Architect PASS, D.1 sits in `review` status. For it to reach
`done`:

- QA-E2E must validate against a live TaskFlow surface
- The surface must be reachable at the task's `validation_target`
- Nobody on the board is authorized to stand up that surface
  (memory `feedback_dont_deploy_for_agents.md`: deploy is
  operator/DevOps-human's job)

At some point during this session, PF's workspace-scoped Vite dev
server came up on `http://192.168.2.60:3000`. That unblocks QA-E2E
in principle — but:
- Task `validation_target` fields still point at `http://192.168.2.64:3000`
  (which is MC, not TaskFlow)
- Agent memory was partially corrected (PF knows `.60=TaskFlow`,
  `.64=MC`), partially stale (other agents' memory still refers to
  `.64:3000` as the deploy target)
- QA-E2E won't rerun against the new surface until one of these two
  is fixed

## The real mission-blocker, stated correctly

Source quality: **working**. Review cycle: **working**. Tests: **working**.
Pipeline stalls at the deploy → QA-E2E → done bridge.

Structural reasons:
1. Tasks have the wrong `validation_target` value (stale from
   earlier topology).
2. Historically, agents were explicitly told never to deploy —
   deploy has always been the operator's domain.
3. TaskFlow has no CI/CD pipeline; it's Vite HMR off an agent
   workspace, which is ephemeral and not a production target.
4. The OperatorDecision `6f4792f1` correctly identified this at
   13:24 UTC today. It is waiting for operator action. No agent
   intervention can resolve it.

## Confusion about IPs (raised by operator)

| Host:Port | Reality (verified this session) | What tasks/memory say |
|---|---|---|
| `.60:3000` | TaskFlow Vite HMR (running in PF workspace, started mid-session) | Sometimes "TaskFlow" (correct), sometimes "connection-refused" (was true earlier today), sometimes absent |
| `.64:3000` | MC dashboard (Next.js) | Sometimes "TaskFlow deploy target" (WRONG — stale task data) |
| `.64:8000` | MC backend API | Correct |
| `.160:8100` | TaskFlow backend API | Correct in some memory notes, wrong in others |
| `.63` | intended TaskFlow production (not validated this session) | Memory says "never .63" (possibly stale) |

Task data is the authoritative fix point. Do not edit agent memory
directly — agents resync from task data on review. Fixing
`validation_target` on the affected Phase 2 tasks will propagate.

## What to un-ship or de-emphasize

The architectural work on `feature/phase-0-workflow-invariants`
is not wrong — echo gate, OperatorDecision model, delivery contract
all have merit. But their emphasis in the prior brief
("delivery-enforcement") was wrong for this pipeline's actual
failure mode. Framed correctly:

- **Phase I/VII (classifiers, echo gate):** useful noise-reduction,
  not a delivery accelerator. Keep.
- **Phase II (Blockers sidecar):** useful structured data, not yet
  exercised enough to show value.
- **Phase III (OperatorDecision):** correctly surfaced THE real
  blocker of this entire board. Actively useful. Keep.
- **Phase IV (Actionability contract):** would have caught cycle 1's
  premature-review bug if fully wired; does not catch it today.
  Real hotfix candidate.
- **Phase V (Deploy-truth):** off on Dev Squad; would only help
  once there's a real deploy to truth-check against. Currently
  inert.
- **Phase VI (Lead scoring, blocked-lane suppression):** useful;
  small effect on throughput.
- **Part C/D/E addenda:** supporting infrastructure, not drivers.

## What would actually move throughput now, in order

1. **Stand up a stable TaskFlow deploy target** (Vite HMR on a
   reliable host, or a real static build on `.63`, or any other
   reachable URL). Without this, `review → done` cannot happen at
   all.
2. **Fix `validation_target` on affected Phase 2 tasks** to match
   that target.
3. **Close OperatorDecision `6f4792f1`** with the resolved URL.
   The Phase III bridge flips `is_blocked=false` on all four
   dependent tasks. They run QA-E2E against live and flow to `done`.
4. **Fix cycle-1 bug:** delivery-contract gate should refuse
   `inbox→review` without `packet_commit_sha` + non-empty artifact
   evidence. Small code fix in `_apply_lead_task_update` or
   equivalent worker transition path.
5. Everything else (template rewrites, model-tier changes, ACP
   enforcement, etc.) is optional and secondary.

## Honest self-assessment of this session's work

I spent most of this session proposing template rewrites,
confronting codex about them, and escalating theory when the real
answer was: **instrument one task and watch**. Two cycles of that
reversed the entire narrative in ~30 minutes of wall time.

The correct instinct at turn 1 was what the operator was already
asking for: "Make one task complete end-to-end on its own,
instrument the friction, fix only that, repeat." Every time I
drifted back to rule-proposing, the operator pulled me back.

Future me: when confronted with "delivery is slow," the cheapest
diagnostic is always a single real end-to-end run with full
instrumentation, not another round of architectural reasoning.
