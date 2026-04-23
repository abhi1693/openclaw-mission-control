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

---

## Part D — OpenClaw 2026.4.20 integration notes (Phase VI feeders)

**Context.** The gateway jumped 2026.4.15 → 2026.4.20 mid-Phase-II. Three changelog deltas introduce capabilities Phase VI (§I6 lane quieting + §I1 free-text-blocker enforcement + §I7 heartbeat deadline surfacing) can lean on without any Phase II or Phase III code change. This section pre-stages them so Phase VI does not have to re-discover the integration points.

All three are **additive and deferred** — none blocks Phase III (operator-decision bridge) or earlier merges. They land when Phase VI consumes them.

### D.1 Auto-file `Blocker` from subagent-failure payloads

**Rationale.** 4.19-beta.1 routed cross-agent subagent spawns through the target agent's bound channel account; 4.20 extended subagent failure payloads with requested role + runtime timing (changelog: *"Agents/subagents: include requested role and runtime timing on subagent failure payloads so parent agents can correlate failed or timed-out child work"*). Today §I1's "no blocked work without a blocker object" invariant depends on humans or reviewer agents filing structured rows. Runtime failures fall through as free-text "blocked on timeout" comments — exactly the footgun the invariant exists to prevent.

**Amendment.** In Phase VI, add a `subagent_failure` sidecar hook:

1. Gateway emits a `subagent_failure` activity event with `{requested_role, runtime_ms, error_class, parent_turn_id}`.
2. MC's activity ingest path (new service method in `app/services/blockers.py::auto_file_from_subagent_failure`) maps the payload to a `Blocker` row:
   - `category = "runtime"`
   - `owner_role = requested_role`
   - `required_artifact = None`
   - `citation = f"subagent {requested_role} failed after {runtime_ms}ms: {error_class}"`
   - `created_by_agent_id = <parent agent id>`
3. Gated by the board's `structured_blockers_v1` rollout flag (already reserved in the allowlist at `backend/app/schemas/boards.py:23`). Boards not yet graduated continue to see the free-text comment path.

**Gate.** Requires gateway 4.20+. On older gateways the failure payload lacks `requested_role`/`runtime_ms`; the hook degrades to a no-op WARN log. Before enabling on a board, confirm the gateway version via `openclaw health` or `models.authStatus`.

**Bounds.** Do **not** auto-resolve the filed blocker when the retry succeeds — that's an operator decision (audit preservation). Do **not** supersede existing same-task open blockers automatically; the reviewer-or-operator judgement stays in the loop.

### D.2 Handle stale-agent-session rejection as operator-category `Blocker`

**Rationale.** 4.20 gateway sessions reject stale agent-scoped sessions after an agent is removed from config (changelog: *"Gateway/sessions: reject stale agent-scoped sessions after an agent is removed from config while preserving legacy default-agent main-session aliases"*). MC's dispatch path currently treats this as an ambient HTTP error. For a task assigned to the stale agent, the correct surface is a structured blocker the operator can route, not a transient 404.

**Amendment.** In Phase VI, extend the gateway-dispatch error classifier:

1. On `PAIRING_REQUIRED` or stale-agent-session rejection, the dispatcher files a `Blocker` with:
   - `category = "operator"`
   - `owner_role = "operator"`
   - `required_artifact = f"agent `{agent_name}` missing from gateway config"`
   - `reopen_condition = "re-add agent to openclaw.json and confirm provision"`
2. The task's `is_blocked` derivation (already wired in Phase II, commit `db72a6a2`) reflects the new row on the next read — no additional plumbing needed.
3. `doctor`-surface: 4.20's reason-specific `PAIRING_REQUIRED` details (changelog: *"Gateway/pairing: return reason-specific `PAIRING_REQUIRED` details, remediation hints, and request ids"*) flow into the `citation` field so the operator gets remediation text at the row level.

**Gate.** Same `structured_blockers_v1` per-board flag as D.1. Requires gateway 4.20+ for the reason-specific remediation hints; 4.19 and below file a generic citation.

**Compatibility rule.** The legacy default-agent main-session aliases still work (per 4.20 changelog); do not file a blocker on alias-resolvable sessions, only on genuinely-removed agents. The classifier must distinguish.

### D.3 Verify MC WebSocket subscription scope is `operator.read+`

**Rationale.** 4.20 narrowed WebSocket broadcast authorization (changelog: *"Gateway/websocket broadcasts: require `operator.read` (or higher) for chat, agent, and tool-result event frames so pairing-scoped and node-role sessions no longer passively receive session chat content"*). If MC subscribes with a pairing-scoped device token, it will silently stop receiving `chat`/`agent`/`tool-result` frames after the gateway upgrade. Phase 2F's activity ingest, Phase 0's shadow-metric comment classifier, and Phase VI's lane-quieting observability all depend on this channel.

