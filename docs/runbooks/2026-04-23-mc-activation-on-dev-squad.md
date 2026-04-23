# MC Activation Runbook — Dev Squad (2026-04-23)

Applies after the Phase 0 → VI + Part D + ultrareview fixes ship (commit
`670d76f4` onward). Walks the operator through (A) stabilise, (B) graduate rollout flags,
(C) close the Architect↔Supervisor echo loop.

The delivery-contract gate is **always-on** (not flag-gated). Any task transition
into `in_progress` / `review` / `done` now requires the contract fields to be
populated. Skipping Section A will cause the first real workflow to 409.

## Constants

| Key | Value |
|---|---|
| MC base | `http://192.168.2.64:8000` |
| Board (Dev Squad) | `05002170-201b-4c66-bae1-26c0c833f206` |
| Gateway | `3821a85a-984c-412a-9340-cda50eaf174e` (OpenClaw Primary) |
| Auth header | `X-Operator-Token: <token>` (see gateway `TOOLS.md`) |

## Section A — Stabilise before any flag graduation

### A.1 Sync templates to the gateway

Deployed templates in `backend/templates/` reach agent workspaces only after
this call. Without it, the agents run on pre-upgrade copies.

```bash
curl -fsS -X POST \
  "$BASE_URL/api/v1/gateways/3821a85a-984c-412a-9340-cda50eaf174e/templates/sync" \
  -H "X-Operator-Token: $OP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Verify on `.64`:

```bash
ssh root@192.168.2.64 "grep -c 'Know When to Speak' \
  /root/.openclaw/workspaces/*/BOARD_AGENTS.md"
```

Each agent workspace should show `≥1`. Agents running on the previous template
show `0`.

### A.2 Find tasks missing the delivery-contract fields

```sql
SELECT id, title, status,
       (review_packet_type IS NULL) AS no_packet_type,
       (assigned_agent_id  IS NULL) AS no_owner,
       (validation_target  IS NULL) AS no_target,
       (packet_commit_sha  IS NULL) AS no_sha
FROM tasks
WHERE board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND status IN ('inbox','in_progress','review','rework')
ORDER BY status, updated_at DESC;
```

Prod snapshot (2026-04-23) showed **9 inbox / 3 in_progress / 2 review / 3 rework**
with 7+1+1 lacking `review_packet_type` and 8 inbox lacking an owner.

### A.3 Backfill — per task

Prefer PATCH via the admin API (audit trail, hook-point-aware) over raw SQL
(fast but bypasses every gate). Only fall back to SQL if the admin API is
failing.

Admin PATCH (operator token):

```bash
curl -fsS -X PATCH \
  "$BASE_URL/api/v1/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "X-Operator-Token: $OP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "review_packet_type": "review_only",
    "assigned_agent_id": "<uuid-of-owner>",
    "validation_target": "http://192.168.2.60:3000",
    "validation_target_kind": "live_url",
    "validation_target_scope": "review"
  }'
```

Notes:
- `review_packet_type="review_only"` and `"other"` do NOT require a
  `validation_target` triplet; choose those for tasks without a reviewable
  artifact.
- `frontend_ui` / `backend_api` / `infra_ops` / `mixed` require the
  validation-target triplet.
- `packet_commit_sha` is only required once `deploy_truth_v1` is enabled
  (Section B.5); skip for now.

SQL fallback (operator-only, bypasses the gate — use for bulk backfill where
you're confident):

```sql
UPDATE tasks
SET review_packet_type = 'review_only'
WHERE board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND status IN ('inbox','review','rework')
  AND review_packet_type IS NULL;
```

### A.4 Verify stabilisation

Re-run A.2. Expected: zero rows where the current status requires that field.

- `inbox` → `review_packet_type` required (before `in_progress` claim)
- `in_progress` / `done` → owner required
- `review` / `done` → `packet_commit_sha` required (only once `deploy_truth_v1`
  is on)

## Section B — Graduate rollout flags (one per day, watch shadow metrics)

All six flags default OFF on Dev Squad (verified at activation). Graduate one
per day and read the shadow-metric emission between each. Rollback is free:
toggle the flag off.

### B.1 comment_policy_v1 (Phase 0/I) — safest first

Enables the comment classifier shadow-mode. Observable via
`shadow_metric_events` rows with
`event_type='comment.ack_only_candidate'` or `comment.near_duplicate_candidate`.
No enforcement.

```bash
curl -fsS -X PATCH \
  "$BASE_URL/api/v1/boards/$BOARD_ID" \
  -H "X-Operator-Token: $OP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"rollout_flags": {"comment_policy_v1": true}}'
```

Watch:

```sql
SELECT event_type, count(*)
FROM shadow_metric_events
WHERE board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND created_at > now() - interval '24 hour'
GROUP BY event_type
ORDER BY event_type;
```

### B.2 heartbeat_watchdog_v1 (Phase 0 §A.1)

Forensic log of watchdog repairs in `agent_heartbeat_repair_events`. No
enforcement change; fixes a missing-deadline race if it re-occurs.

```bash
curl -fsS -X PATCH "$BASE_URL/api/v1/boards/$BOARD_ID" \
  -H "X-Operator-Token: $OP_TOKEN" -H "Content-Type: application/json" \
  -d '{"rollout_flags": {"comment_policy_v1": true, "heartbeat_watchdog_v1": true}}'
