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

---

## Self-audit addendum (2026-04-24, post-brief)

After writing the brief above, three skeptic sub-agents (verification /
gap-hunting / prod-state) reviewed it against the actual code + live
systems. Scoping this addendum honestly because the original brief
overstated coverage on several axes.

### Claim-verification results

All 5 "What to validate" priorities **VERIFIED** as-described against
the code. One caveat: the Postgres `IntegrityError` regression tests
(stale-agent-blocker, subagent-failure-blocker) all run against SQLite
in-memory fixtures. No production-shape Postgres IntegrityError round-
trip test exists; the `_is_dedupe_integrity_error` substring match is
protected by the *current* Postgres + asyncpg behaviour (server-side
message text includes the quoted `uq_blockers_*_open` identifier) but
would silently regress under asyncpg driver or `lc_messages` drift.

### Wording corrections

- **"6 of 7 rollout flags on"** — actually 6 keys present and true;
  `deploy_truth_v1` is *absent from the JSON blob*, not stored as
  `false`. Functionally equivalent under the allowlist helper but
  the brief's phrasing implied a stored false value.
- **"All 4 tasks is_blocked=true"** — `is_blocked` is a runtime-derived
  property, not a persisted column. The column `operator_decision_required`
  stays False on the 4 parked tasks; the `is_blocked=true` signal comes
  from the `task_has_pending_operator_decision` bridge at read time.
- **"Templates synced to 7 agent workspaces"** — accurate, but a naive
  grep for the lead-branch phrase ("Escalate Persistent Blockers")
  shows it on the Supervisor workspace only; worker workspaces carry
  the worker-branch phrase ("Parked tasks: ... DO NOT TOUCH") — 6/7
  worker workspaces have it. The 7th (`mc-3c920c2a`) is Supervisor's
  secondary alias workspace and intentionally has no HEARTBEAT.md.

### Unstated issues surfaced in the gap-hunt

The gap-hunting agent found 10 findings the brief didn't call out.
Priority-ordered, with the concrete repro / attack.

#### H-priority (ship-blocking)

**H1 — Task DELETE 500s on any task with a linked
Blocker / Review / ReviewBlocker / OperatorDecisionTaskLink row.**
Migrations `b10ca1ab1e00` / `01` / `03` declare FKs without
`ondelete=`, which Postgres defaults to `NO ACTION` (RESTRICT).
`delete_task_and_related_records` at `app/api/tasks.py:2322-2382`
cleans activity_events / approvals / dependencies / tags / custom
fields but NOT the four Phase II/III sidecar tables. Every task ever
touched by Phase II or III enforcement is now undeletable. Repro:
`POST /boards/{b}/blockers` filing a blocker on task T, then
`DELETE /boards/{b}/tasks/{T}` → IntegrityError 500.

**H2 — SSRF guard bypassable via alternate IP literal encodings.**
`_VALIDATION_TARGET_BLOCKED_PREFIXES` in `app/schemas/tasks.py:77-86`
matches raw `str.startswith`. Decimal IPv4 (`http://2130706433/` =
127.0.0.1), hex (`http://0x7f000001/`), octal (`http://0177.0.0.1/`),
expanded IPv6 (`http://[0:0:0:0:0:0:0:1]/`) all bypass the prefix
list. No DNS resolution: an attacker-controlled domain that
A-records to 127.0.0.1 or 169.254.169.254 (AWS IMDS) bypasses too.
The private-LAN deployment limits blast radius but the gap is real.
Fix: parse via `ipaddress.ip_address` after resolving the hostname
once, not string-prefix matching.

**H3 — Echo gate returns HTTP 409, triggering exactly the auto-retry
storm the gate is supposed to prevent.**
`_echo_guard_suppressed_error` at `app/api/tasks.py:211-222` returns
`409 comment_echoed_as_no_op`. Compare the sibling
`_lane_quieting_suppressed_error` at `:250-263` whose comment block
explicitly says *"403 — not 409 — because Clients auto-retrying on
409 would loop"*. Agent HTTP middleware (httpx Retry, aiohttp retry)
commonly treats 409 as transient. Same anti-pattern the brief
claimed the gate closed; an agent in a retry storm will hammer the
gate with the same echoed comment until its retry budget exhausts.
Fix: 403 with `Retry-After: never` or a structured `retry: false`
signal in the body.

#### M-priority (latent risk)

- **M4 — Main-agent tokens unscoped on `POST /boards/{b}/tasks/{t}/
  subagent-failure`.** `_guard_task_access` short-circuits
  "allowed" when `agent_ctx.agent.board_id` is falsy (main tokens);
  combined with no rate limit, a compromised main token is a cross-
  tenant blocker-flood vector. `app/api/agent.py:241-245`.
- **M5 — D.1 citation not redacted.** `subagent_failure_blocker._citation_for`
  at `:158-165` interpolates `payload.error_class` raw into the
  citation. D.2 (sibling stale-agent path) redacts via
  `redact_gateway_error_message`. Stack traces carrying
  `Authorization: Bearer …` or `?token=…` would land in Blocker rows
  visible on operator dashboards.