**Amendment.** This is a pre-flight operational verification, not a code change:

1. Before each gateway upgrade past 4.19, confirm MC's active auth method uses a shared-secret operator token or a paired device with `operator.read+` scope.
2. If MC is running on a narrower-scope token (pairing-only, node-role), upgrade the pairing scope first via `openclaw devices` or rotate the token.
3. Ship a one-time observability check — an SSE heartbeat on `GET /api/v1/gateways/{gateway_id}/activity/stream` — that flags "no frames received in N minutes while gateway reports traffic" as a health regression. This lives in Phase VI alongside the other observability wires.

**Why not auto-heal.** The correct response to a scope regression is an operator action (re-pair, rotate token). Silently retrying or promoting scope would mask misconfiguration. The check surfaces the problem; the operator fixes it.

### D.4 What Part D does not do

- Does not change Phase II's Blocker/Review schemas or endpoints. All three enhancements reuse the existing `Blocker` row shape.
- Does not block Phase III. D.1 and D.2 ride on top of the Phase III operator-decision bridge; D.3 is purely operational.
- Does not require a new `rollout_flags` key. Both D.1 and D.2 gate on `structured_blockers_v1`, which is already in the allowlist.
- Does not alter the §I1 invariant (*"no blocked work without a blocker object"*) — it mechanizes the invariant in two new sources rather than changing its statement.

### D.5 Sequencing

1. Complete Phase III (operator-decision bridge) before D.1 or D.2. Their auto-filed rows interact with the operator-decision routing layer.
2. Land D.3 operational check as a standalone commit during Phase IV or V prep, tied to the next gateway upgrade.
3. D.1 + D.2 ship together in Phase VI, gated per-board by `structured_blockers_v1`. Graduate the Dev Squad board first for one week of shadow data before widening.

## Part E — OpenClaw 2026.4.21 / 4.22 integration addenda (2026-04-23)

**Context.** Prod upgraded from 2026.4.14 straight to 2026.4.22 on 2026-04-23. An audit covering the four stable releases in the window (4.15, 4.20, 4.21, 4.22) reviewed every Changes + Fixes entry against MC code. Prior work that had already landed is marked below; new items are Part E.

### E.0 Audit outcomes on prior items

- **Part C.1 `models.authStatus` forensic-log + alert gate** — *still unimplemented.* The method is absent from ``GATEWAY_METHODS`` in ``app/services/openclaw/gateway_rpc.py`` and the heartbeat watchdog at ``app/services/openclaw/heartbeat_watchdog.py`` never invokes it. See E.1 for the scoped follow-through.
- **Part D.1 subagent-failure → Blocker** — *shipped.* Service at ``app/services/subagent_failure_blocker.py`` + agent self-report endpoint ``POST /api/v1/agent/boards/{board_id}/tasks/{task_id}/subagent-failure`` (commit ``3c363e68``). Parent agents can ingest today without waiting on a gateway-push channel; when 4.22's push channel lands, both paths share the same filer + dedupe index.
- **Part D.2 stale-agent-session → operator Blocker** — *shipped.* Wired in ``_notify_agent_on_task_assign`` and ``_notify_agent_on_task_rework`` on the dispatch-failure branch. Citation goes through ``redact_gateway_error_message`` so token-bearing substrings (``?token=<shared>``, bearer headers, JWTs) never reach the operator-facing Blocker row.
- **Part D.3 WS scope verification** — *shipped (no-op for this deployment).* MC uses a shared-secret operator token with device-pairing disabled, so the 4.20 broadcast narrowing doesn't affect us. Step 3's frame-age observability check is **deferred / superseded**: MC has no live gateway subscription today (``sessions.subscribe`` is in the method list but has zero callers), so there's no frame stream to monitor. Re-activate if and when MC adopts a gateway-pushed activity stream (currently covered by the agent-self-report path in D.1).
- **Token redactor** — *shipped.* ``redact_gateway_error_message`` strips ``token=`` / ``access_token=`` / ``authorization:`` key-value / JWT shapes from gateway error messages before they persist. Consumed at D.2's citation builder.

### E.1 `models.authStatus` forensic-log integration (formerly C.1, now scoped)

**Rationale.** 4.15 added ``models.authStatus`` (stripped, 60s-cached) to give operators per-provider OAuth-token and rate-limit-pressure visibility without exposing credentials. §C.1 of the amendments doc called for capturing this on each watchdog repair row AND using it to suppress the "3× repairs in 1h" operator-alert when the provider was independently degraded. The method signature + call shape are now stable; this is the straightforward landing.

**Amendment.**

