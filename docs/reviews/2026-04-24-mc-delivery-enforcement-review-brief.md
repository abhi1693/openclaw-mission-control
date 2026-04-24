# MC Delivery-Enforcement Review Brief (2026-04-24)

## What to hand to codex

This document is a self-contained brief for an external reviewer (codex gpt-5.5/high,
another AI, or a human engineer) to understand and validate the work shipped on
branch `feature/phase-0-workflow-invariants` during the 2026-04-22 → 2026-04-24
session. It is point-in-time — the branch is live on prod (`.64`, gateway `.60`
upgraded to 2026.4.22 mid-session) and carries 82 commits ahead of `prod/master`
ancestor. Full suite: **867 passing, 0 failing, 5 skipped, 4 xfailed**.

## Problem statement the work addresses

Mission Control (MC) is the control plane coordinating a 7-agent Dev Squad
board running on OpenClaw gateway. Pre-session symptom: delivery throughput in
freefall (56 → 32 → 12 → 4 done/week), agents trapped in loop-posting patterns
(40 near-identical comments / 10 min at one point), ambient HTTP failures
surfacing as free-text "blocked" comments with no routable structure, no
gates preventing review/done transitions on incomplete work. MC's invariants
— "no blocked work without a blocker object", "actionable tasks declare
owner + packet type", "live state reflects live deploy" — were aspirational,
not enforced.

## Phase structure

The plan doc at `docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md`
is the running reference. Phases landed in order:

- **Phase 0** (plan §A) — Board `rollout_flags` JSON column + allowlist;
  `shadow_metric_events` append-only table; heartbeat watchdog forensic log
  (`AgentHeartbeatRepairEvent`); retention purge.
- **Phase I** (plan §B) — Comment classifier (`ack_only`, `near_duplicate`)
  + board-level `comment_signal_filter` tri-state; shadow-mode-first.
- **Phase II** (§I1/§I4) — `Blocker` sidecar with CHECK on category set
  `{source,deploy,runtime,contract,operator}`; `Review` + `ReviewBlocker`
  tables; partial unique index on open supersede chain.
- **Phase III** (§I3) — `OperatorDecision` + `OperatorDecisionTaskLink` as
  first-class entities; compatibility bridge so pending decisions feed
  `Task.is_blocked` derivation.
- **Phase IV** (§I2) — Actionability contract: `in_progress` / `review` /
  `done` require `review_packet_type` + `assigned_agent_id`; delivery-contract
  gate enforces pre- and post-mutation; shadow-metric on violations.
- **Phase V** (§I8) — Deploy-truth: `review` / `done` fetch `{validation_target}/__build`,
  compare `packet_commit_sha` prefix vs live SHA; degraded-validation shadow
  metric when capability absent; SSRF guard on `validation_target` URL parser.
- **Phase VI** (§I5 + §I6) — Lead-heartbeat no-op scoring (two-strike
  `heartbeat_noop_streak_alert`); blocked-lane comment suppression (non-owner
  agents cannot comment on tasks with acknowledged open Blockers).
- **Phase VII** (my addition, 2026-04-23) — Comment-echo write gate.
  Classifier extended with `ECHO_SHAPE` flag (leading-`@mention` handling +
  state-reassurance phrase detection); `echo_guard` service gates at
  comment ingress with three-signal AND (echo-shape + same-author recent
  prior + no blocker state delta + [2026-04-24 refinement] no new
  evidence markers vs prior).