```

(`rollout_flags` PATCH is merged on the server — no need to resend prior keys,
but resending keeps the intended state explicit.)

### B.3 structured_blockers_v1 (Phase II + Part D)

Activates:
- `§I6` lane quieting — non-owner comments on a task with an acknowledged open
  Blocker get rejected (403).
- `D.1` auto-file Blocker from subagent-failure payloads (currently not wired
  — safe to enable).
- `D.2` auto-file operator Blocker on stale-agent-session dispatch error. If
  any dispatch currently 500s on a known gateway error, you will see new rows
  in `blockers` with `category='operator'`.

Expect a triage spike — legitimate stuck states materialise as structured rows
for the first time.

### B.4 operator_decisions_v1 (Phase III)

Bridges pending `operator_decisions` rows into `task.is_blocked`. Today the
Dev Squad board has **0 pending decisions**; the flag is a no-op until someone
files one via `POST /api/v1/boards/{board_id}/operator-decisions`.

### B.5 deploy_truth_v1 (Phase V §I8)

**Only after A.3 backfills `packet_commit_sha` on every review/rework task.**
`review` / `done` transitions now fetch `{validation_target}/__build`,
compare the returned SHA with `packet_commit_sha`, and reject on mismatch.

Pre-check before enabling:

```sql
SELECT count(*) FROM tasks
WHERE board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND status IN ('review','rework')
  AND packet_commit_sha IS NULL;
```

Must be `0`. Enable:

```bash
curl -fsS -X PATCH "$BASE_URL/api/v1/boards/$BOARD_ID" \
  -H "X-Operator-Token: $OP_TOKEN" -H "Content-Type: application/json" \
  -d '{"rollout_flags": {"deploy_truth_v1": true}}'
```

SSRF guard on `validation_target` is always-on (Phase V hardening) — blocks
loopback, link-local, and cloud-metadata hostnames. RFC1918 (private LAN) is
allowed.

### B.6 lead_scoring_v1 (Phase VI §I5)

Lead-heartbeat no-op scoring. After two consecutive sweeps where the lead
produced zero real actions (no Blocker, no task mutation), fires
`supervisor.heartbeat_noop_streak_alert`. Sweep runs every 300s. First scoring
writes a bootstrap marker — streak alerts do not fire on the first sweep after
enablement.

## Section C — Close the Architect↔Supervisor echo loop

See `docs/plans/…` TBD (Phase VII comment-echo write gate) for the backend
implementation plan. The short version:

1. Template rewrite of `backend/templates/BOARD_AGENTS.md.j2` §"Know When to
   Speak" — replace the abstract "filler" example with a hard pre-post
   checklist that requires delta vs the agent's **own last same-task comment**
   (not vs "board truth" — models will otherwise re-invoke an existing
   blocker name every time).
2. Backend write gate combining three signals (near-duplicate jaccard ≥0.9
   within 300s **OR** extended ack-shape **OR** no-state-delta since prior
   same-author comment). Enforcement gated by a new rollout flag
   `comment_echo_guard_v1`.

Do not graduate the existing `comment.ack_only_candidate` classifier into
enforcement alone — codex verified (2026-04-23) that the Architect sample in
the 2026-04-17 22:30 storm does not match the current `ack_only` regex (leads
with `@mention`, "holding X on that exact truth" is not an ack-phrase). Only
the Supervisor half would get caught; the loop would continue half-amplitude.

## Verification at steady state (run daily)

```sql
-- 24h comment volume per agent on Dev Squad
SELECT a.name, count(*) AS comments
FROM activity_events e
JOIN agents a ON a.id = e.agent_id
WHERE e.board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND e.event_type = 'task.comment'
  AND e.created_at > now() - interval '24 hour'
GROUP BY a.name
ORDER BY comments DESC;

-- 24h shadow-metric counts
SELECT event_type, count(*)
FROM shadow_metric_events
WHERE board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND created_at > now() - interval '24 hour'
GROUP BY event_type
ORDER BY 2 DESC;

-- Open blockers triage
SELECT b.id, b.category, b.owner_role, b.required_artifact, t.title, t.status
FROM blockers b
JOIN tasks t ON t.id = b.task_id
WHERE b.board_id = '05002170-201b-4c66-bae1-26c0c833f206'
  AND b.resolved_at IS NULL
ORDER BY b.created_at DESC;
```

Red flags:
- Any agent > 200 comments / 24h → echo-loop recurrence; escalate to Section C
- `comment.near_duplicate_candidate` count > 0 with `comment_echo_guard_v1`
  enabled → the gate is shadow-observing but not rejecting (configuration bug)
- Stale `operator`-category blocker (`created_at` > 24h ago, `acknowledged_at`
  still NULL) → operator intervention needed; not an MC bug

## Rollback

Any single flag can be disabled by PATCHing `rollout_flags` with the key set
to `false`. The gated behaviour reverts to pre-Phase-0 on the next request.
Existing auto-filed Blocker / OperatorDecision rows persist (they are the
audit trail); the derivation stops consulting them.