1. Add ``"models.authStatus"`` to ``GATEWAY_METHODS`` in ``app/services/openclaw/gateway_rpc.py`` and a thin ``models_auth_status(config)`` helper matching the other ``openclaw_*`` helpers.
2. Extend ``AgentHeartbeatRepairEvent`` with a JSON column ``auth_status_snapshot: dict | None``, migration-only (prod column already exists as JSON elsewhere; reuse that pattern).
3. In ``heartbeat_watchdog.py`` at the repair path, best-effort call ``models_auth_status`` before inserting the event row. Network failure / method-not-supported must NOT block the repair — wrap in try/except and store ``None`` on failure. Cache the snapshot per-sweep so a wave of repairs in the same tick reuses one call.
4. Alert-gate extension: the "3× repair / 1h" alarm is suppressed when any snapshot in the window reports ``degraded=true`` or ``expiring=true`` for the affected provider. The repair rows still persist — operators can still see them — only the page is gated.

**Gate.** Requires gateway 4.15+; the method exists across 4.15 → 4.22. On older gateways, the best-effort call degrades to ``None`` via the existing unknown-method pathway.

**Bounds.** Do NOT use the snapshot for gating OTHER alerts (heartbeat-deadline-missed, stale-agent-session filing, etc.). The one-specific gate is "repeated-repair spam during provider degradation"; broadening it risks masking real bugs behind transient auth issues.

### E.2 Parse ``Runner:`` field from ``status`` RPC (4.22) — **CANCELLED 2026-04-23**

**Original rationale.** 4.22 `#70595` was read as adding a ``Runner:`` field to the ``status`` RPC response reporting ``embedded | cli | acp``.

**Why cancelled.** Inspecting the PR (`openclaw/openclaw#70595`, files: ``CHANGELOG.md``, ``src/auto-reply/status.test.ts``, ``src/status/status-message.ts``) showed the change only touches the chat-rendered ``/status`` command output — a human-readable label in a chat message, NOT a structured field on any RPC response (``status``, ``sessions.list``, ``sessions.preview`` all confirmed empty of ``runner`` on a live 4.22 gateway probe). MC has no hook to a chat-formatted label; parsing the human-readable string back into a structured column would be fragile and gives nothing the existing ``config.get`` agent listing doesn't already imply.

### E.3 Use server-side ``sessions.list`` filters (4.22) — **RE-OPENED 2026-04-23 (codex correction)**

**Original rationale.** 4.22 `#69839` was read as adding ``label`` / ``agent`` / ``search`` server-side filter params to the ``sessions.list`` gateway RPC.

**First cancellation (WITHDRAWN).** I originally cancelled E.3 after seeing the PR #69839 file list only under ``src/agents/tools/``. Codex gpt-5.5/high review on 2026-04-23 caught the error: the gateway RPC schema at ``src/gateway/protocol/schema/sessions.ts``'s ``SessionsListParamsSchema`` explicitly accepts ``label``, ``agentId``, ``search``, ``spawnedBy`` as ``Type.Optional`` params. The RPC absolutely was updated — PR #69839 changed the agent-tool wrapper AS WELL, but the underlying schema / handler in ``src/gateway/server-methods/sessions.ts`` validates and forwards these params.

**Amendment.** MC's ``session_service.py`` currently fetches the full list via ``openclaw_call("sessions.list", None, config=cfg)`` and filters client-side. Switch to server-side filtering by passing the params dict. Priority stays L — Dev Squad session volume doesn't need it today — but it's real integration work, not a ghost PR.

**Lesson for future audits.** Checking the PR file list is necessary but not sufficient — a single PR can touch multiple surfaces, and the upstream schema ``.ts`` file may be in a separate path the PR didn't directly modify. The durable check is: grep the upstream gateway RPC schema for the new param names BEFORE scoring the integration as "not on the MC surface".

### E.4 Promote ``request_id`` from ``PAIRING_REQUIRED`` into structured Blocker field

**Rationale.** 4.20 `#69227` added reason-specific remediation hints + ``request_id`` to ``PAIRING_REQUIRED`` responses. D.2's ``_citation_for`` preserves the raw (redacted) message but the 512-char cap can clip the ``request_id``. Operators need that id to cross-reference gateway logs when triaging a stuck agent.

**Amendment.** Parse ``request_id`` out of the remediation JSON (when present) and stamp it on a new ``Blocker.citation_request_id: str | None`` column. Keep the free-form citation for the rest of the message. Priority M — operator triage quality.

### E.5 Post-upgrade operational smoke test: ``config.patch`` operator-auth

**Rationale.** 4.20 `#69377` tightened the gateway's ``config.patch`` / ``config.apply`` guard to reject model/agent-driven mutations of operator-trusted paths. MC's Sync Templates + agent-create paths call ``config.patch`` from the operator-token context — should be fine, but verify on each major upgrade that the operator-path hasn't accidentally been bound through a narrower scope.