- **M6 — Shadow-metric double-count.** A comment firing both
  `ACK_ONLY` and `ECHO_SHAPE` produces two `ShadowMetricEvent` rows
  with identical `source_event_id`. Dashboards running
  `COUNT(*) WHERE event_type LIKE 'comment.%_candidate'` overstate
  flagged-comment volume ~1.5-2x once ECHO_SHAPE rollout tuning
  begins. `shadow_metrics.py:284-290, 433-440`.
- **M7 — OperatorDecision `pending` rows never age out.**
  `app/services/retention.py:57-74` purges only shadow_metric_events
  and agent_heartbeat_repair_events. An abandoned decision keeps
  linked tasks `is_blocked=true` forever via the Phase III bridge —
  silent board rot. The live `6f4792f1` is a canary.
- **M8 — `_is_dedupe_integrity_error` doesn't fall back to
  `constraint_name`.** Current substring match on `f"{exc} {exc.orig}"`
  works on current Postgres but not guaranteed across asyncpg
  version drift. Trivial fix: also check
  `getattr(exc.orig, "constraint_name", None)` before falling back
  to the substring match.

#### L-priority

- **L9 — Echo-guard query ordering.** The expensive `EXISTS` over
  blockers runs BEFORE the rollout_flags read at
  `app/services/echo_guard.py:185-196`. If the flag is off, that
  query was wasted. Under H3's retry amplification, this becomes
  10+ wasted queries/sec per amplifying agent. Reorder the
  rollout_flags read to short-circuit first.

### Revised "What to validate" for any further review

Add these five probes to the original five:

6. **DELETE test coverage** — is there a test anywhere that deletes
   a task carrying a Blocker / Review / OperatorDecisionTaskLink?
7. **SSRF evasion** — do the negative tests on `validation_target`
   cover alternate IP encodings or only the obvious `localhost` /
   `127.0.0.1` forms?
8. **Ingress retry behaviour** — what status codes does each gate
   return, and would agent retry middleware amplify?
9. **Redaction coverage** — which citation paths run
   `redact_gateway_error_message`, which don't? Asymmetry = leak.
10. **Retention coverage** — which append-only tables does
    `retention.py` purge, and which rot? OperatorDecisions are one;
    are there others?

### Honest reflection

The original brief was accurate on what it covered. But it was
**calibration-biased toward "did I implement what I said"** rather
than "did I implement everything that should exist." The gap-hunting
agent's 10 findings are the shape of issue an external reviewer
would naturally find by probing adversarial rather than confirming
narrative. Future review briefs should include that second lens as
explicit probe categories (DELETE, retry-safety, evasion, asymmetry,
retention) rather than trusting the implementer to surface their
own omissions.

---

## Codex skeptic pass (2026-04-24, gpt-5.5 / high / read-only)

The brief (self-audit addendum included) was handed to Codex
gpt-5.5/high in read-only mode with the instruction "confront, do not
validate." Findings below are verbatim severities + paraphrased
evidence from that run. They re-frame several load-bearing claims and
are **unresolved** — treat the self-audit as one lens, this pass as a
second.

### Re-framings of prior claims

- **C1 (Critical) — Phase V "live deploy truth" is operationally
  hollow.** `deploy_truth_v1` is OFF on Dev Squad due to backfill;
  review/done still pass without live SHA check. Calling Phase V
  "shipped" is technically true but operationally misleading.
  Unknown `packet_commit_sha` should block affected transitions or
  require an explicit operator exception, not disable the invariant
  globally.
- **C2 (Critical) — H2 SSRF fix is incomplete.** `ipaddress.ip_address`
  after a single DNS resolve still leaves open: redirect-hop SSRF,
  DNS rebinding / TOCTOU between validate-time and connect-time,
  IPv4-mapped IPv6, link-local / private ranges, proxy behavior,
  "validated host ≠ connected address" failure modes. Fix must
  validate every redirect hop *and* the actual connect target
  (address pinning, or policy check on every hop).
- **H2 (High) — "VERIFIED as-described" is confirmation testing.**
  The self-audit verified the implementer's narrative, not the
  production-risk surface. `VERIFIED` should be scoped to "matches
  narrative," not "safe to ship." The addendum's gap-hunt is
  exactly what a real audit produces, which is the tell that the
  first pass was too narrow.
- **H3 (High) — 867 passing is partially theatrical** for the
  enforcement paths. Synthetic IntegrityError + SQLite do not
  exercise asyncpg, migration FK cascade, live rollout-flag state,
  or retrying agent clients. The risk-bearing paths are the ones
  least exercised.
- **H5 (High) — D.1 citation asymmetry is a category error, not a
  per-feature bug.** M5 in the self-audit says "D.1 interpolates
  raw `payload.error_class`". Correct fix is sink-level redaction
  (every citation path runs through `redact_gateway_error_message`),
  not per-call hardening. Any new citation path re-opens the leak.
