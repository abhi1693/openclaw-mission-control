# Blocker reason_code: enforcement follow-up

Status: planned (column landed 2026-04-30, alembic `f2b3c4d5e6a7`).
Author: operator + Claude Opus 4.7 session.

## What shipped on 2026-04-30

Alembic `f2b3c4d5e6a7` added a nullable `reason_code VARCHAR(64)` column
to both `blockers` and `operator_decisions`. Open vocabulary, no CHECK
constraint, no backfill. Pre-existing rows have `NULL`.

The new field flows through:

- `BlockerCreate` / `BlockerRead` / `BlockerBase` schemas
- `OperatorDecisionCreate` / `OperatorDecisionRead` / `OperatorDecisionUpdate`
  schemas (update path included so a sharper code can be patched onto a
  pending decision)
- `ReviewBlockerDescriptor` schema (so reviewers filing a FAIL with
  blockers can stamp the code in the same transaction)
- `POST /boards/{board_id}/tasks/{task_id}/blockers`
- `POST /boards/{board_id}/operator-decisions`
- `PATCH /boards/{board_id}/operator-decisions/{id}`
- `POST /boards/{board_id}/tasks/{task_id}/reviews` (review-emitted blockers)

The `lead-health-scan` skill now contains a "Stale Operator-Blocker
Revalidation" section that reads `reason_code` and either:

- probes the underlying infra (gateway WS, deploy hash) and posts a
  `REVALIDATION_CANDIDATE` comment if healthy, OR
- silently skips when the code is durable (`operator_policy`,
  `requirements_clarification`, `credential_required`) or unknown.

Anti-spam: max 1 `REVALIDATION_CANDIDATE` per task per 12h. The skill
never clears blockers itself — only surfaces candidates.

## Recommended starter codes

Open vocabulary, but readers should treat unknown codes as opaque (no
auto-revalidation logic). The current dispatch in `lead-health-scan`
recognises:

| Code | Auto-revalidatable? | Probe |
|---|---|---|
| `gateway_ws_timeout` | yes | WS handshake against gateway port |
| `deploy_drift` | yes | live build hash vs source-of-truth commit |
| `external_dependency` | nudge only (24h) | none |
| `operator_policy` | no | — (durable human decision) |
| `requirements_clarification` | no | — |
| `credential_required` | no | — |
| `infra_other` | no | — (fallback for ad-hoc infra blockers) |

New codes can be added without a schema migration. Add the
recognise-and-probe rule to `lead-health-scan` before deploying.

## What's NOT enforced yet

The column is currently advisory. No code path requires `reason_code`
to be set when filing a blocker, and unknown values are accepted silently.
The follow-up enforcement work below is intentional separate scope.

## Phase IV-A: enforcement of `reason_code` on infra-class blockers

Goal: when a blocker is filed by an automated agent (not by a human
operator), require a recognised `reason_code`. Operator-filed blockers
remain unconstrained because operators carry context in prose.

Changes:

1. Add a `_validate_agent_filed_reason_code` helper in
   `app/api/blockers.py` that runs only when `actor.actor_type == "agent"`
   and `category in {"runtime", "deploy"}`. Reject 422 with
   `code="blocker_reason_code_required"` if `payload.reason_code` is null
   or not in the recognised set.
2. Same helper for operator-decisions filed by agents.
3. Add a config knob `BLOCKER_REASON_CODE_ENFORCEMENT_MODE` (default
   `advisory`, optionally `strict`) so deploy can roll the gate without
   schema migration.
4. Tests: agent-filed runtime blocker without code returns 422 in strict
   mode; agent-filed in advisory mode passes silently; operator-filed
   passes in both modes.

Rollout window: low-traffic. The change is API-only, no migration.
Pre-check: existing dashboards/agents must be confirmed to send
`reason_code` for agent-filed runtime blockers before flipping the
knob to strict.

## Phase IV-B: structured probe library for revalidation

Goal: replace the inline curl probes in `lead-health-scan` with a
shared probe library so each `reason_code` has one canonical health
check that's exercised by tests.

Changes:

1. New module `app/services/blocker_probes.py` exposing
   `async def probe(reason_code: str, *, board: Board, task: Task) ->
   ProbeResult` returning `{healthy: bool, evidence: str, ts: datetime}`.
2. Per-code implementations:
   - `gateway_ws_timeout` → WS handshake probe (5s timeout).
   - `deploy_drift` → fetch live target, compare loaded build hash to
     `task.packet_commit_sha` artifact map.
   - extensible registry for future codes.
3. New endpoint `POST /boards/{board_id}/blockers/{id}/probe` that runs
   the probe and stores the result on the Blocker as a JSON field
   (requires Phase IV-C migration).
4. The `lead-health-scan` skill calls the endpoint instead of inlining
   curl probes; less LLM-prompt-tax, more deterministic.

## Phase IV-C: probe-result audit column

Optional follow-up. Adds a `last_probe_at` + `last_probe_healthy` +
`last_probe_evidence` set of columns to `blockers` so the operator
dashboard can show "this blocker was probed at 13:42, infra healthy,
no human action yet".

Schema migration size: 3 nullable columns, all additive.

## Why these are deferred

- Phase IV-A: needs a soak window in `advisory` mode to catch agents
  that don't yet stamp `reason_code`. Premature `strict` would 422 the
  current Hero-card-straddle pattern even though those agents are doing
  the right thing structurally.
- Phase IV-B: nice to have but `lead-health-scan` already has working
  inline probes. A shared library is cleanup.
- Phase IV-C: only valuable once a UI consumes the probe history.

## Decision log

- 2026-04-30 chose open-vocabulary string over enum (CHECK constraint
  would force a schema migration to add new codes). Readers handle
  unknown codes as opaque.
- 2026-04-30 chose to make the column nullable rather than backfilling
  existing rows. Backfill would have required prose-parsing the existing
  blocker comments — flaky and out of scope. Readers tolerate `NULL`.