**Amendment.** Operational check, not code:
1. After any gateway upgrade past 4.20, run one ``POST /api/v1/gateways/{id}/templates/sync`` and confirm ``agents_updated`` comes back non-zero with ``errors: []``.
2. Create a throwaway test agent via the provisioning API and confirm the agents.create RPC path returns success (not a scope-denied 403).
3. Red flag: sync returns ``errors`` containing ``permission_denied`` / ``scope_insufficient``. Action: re-check operator token provenance; do NOT downgrade the gateway's guard.

### E.6 What Part E does not do

- Does not change Phase II / III / IV / V / VI / Part D schemas or endpoints. E.1 adds one JSON column; E.4 adds one nullable text column. All other items are runtime-only.
- Does not require new rollout flags. E.1's alert-gate is always-on (best-effort — the provider-degraded short-circuit is non-invasive); E.2/E.3 are pure-read integrations.
- Does not alter any §I invariant.

### E.7 Sequencing

1. Land E.1 first — highest-value safety. Watchdog-repair rows immediately carry authStatus snapshot for operator triage; alert-gate lands with it.
2. E.4 next (M) — small column + parse; paves the Blocker dashboard for the next dispatch-failure wave.
3. ~~E.2, E.3 batched later (L) — pure observability / perf.~~ **Both cancelled 2026-04-23** after the underlying PRs were confirmed to touch non-MC surfaces (chat-message label and agent-tool respectively). See E.2 / E.3 subsections for the investigation trail.
4. E.5 runs on every upgrade past 4.20; not a code commit.

### E.8 Status snapshot (2026-04-23)

| Item | Priority | Status |
|---|---|---|
| E.1a authStatus capture on repair rows | M | shipped (``13314e4b``) |
| E.1b authStatus-based alert-gate suppression | M | deferred — needs real snapshot samples from prod before the predicate can be tuned |
| E.2 ``Runner:`` field parse | L | **cancelled** (chat-label only, not RPC) |
| E.3 server-side ``sessions.list`` filters | L | **re-opened 2026-04-23** — codex review confirmed gateway RPC schema accepts ``label``/``agentId``/``search``/``spawnedBy``; implementation deferred |
| E.4 Blocker ``citation_request_id`` | M | shipped (``780982a6``) |
| E.5 ``config.patch`` operator-auth smoke test | ops | ready per upgrade; one curl |

**Lesson for future changelog audits.** When a changelog entry mentions a feature added to ``/command``, ``$tool``, or ``src/agents/*``, resolve the PR file list BEFORE scoring MC integration priority. Chat-command surfaces, agent tools, and gateway RPCs are three different wire contracts. The audit that produced Part E pre-cancellation conflated them.

**Follow-up correction (2026-04-23):** the above lesson was right but incomplete. Codex gpt-5.5/high review of the cancellations caught that PR #69839 touched BOTH the agent tool AND the gateway RPC schema (separate file paths). A single PR file list can be misleading when the schema ``.ts`` file is updated in a parallel path the PR didn't include explicitly. Harden the audit by also grepping the upstream gateway protocol schema (``src/gateway/protocol/schema/*.ts``) for the new param names BEFORE concluding "not on the MC surface". This is what caused the premature E.3 cancellation. E.3 has been re-opened.

### E.9 Implementation corrections from codex review (2026-04-23)

Two corrections applied to already-shipped code after a gpt-5.5/high review:

**E.1a watchdog RPC timeout.** Codex caught that ``openclaw_call`` has no end-to-end response timeout after connect+send (the 2s ``wait_for`` at ``gateway_rpc.py:486`` only covers the connect-handshake read). A hung or slow gateway could stall the 60s watchdog sweep indefinitely. Wrapped each per-gateway ``models_auth_status`` call in ``asyncio.wait_for`` with a 5s cap; timeout maps to ``None`` snapshot, repair still persists. New regression test ``test_auth_status_fetch_timeout_survives_to_null`` locks the behaviour.

**E.4 request_id surface.** Codex caught that parsing the human-readable error message is the wrong surface. The gateway's ``PairingConnectErrorDetails`` at ``src/gateway/protocol/connect-error-details.ts`` carries structured ``requestId`` / ``reason`` / ``code`` fields, and MC was discarding everything except ``.message`` at ``gateway_rpc.py:380``. Extended ``OpenClawGatewayError`` with an optional ``details`` dict populated from ``data["error"]`` + ``.request_id`` / ``.code`` property accessors. New ``request_id_from_exc()`` helper in ``stale_agent_blocker.py`` prefers the structured field with regex fallback for pre-4.20 gateways. Four new regression tests cover structured-preference, regex-fallback, absent-in-both, and the ship-case where a citation's structured id wins over a different id in the message text.