**Part C** (OpenClaw 4.15) — `models.authStatus` integration hooks.
**Part D** (OpenClaw 4.20) — D.1 auto-file runtime Blocker from subagent-
failure payloads (+ agent self-report endpoint since gateway push isn't wired);
D.2 auto-file operator Blocker on stale-agent-session dispatch errors with
token redactor; D.3 WS scope verification (no-op for shared-secret operator
token deployment).
**Part E** (OpenClaw 4.21/4.22) — E.1a authStatus snapshot on watchdog
repair rows + asyncio.wait_for timeout; E.4 structured `citation_request_id`
extracted from 4.20+ `PAIRING_REQUIRED` details; E.2/E.3 cancelled after
verifying PRs touched non-MC surfaces.

## Key primitives to review

1. **`board_rollout_flag_enabled(flags, key)`** in `app/schemas/boards.py`.
   Every gate reads through this helper. A false negative (flag appears off
   when true) silently disables enforcement.
2. **`Blocker` partial unique indexes** —
   `uq_blockers_runtime_owner_open` and `uq_blockers_operator_artifact_open`
   in `app/models/blockers.py`. Dedupe races closed at the DB layer;
   `IntegrityError` handling narrowed to the specific constraint signatures
   to avoid swallowing unrelated violations.
3. **`OpenClawGatewayError.details`** in
   `app/services/openclaw/gateway_rpc.py`. Gateway's structured error frame
   (`data["error"]`) captured wholesale; `.code` and `.request_id` property
   accessors let downstream code prefer structured over message-regex.
4. **`_apply_lead_task_update` validation shape** in `app/api/tasks.py`.
   Ported from `_finalize_updated_task`: pre-apply deploy-truth via
   `_projected_task`, setattr loop after specialized helpers, post-apply
   delivery-contract check. Ordering matters — the pre-apply deploy-truth
   gate MUST see the intended state before mutation to avoid bypass.
5. **`echo_guard.classify_for_echo`** in `app/services/echo_guard.py`.
   Three-signal gate; `is_blocked=true` via `OperatorDecision` bridge does
   NOT trigger lane-quieting (§I6) — asymmetry with `Blocker`-driven blocking.

## Deployment state (prod)

- MC backend on `.64` at branch-tip commit
- Gateway on `.60` at OpenClaw 2026.4.22
- Dev Squad board has **6 of 7 rollout flags on**. `deploy_truth_v1` is
  OFF because 17 live tasks lack `packet_commit_sha` (backfill is per-task
  operator judgement).
- Templates (`BOARD_AGENTS.md.j2`, `BOARD_HEARTBEAT.md.j2`) synced to 7
  agent workspaces. Agents are on `openai-codex/gpt-5.4`; templates use
  imperative rules + concrete curl recipes (gpt-5.4 ignores principle-level
  guidance).
- One production `OperatorDecision` filed (`6f4792f1`) covering the 4
  Phase-2 TaskFlow tasks blocked on operator deploy.

## Known gaps / explicit non-goals

- **E.1b authStatus alert-gate suppression** — deferred. Needs real watchdog
  repair samples to tune the degraded-predicate.
- **§I6 lane quieting asymmetry** — only fires on acknowledged `Blocker`
  rows, not `OperatorDecision`-blocked tasks. Real gap.
- **No wake-on-resolve** when `OperatorDecision` flips to `resolved` — the
  4 dependent tasks silently become `is_blocked=false`; no downstream
  notification.
- **Rework-thrash signal** — no alert when a single task bounces
  `review → rework` 10+ times. Surfaced only via ad-hoc SQL audit.
- **D.1 gateway push wiring** — parser + filer + agent-self-report endpoint
  shipped; gateway doesn't yet push activity events to MC. Latent until 4.22+
  gateway push lands.

## What to validate (review priorities)

1. **Ordering correctness** — pre-mutation vs post-mutation gate order in
   `_apply_lead_task_update` (commit `fa54711c`). Did I port the deploy-truth
   projection pattern correctly? Would a lead PATCH that updates both
   `status` and `validation_target` in one call correctly see the intended
   target during the `/__build` fetch?
2. **Echo-gate refinement false-positive risk** (commit `e8740dd4`). The
   prior-relative evidence check: does "new SHA reference while same URL+HTTP
   code" correctly fall through as not-echo? The regression tests cover
   URL/HTTP-code/SHA deltas; anything else you'd expect?
3. **Structured-error surface port** (commit `c7df99d9`). `OpenClawGatewayError`
   now carries `details` populated from `data["error"]`. Is there any caller
   currently relying on the old sync-positional-arg constructor that my change
   missed?
4. **Partial-unique-index signatures** (commits `9c98b07a`, `ee28761c`). The
   `_is_dedupe_integrity_error` helpers match on
   `uq_blockers_*_open` strings OR the SQLite column-set expression. Cross-
   driver check: does any Postgres-side IntegrityError message format drift
   between asyncpg versions break the match?
5. **Template imperative rules on gpt-5.4** (commits `83ac1bf0`,
   `97effdde`). HEARTBEAT.md's "file OperatorDecision, not hold-loops"
   recipe — is the trigger ("2+ agents, 2+ heartbeats") concrete enough
   that gpt-5.4 won't skip it? The cURL example uses `X-Agent-Token` —
   verified agents can POST via that header.

## Branch state at review time

```
HEAD: feature/phase-0-workflow-invariants
commits: 82 ahead of prod/master ancestor
tests: 867 passed, 0 failed, 5 skipped, 4 xfailed
prod state: mc-backend active, /healthz 200, /api/v1 mounted routes OK
DB migrations: head = d30eab11ad03 (applied on prod via alembic upgrade)
```

Plan doc is the primary context:
`docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md`.
Runbook for operator activation:
`docs/runbooks/2026-04-23-mc-activation-on-dev-squad.md`.

Push back on anything that looks load-bearing but thinly tested. The
partial-index + structured-error + prior-relative-classifier paths all
have regression tests but only synthetic samples — the production echo
storm we're trying to prevent is exactly the regime where synthetic
tests miss edge cases.