- **H6 (High) — M4 (main-agent token unscoped) is under-severed.**
  Not "medium latent"; a compromised main token that can cross-board
  or cross-tenant file blockers with no rate limit is a blocker-
  integrity incident that directly defeats the routable-blocker
  promise. Raise to high.
- **H7 (High) — D.1 "auto-file runtime Blocker" is overstated.**
  Because gateway push is not wired, the system depends on the same
  loop-posting agents to call the self-report endpoint correctly.
  It adds a structured path, but not reliable capture. Net effect
  is optional, not automatic.
- **H8 (High) — H3 root-cause model under-evidenced.** The retry-
  amplification claim rests on unverified HTTP middleware behavior.
  The stronger evidence is that templates explicitly teach agents
  that `comment_echo_guard_v1` "409s echoes," so LLM clients may
  treat 409 as a workflow conflict to resolve by rephrasing and
  retrying. Switch to 403/422 with `retryable:false` for terminal-
  refuse semantics, and fix the model we use to justify it.
- **H9 (High) — Wake-on-resolve listed as non-goal contradicts the
  delivery goal.** If `OperatorDecision` resolution changes
  `is_blocked` only at read time with no wake/notification, agents
  may never resume and dashboards may silently look clear while
  throughput stalls. Promote to high.
- **H10 (High) — "SSRF guard on `validation_target`" in A/B/E
  sections is overconfident.** A string-prefix URL parser is a
  denylist with known bypasses, not an SSRF guard. And this fetch
  runs during review/done — privileged workflow, not harmless
  metadata.

### Medium re-framings

- **M1 — M7 retention framing is wrong.** Auto-purging pending
  `OperatorDecision` rows would silently unblock tasks and lose
  audit history. The missing mechanism is SLA / expiry /
  escalation plus wake-on-resolve, *not* retention deletion.
- **M2 — Flag helper not proven fail-closed on unknown flags.**
  Correction that "`deploy_truth_v1` is absent, not false" is not
  operationally equivalent: absent can mean migration omission,
  typo, stale rollout state, or intentional off. Needs auditable
  flag state with explicit disabled-reason per board, not
  "missing = off."
- **M3 — Echo-classifier regression matrix is too thin.** URL +
  HTTP code + SHA deltas miss real progress evidence: command
  output, timestamps, PR IDs, test names, error classes, stack
  traces, screenshots, build IDs, request IDs, changed repro
  steps. Expect false negatives on productive long-form comments
  and false positives on fresh-but-useless markers.
- **M4 — H1 blast radius likely wider than task DELETE.** Any new
  sidecar FK without `ondelete` will also affect board DELETE,
  agent DELETE, org cleanup, fixture teardown, admin remediation
  scripts. Audit every parent lifecycle that touches Phase II/III
  tables, not just Task.
- **M5 — D.3 WS scope is not verified.** "No-op for shared-secret
  deployment" means the protection is unexercised in the prod
  shape that exists today. Honest claim: "code path exists for a
  future auth model; current shared-secret deployment gets no
  effective WS scope isolation."

### Calibration pushback

- **L1 (Low) — The calibration-bias reflection is itself too soft.**
  Real failure wasn't just "did what I said vs. everything that
  should exist" — it was **confusing implementation completeness
  with operational control**. Partially disabled, synthetically
  tested, non-prod-shaped enforcement was described in
  production-sounding language. Future briefs should distinguish
  "code path exists" from "invariant is enforced under the
  deployment's current flag state and client behavior."

### Cross-cutting theme

Every high-severity finding traces to one of three patterns:

1. **Implementation completeness ≠ operational control.** Phase V
   off, D.3 no-op, D.1 depends on agent cooperation — all "shipped"
   but not enforcing.
2. **Sink-level invariants implemented per-feature.** Redaction,
   fail-closed flag reads, URL safety, token scoping should each
   be single-chokepoint with no opt-in. Current surface has
   multiple call sites that must each remember to do the safe
   thing.
3. **Test shape ≠ prod shape.** SQLite unit tests, synthetic
   IntegrityError, no live flag state, no retry client, no
   redirect chains. The very paths the brief claims are hardened
   are the ones least exercised.

### Next-step hotfix queue (prioritised by this pass)

1. **C1** — scope Phase V fail-closed on missing SHA (operator
   exception or transition block), stop gating on `deploy_truth_v1`
   being globally on.
2. **C2** — SSRF redirect-hop validation + address pinning (not
   just single-resolve IP check).
3. **H5** — sink-level redaction in one `format_citation()` helper,
   remove per-feature interpolation.
4. **H6** — scope main-agent tokens by board_id; rate-limit blocker
   filing per agent.
5. **H9** — wake-on-resolve notification path for OperatorDecision
   state transitions; parked tasks must get an explicit unpark
   signal, not lazy read-time derivation.
6. **H3 / H8** — switch echo gate to 403/422 with `retryable:false`;
   update templates so agents treat it as terminal, not conflict.
7. **H1** — ondelete audit across Phase II/III FKs for all parent
   entities, not just Task.
8. **M2** — explicit flag-state audit endpoint + disabled-reason per
   board; treat absent as error, not off.
