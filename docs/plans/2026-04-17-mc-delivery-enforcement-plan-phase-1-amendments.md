# MC Delivery Enforcement Plan — Amendments (Phase 0 + Phase I)

**Amends:** `docs/plans/2026-04-16-mc-delivery-enforcement-plan.md` v2.0
**Date:** 2026-04-17 (extended with Phase 0 section same-day)
**Scope:** failure-mode-driven corrections to Phase 0 (Board flags + watchdog + shadow metrics) and Phase I (Shared Comment Policy Service). Not a replacement plan. Each correction cites the v2.0 section it amends and the concrete failure mode it addresses.
**Author context:** arose from two confrontation reviews against v2.0 — one on Phase I after a parallel spec was rejected, one on Phase 0 before implementation began. The points below are what survived those reviews.

---

## Part A — Phase 0 amendments (Board flags + watchdog + shadow metrics)

### A.1 Watchdog must emit a forensic record per repair, not just a log line (F1)

**What v2.0 currently says** (§I7):
> "runs every 60 seconds / auto-repairs null deadlines to `now + heartbeat_interval` / repeated repair failure pages the operator"

**Failure mode:** `status='online' + checkin_deadline_at IS NULL` is a symptom of a writer-path bug (recent commits `f8145ab9 Rearm heartbeat deadline on agent auth traffic` and `14520282 Document heartbeat supervision fix` prove this is an active bug surface). Silent auto-repair erases diagnostic evidence. The bug persists invisibly.

**Amendment:** replace §I7's bullet list with:
> - runs every 60 seconds
> - before repair, emits a structured forensic record: `{agent_id, prev_deadline=null, last_seen_at, wake_attempts, elapsed_since_last_seen, repair_reason}` into a new `agent_heartbeat_repair_events` table (append-only)
> - auto-repairs null deadlines to `now + heartbeat_interval + grace`
> - alert condition: **same agent repaired ≥ 3 times within 1h** (pattern indicator of a writer-bug), in addition to the existing "repeated repair failure" clause
> - the 1h-repeat-repair alert routes to the operator via the existing WhatsApp/Baileys path

**Why:** repair becomes observable. Operator can diff the forensic events to pinpoint which writer path is dropping the deadline.

### A.2 Shadow metrics must share a classifier library with Phase I (F2)

**What v2.0 currently says** (§Phase 0):
> "shadow metrics for: duplicate comments / ack-only comments / rework count / non-artifact update count / actionability violations on active tasks"

**Failure mode:** Phase 0 shadow metrics and Phase I `CommentPolicyService` both need the same regex-and-jaccard classification. If Phase 0 ships its own classifier implementation, Phase I duplicates or refactors. Wasted implementation.

**Amendment:** add to §Phase 0 scope:
> - a shared library at `backend/app/services/comment_classifier/` exposing `classify(message, packet_type) -> list[str]`. This is the single source of ack-only + near-duplicate detection consumed by:
>   - Phase 0 shadow-metric emitter (records classifier flags as observability events, no enforcement)
>   - Phase I `CommentPolicyService` (consumes the same flags, gated by the board's `rollout_flags.comment_policy_v1` setting — see A.3)

### A.3 Rename the board feature-flag field + capture unknown keys (F3, F4)

**What v2.0 currently says** (§Rollout Strategy):
> "Introduce board-level feature flags for workflow invariants, for example: `workflow_invariants_v1` / `structured_blockers_v1` / ..."

**Failure mode F3:** "workflow_invariants" as a column name suggests invariant objects; it's actually a boolean feature-flag map. Semantic mismatch for future readers.

**Failure mode F4:** a hard allowlist gates every new invariant on a code change before the flag can be set. An empty column rejects all unknown flags and loses signal about what operators tried to enable.

**Amendment:** replace the "board-level feature flags" bullet with:
> - two JSON columns on `boards`:
>   - `rollout_flags: dict[str, bool]` — known flag keys only; enforced via an allowlist in the BoardUpdate validator. Canonical keys: `comment_policy_v1`, `structured_blockers_v1`, `operator_decisions_v1`, `deploy_truth_v1`, `heartbeat_watchdog_v1`.
>   - `rollout_flags_unknown: dict[str, bool]` — unknown keys routed here. Accepted but not acted on. Observable so operators can see what keys are being tried before the allowlist adds them.

Renaming resolves F3. The split column resolves F4.

### A.4 Shadow-metric events need a retention policy from day one (F5)

**What v2.0 currently says:** nothing about retention for shadow-metric events.

**Failure mode:** ~1,000 comments/day × 3 emission types = ~1M rows/year. Operator queries slow; storage climbs.

**Amendment:** add to §Phase 0 scope:
> - `shadow_metric_events` table carries a 90-day retention policy: rows older than 90 days are deleted by a daily cleanup job bundled with the watchdog scheduler. Retention configurable per deployment via `SHADOW_METRIC_RETENTION_DAYS` setting, default 90.

### A.5 Actionability-violation metric must instrument existing raise, not re-check (F6)

**What v2.0 currently says** (§Phase 0):
> "shadow metrics for: ... actionability violations on active tasks"

**Failure mode:** prod's `_require_delivery_contract_for_task_state` (tasks.py:250) already raises 422 on missing contract metadata. A shadow metric that independently re-runs the check adds overhead without new signal.

**Amendment:** clarify in §Phase 0:
> - the actionability-violation metric is recorded by **instrumenting the existing `_require_delivery_contract_for_task_state` raise path**, not by duplicating the check. The function records the violation event (including the missing-fields list and the attempted transition) before raising. Single source of truth; single enforcement site.

### A.6 Watchdog PR must include a scheduler (F8)

**What v2.0 currently says** (§I7): "runs every 60 seconds" — asserted as a behavioral contract.

**Failure mode:** shipping only the pure watchdog function without a scheduler = the function never runs. The behavioral contract in the plan is unmet.

**Amendment:** add to §Phase 0 scope:
> - scheduler wiring (not a separate follow-up): the watchdog runs on a 60-second interval via the same scheduling primitive MC currently uses for `queue_worker`. If the current backend has no in-process scheduler suitable for this, the PR must introduce one (minimum: asyncio background task registered at app startup, cancelled on shutdown). **Shipping the watchdog function without an invoker is rejected as incomplete.**

### A.7 Migration must be tested on both PostgreSQL and SQLite (F9)

**What v2.0 currently says:** nothing about cross-engine migration testing.

**Failure mode:** `server_default=sa.text("'{}'")` behaves differently across PG and SQLite. Prod uses PG; tests use SQLite.

**Amendment:** add to the acceptance matrix (§Annex B):
> 8. Migration portability
>    - migration upgrade + downgrade runs clean on PostgreSQL
>    - migration upgrade + downgrade runs clean on SQLite
>    - JSON column round-trips `{"comment_policy_v1": true}` identically on both engines

### A.8 Phase 0 is visibility-only — operator framing (F10)

**What v2.0 currently says** (§Phase 0 Expected value): "immediate visibility into pathology / heartbeat blind-spot closed early."

**Failure mode:** operator and board may expect Phase 0 to reduce noise. It won't. 1,112-comment pain continues until Phase I lands.

**Amendment:** add a rollout expectation to §Phase 0:
> - **Phase 0 yields observability, not noise reduction.** The 36h-incident comment volume will not drop until Phase I ships the shared CommentPolicyService. Phase I must follow Phase 0 within 2 weeks or Phase 0 is pure operational cost. This is an explicit operator commitment, not an implementation detail.

### A.9 Cold-start baseline is a known limitation (F11)

**What v2.0 currently says:** nothing.

**Failure mode:** 32 existing boards have no historical shadow-metric data. Week-1 readings have no comparison anchor.

**Amendment:** add to §Phase 0:
> - Week 1 of shadow-metric collection is declared the baseline. Week 2+ readings compare against it. Historical comparisons prior to Phase 0 rollout are not recoverable — this is an accepted cold-start limitation.

---

## Part B — Phase I amendments (see below, unchanged from original amendment document)

## 1. Apply shadow-mode-first uniformly to I9 ack-only, not just metric thresholds

### What v2.0 currently says

- §Metrics And Alerts / Promotion rule: *"thresholds may begin in shadow mode"*
- §Failure mode 6: *"Threshold overfitting... use shadow mode first for selected thresholds, then promote the proven ones into enforcement."*
- §I9: *"reject acknowledgment theater such as Acknowledged, Received, Confirmed, holding exactly there"* — no shadow phase mentioned
- §Phase I: ships I9 as hard rejection

### The inconsistency

v2.0 argues (correctly) that empirical thresholds come from one severe incident cluster and some must start as shadow metrics before becoming hard rejects. It then exempts I9 ack-only rejection from that principle, despite I9's regex being tuned on the same single-incident corpus.

### Amendment

Replace v2.0 §I9 rule #2 with:

> 2. Ack-only classification
>    - Comments matching the ack-only pattern are marked with a structured classifier flag at write time.
>    - A board-scoped setting `comment_signal_filter ∈ {off, default_hidden, hidden_strict}` controls whether flagged comments are rejected, hidden, or only tagged for observability.
>    - Initial rollout value for all boards: `off` (flag + observability, no rejection, no hiding).
>    - Boards graduate to `default_hidden` only after (a) Phase II blocker/review sidecars are live on the board AND (b) two weeks of shadow data show the classifier false-positive rate ≤ 5% on that board.
>    - `hidden_strict` is operator-approved per-board, post-Phase II.

Rationale: v2.0 §Failure mode 4 explicitly warns that *"dedup and ack rejection can reduce noise without fixing routing if blocker objects and review objects are not live yet."* The canonical hard-rejection form of I9 ships before Phase II and triggers exactly that failure mode. Shadow-mode-first defuses it without delaying the noise-reduction value — the classifier flag is available for observability from Day 0.

### Phase order impact

- Phase I still ships first (classifier + shared service + flag field), unchanged.
- `default_hidden` graduation moves from "Phase I rollout day 3" to "Phase II rollout + 2 weeks of clean shadow data."
- No new phase added; Phase I's scope shrinks, Phase II's gating responsibility grows.

---

## 2. Add a healthy-corpus calibration gate before Phase I merges

### What v2.0 currently says

- §Incident replay acceptance test uses the Phase 2 failure scenario as the proving ground.
- §Annex B additional matrix requirement: *"the replay alone is necessary, but not sufficient."*
- No explicit pre-merge gate against a healthy corpus.

### The gap

The replay test validates that the classifier catches comments from a known pathological window. It does not protect against the classifier learning the pathology's linguistic fingerprint rather than true low-signal content. Without a healthy-corpus gate, a classifier that flags 80% of Dev Squad's crisis comments looks successful even if it would flag 40% of a healthy board's normal traffic.

### Amendment

Add to v2.0 §Annex B before the incident replay subsection:

> #### Pre-merge healthy-corpus gate
>
> Before Phase I merges:
>
> 1. Export comments from the 9 done Phase 2A-F tasks on the Dev Squad board and from at least one task on a non-Dev-Squad board (for cross-board signal).
> 2. Run the classifier against both corpora.
> 3. Required: healthy-corpus flagged rate ≤ 15% per corpus, per rule, per packet type.
> 4. Required: per-rule flagged rate on the pathological corpus within ±5% of the target measured during calibration (currently 32% ack-only, 7% near-duplicate).
>
> If healthy-corpus rate > 15% on any corpus slice, the classifier is over-fitting the pathological fingerprint. Tune regex + re-calibrate before merge. Do not ship a Phase I build that fails this gate.
>
> Calibration script + fixtures: `scripts/calibrate_comment_classifier.py`, `tests/fixtures/comments_healthy.csv`, `tests/fixtures/comments_pathological.csv`.

### Why this is load-bearing

The baseline data in §Problem and §Metrics comes from a 36-hour crisis window. Any regex optimized against it will over-fit. The healthy-corpus gate is the cheapest defense against shipping a classifier that silences normal coordination on boards that are not in crisis.

---

## 3. Apply packet-type severity modulation to I9 ack-only

### What v2.0 currently says

- §I9 rule #2 applies uniform ack-only rejection regardless of task metadata.
- §Current Codebase Reality lists `review_packet_type` as existing metadata.
- The relationship between `review_packet_type` and ack-only severity is unspecified.

### The problem

Prod's `ReviewPacketType` taxonomy (`backend/app/schemas/tasks.py:23-31` on `prod/master`) distinguishes:

- evidence-requiring: `frontend_ui`, `backend_api`, `infra_ops`, `mixed`
- lower-evidence: `review_only`, `content_copy`, `other`

A short ack on a `review_only` comment is often a legitimate reviewer signal ("Acknowledged, looks good"). The same ack on a `backend_api` task with a packet claim is noise. Uniform rejection produces false positives on the former without improving detection on the latter.

### Amendment

Extend v2.0 §I9 with a severity modifier:

> #### Packet-type severity modifier (applies to I9 ack-only only)
>
> The ack-only classifier consults `task.review_packet_type`:
>
> - Strict (flag AND eligible for eventual hiding/rejection): `frontend_ui`, `backend_api`, `infra_ops`, `mixed`.
> - Lax (flag only if message is < 15 words AND contains no routing verb): `review_only`, `content_copy`, `other`.
> - Task has no `review_packet_type` set: treat as strict.
>
> The near-duplicate classifier (I9 rule #1) is unaffected by packet type.

### Why this integrates with v2.0 §I2

v2.0 §I2 (refined) requires `review` status to have full packet completeness and `in_progress` to have actionability metadata appropriate to the task type. The packet-type severity modifier reuses the same `review_packet_type` signal v2.0 already treats as an actionability dimension. No new concept introduced; existing prod taxonomy consumed.

---

## 4. Scope clarification — Phase I must cover both comment ingress paths

v2.0 §I9 implementation note correctly identifies this:

> *"this cannot live in only one endpoint; MC currently has at least two task-comment ingress paths; enforcement must sit in a shared CommentPolicyService."*

Confirming explicitly for the implementer: the shared service must be invoked from both:

- `POST /api/v1/boards/{board_id}/tasks/{task_id}/comments` — prod `backend/app/api/tasks.py:2986` (and the agent route funnel at `backend/app/api/agent.py:1069` which calls through the same handler)
- `PATCH /api/v1/boards/{board_id}/tasks/{task_id}` — any path that accepts a `comment` field in the update payload

No new architectural guidance here; just a reiteration to catch the second path, which a naive implementation would miss.

---

## 5. Acceptance-matrix additions

Add two rows to v2.0 §Annex B matrix:

| # | Case | Pass criterion |
|---|---|---|
| 1a | PATCH `/tasks/{id}` with `comment` field | Same classifier flags applied as POST path |
| 2a | Healthy-corpus gate | ≤ 15% flagged-rate per corpus per rule per packet type |

---

## 6. What this amendment does NOT propose

- Does not change v2.0's phase ordering (Phase 0 → I → II → III → IV → V → VI).
- Does not change any threshold in §Annex A.
- Does not change the blocker/review/operator-decision domain models.
- Does not add SOUL template changes.
- Does not propose deleting v2.0.

---

## 7. Integration into v2.0

Recommended inline edits to v2.0:

1. Replace §I9 rule #2 body with the shadow-mode text from §1 of this amendment.
2. Add §Annex B "Pre-merge healthy-corpus gate" subsection from §2 of this amendment.
3. Append "Packet-type severity modifier" subsection to §I9 from §3 of this amendment.
4. Add the two matrix rows from §5 of this amendment.

After integration, this amendment file should be deleted to avoid plan fragmentation.

---

## 8. Rejection criteria

This amendment itself should be rejected if:

- Phase I is already mid-implementation and adding shadow-mode would delay landing (not the current state — Phase 0 hasn't shipped).
- Healthy corpus cannot be exported from the MC API (not the case — exports work today).
- `review_packet_type` is about to be deprecated (not the case — prod's delivery-contract work cements it as load-bearing).

None of these rejection conditions hold as of 2026-04-17.

---

## Part C — OpenClaw 2026.4.15 integration notes

The 4.15 release introduces two gateway-side capabilities that directly intersect the invariant scope. Features that are merely complementary (`localModelLean`, prompt/context trims, unknown-tool loop guard default-on, systemd restart-loop fix) require no plan amendment; they reduce symptom pressure upstream without changing what the plan must enforce.

### C.1 Integrate `models.authStatus` into the I7 forensic log and alert gate

**Rationale.** The watchdog's 1h-3x repeat-repair alert (Phase 0 §A.1) assumes that a persistent null-deadline pattern indicates a writer-path bug. In reality, a substantial class of null-deadline incidents is caused by **upstream OAuth expiry or model rate-limit pressure** — the gateway cannot deliver a wake because the provider token is degraded, so `commit_heartbeat` never fires, so the deadline stays null. A writer-bug alert in that case pages the operator for a problem they can already see on the new Model Auth card, and the real fix is provider re-auth, not MC engineering.

4.15 exposes per-provider auth state via `models.authStatus`. Recording it at repair time collapses the alert's false-positive class cleanly.

**Amendment.** Extend §I7 with a `model_auth_snapshot` capture, and extend the alert gate to consult it.

Add to §I7 bullet list:

> - At repair time, call `models.authStatus` on the gateway backing this agent. Store the per-provider response on the forensic row as `model_auth_snapshot: JSONB`. The column is nullable so pre-4.15 gateways and auth-call failures degrade to "no snapshot, alert as before".
> - The 1h-3x alert gate reads the stored snapshots: if all N repairs within the window happened while the relevant provider was flagged unhealthy, the alert is suppressed and the log line categorized as `upstream-auth-degraded` at INFO. If ≥1 repair happened under healthy auth, alert as before. Operator's WhatsApp is not paged for provider-side problems.

**Schema change:**

```python
# AgentHeartbeatRepairEvent gains:
model_auth_snapshot: dict[str, Any] | None = None
```

And a follow-up alembic migration `d4e5f6a7b8c9_add_model_auth_snapshot` adding a nullable JSON column. The existing `c3d4e5f6a7b8` migration does not need to be reopened; the new column backfills as NULL.

**Rollout gate.** Ship only when `.60` (and any gateways MC connects to) is on 4.15+. Pre-4.15 gateways return 404 on the new method; watchdog treats that as "no snapshot available" and falls through to the existing alert logic. Zero regression on 4.14 gateways.

### C.2 QA/Architect evidence packets cite transcript `turn_id`, not external run IDs

**Rationale.** Phase 2 Track A.QA fail-closed because Playwright work was dispatched via ACP, but ACP run IDs were not in the gateway session transcript, so the Supervisor could not correlate claimed evidence against an auditable artifact. 4.15 persists CLI-backed turns (including ACP invocations) into the session history.

**Amendment.** Add a Compatibility Rule after §Compatibility Phase 0:

> **Compatibility Rule 4 (CLI-backed turn evidence, 2026.4.15+):** QA and Architect evidence packets that derive from a CLI-invoked run (ACP, Codex CLI, or any gateway-side `exec`) must cite the gateway `turn_id` from the session transcript. External run IDs (ACP session UUIDs, etc.) are no longer sufficient because the transcript is now the canonical audit surface.
>
> On gateways older than 4.15, external run IDs remain acceptable and the transcript requirement is waived. Supervisor must verify gateway version before applying the rule.

No code change required. Purely a routing-and-review protocol clarification. Unlocks ACP-delegated lanes that currently fail-closed on unverifiable evidence.

### C.3 What this amendment does not do

- Does not block Phase 0 landing. The existing watchdog (commit `b085455e`) is already safe to ship against 4.14 gateways; C.1 is strictly additive.
- Does not introduce a hard 4.15 requirement. Every new behaviour degrades cleanly on pre-4.15 gateways.
- Does not touch C.1's hotfix window. If gateway 1006 (WebSocket abnormal close) failures observed on `.60` are caused by the systemd config-write loop that 4.15 fixes, upgrading first will reduce the watchdog's incident rate independent of C.1. Do the version check before measuring baseline.

### C.4 Sequencing

1. Verify `.60` is on 4.15 or can be upgraded. If not, skip C.1 until the gateway is ready.
2. Ship C.1 in its own commit after the watchdog's existing test suite has one week of baseline data from 4.14 (to measure the false-positive reduction C.1 buys).
3. Ship C.2 as a one-line protocol update in the Supervisor's routing prompt, synchronized with the 5-layer SOUL template sync process.
4. Defer complementary 4.15 features to operator runbook; they do not require plan changes.
