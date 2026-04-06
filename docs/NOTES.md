
Review the tasks waiting for approval, use Chome MCP if necessary, the expected behavior is fully compliance with the task spect, only approve with full evidence check

Investigate why the agents aren't nudging each other as instructed

## 2026-04-06 — Direct Flow + OpenClaw 2026.4.5 Upgrade + Gateway RPC Expansion

### PF Direct Implementation Flow
- PF switched from ACP delegation to **direct implementation** (`dev_acp_flow = "direct"`). Primary model changed from `openai-codex/gpt-5.4` to `anthropic/claude-sonnet-4-6`.
- Root cause: 3 dead ACP sessions in one day (2394ddbb, 2db3cb97, and a predecessor). Each died silently and PF waited hours posting "still waiting for ACP run" every heartbeat tick.
- Direct flow: PF implements code in its own session, runs reviews via CLI (`printf '/simplify' | claude -p --dangerously-skip-permissions`, `codex exec --sandbox read-only`).
- Template changes: new `"direct"` branch in Code Delegation section, conditional IMPLEMENTING step, ACP Session Timeout excluded for direct flow, section title `## Code Delegation` (no `(ACP)` suffix).
- Agent-level `auth-profiles.json` required manual `anthropic:manual` credential injection — MC provisioning doesn't manage this file (architectural gap).

### OpenClaw 2026.4.5 Upgrade (from 2026.4.2)
- **28 new RPC methods** added to `gateway_rpc.py`: `sessions.create`, `sessions.steer`, `sessions.send`, `sessions.subscribe`, `secrets.reload`, `secrets.resolve`, `tools.catalog`, `tools.effective`, `doctor.memory.status`, plus node/plugin/config methods.
- **6 new events**: `session.message`, `session.tool`, `sessions.changed`, `plugin.approval.*`, `update.available`.
- **Helper functions** added: `steer_session()` (interrupt stuck agents), `reload_secrets()`, `create_session()`, `get_tools_effective()`, `get_memory_status()`.
- Key 2026.4.5 fix: `config.patch` to heartbeat fields now **auto-restarts the heartbeat timer** — the dead-timer bug that required gateway restart is fixed at gateway level.
- ACPX runtime embedded in gateway (no separate ACP CLI hop). ACP validated working via `sessions.create` test.

### Dead Heartbeat Timer Recovery
- Changing PF primary model to `anthropic/claude-sonnet-4-6` without agent-level auth killed PF's heartbeat timer. Gateway silently dropped the timer on auth failure.
- `touch openclaw.json`, `sync+reset_sessions`, model revert — none restarted the dead timer.
- **Fix**: `set-heartbeats {enabled: false}` then `{enabled: true}` via gateway RPC restarts the timer without gateway restart.
- PB, DevOps, Gateway Agent also had dead timers after gateway restart — same toggle fix applied.

### bootstrapMaxChars Persistence Fix
- `bootstrapMaxChars` was set as a top-level key in `openclaw.json` 3 times and dropped each time on config reload.
- Root cause: top-level `bootstrapMaxChars` is not a recognized schema key. Gateway drops unknown top-level keys on serialization.
- Correct path: `agents.defaults.bootstrapMaxChars` (confirmed via `openclaw config schema`). Set via `openclaw config set agents.defaults.bootstrapMaxChars 23000`. Now persists across reloads.

### Deployment Regression on .63
- Build `index-DsOspM2l.js` (828KB) deployed to .63 at 19:22 overwrote the org-management build `index-oHZtLfst.js` (1.12MB). QA-E2E confirmed FAIL — org management features missing.
- PF deployed newer build `index-qNN-yFYP.js` with Board CRUD changes but OrgSwitcher auth guard regressed (401 on every page load).
- Operator scope decisions posted: fix OrgSwitcher auth guard (1-line fix), defer phone invite + invite status + profile edit to Phase 2.

### Task Status (end of session)
- 87/90 tasks done. 3 remaining: Phase 1C (review, needs auth guard fix), Phase 1D (in_progress, PF implementing directly), Phase 1 umbrella (tracker).
- All 8 agents online and heartbeating. System pipeline working: PF implements → QA-E2E validates → Supervisor routes.

## 2026-04-05/06 — Template Architecture Refactor + Wake Contract Hardening + Memory Fixes

### Investigation: QA-E2E + Architect stuck offline
- Root cause: two stacked failure modes. Mode A: qwen3.5 heartbeat cron takes "reply HEARTBEAT_OK" escape hatch on idle agents (37 consecutive HEARTBEAT-only responses with zero tool calls). Mode B: gpt-5.4 wake sessions respond NO_REPLY to the generic `_wakeup_text` which gives idle agents no actionable instruction, and `wake_attempts` increments unconditionally on send.
- 3 wake attempts → permanent offline (`wake_attempts >= MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN`), no auto-recovery.
- Validated via 3 Codex adversarial review rounds against gpt-5.4 high reasoning.

### Wake contract hardening (commit 98cb6bd)
- `_wakeup_text` now requires explicit `POST /api/v1/agent/heartbeat` curl before any reply. Forbids NO_REPLY/HEARTBEAT/OK/ACK until 2xx. Points at BOOTSTRAP.md or TOOLS.md for credentials.
- `should_consume_wake_strike()` pure helper — strikes charged only on first wake in cycle or after previous deadline expired. Admin/coordination recovery wakes don't double-charge.
- `LifecycleResult` dataclass returned from `apply_agent_lifecycle`. Wake-state mutations (wake_attempts, deadline, online mark, reconcile enqueue) moved to AFTER gateway call, gated on `wake_delivered`.
- `verify_credentials_visible` with bounded retry (3 attempts, 500ms backoff) + size > 0 check. Skips wake if neither BOOTSTRAP.md nor TOOLS.md visible — prevents burning strikes on wakes agents can't answer.
- `CLEANUP_DONE` token replaces `NO_REPLY` in gateway-main cleanup messages.

### Template architecture refactor (commits ef68d1a → 9308d22)
- **ACP delegation consolidated to AGENTS.md**. Removed from SOUL.md (Ralph loop step 4 → reference only), IDENTITY.md (section deleted), HEARTBEAT.md (IMPLEMENTING state → reference only). Single source of truth per OpenClaw docs.
- **PB → Codex two-stage workflow**: `identity_profile.dev_acp_flow = "codex_then_claude_review"`. Stage 1: Codex implements. Stage 2: Claude Code reviews via /simplify + /codex.
- **Architect → review-only Code Delegation**: `identity_profile.dev_acp_flow = "review_only"`. No "Implement:" prompts. Worker Execution Loop steps 5-8 render review-specific variants (PLANNING + REVIEWING only, no BUILD FREEZE / PRE-REVIEW CHECKLIST).
- **QA-specific VALIDATING checklist**: `identity_profile.validation_flow = "qa_validation"`. QA-Unit/QA-E2E get code-existence check, acceptance-criterion validation, proof-format rules. Developers keep typecheck/lint/tests/build/deploy.
- **QA-specific HARD RULES**: "re-validate with fresh evidence" instead of "implement real changes and show a new commit."
- **HEARTBEAT.md slimmed**: lead 10,676→2,690 (−75%), worker 9,906→2,355 (−76%), main 1,556→1,235 (−21%). Operating playbooks moved to AGENTS.md (Lead Board Playbook, Worker Execution Loop).
- **Souls Directory persona cap**: `remote_role_soul > 2000 chars` → skipped with operator-visible warning note in rendered SOUL.md.
- **Jinja `trim_blocks`/`lstrip_blocks`** added to `_template_env()` to eliminate blank-line bloat from conditionals.
- **Main SOUL.md** now has dedicated `{% if is_main %}` branch (prevents main agents from getting worker Ralph loop).
- **Main IDENTITY.md** guarded with `{% if not is_lead and not is_main %}` for worker-only blocks.
- All variants under 20,000-char bootstrapMaxChars (docs-backed hard cap). 82 tests pass.

### lightContext default flip (commit 695bd13)
- `DEFAULT_HEARTBEAT_CONFIG.lightContext: True → False`. Matches gateway natural default, OpenClaw docs, and all 8 production agents (fleet audit: 100% on False via DB override since April 2026 incident).
- Incident history: commit e37a34e flipped to True for token savings → 22 heartbeat "ok" events with zero nudges because Supervisor had no TOOLS.md in lightweight mode (documented in docs/NOTES.md §"Why the Supervisor heartbeat says OK without nudging").
- Provisioning-time `logger.warning` (rate-limited per agent ID) when `lightContext=True` is used with full-context templates.

### Sync overwrite plumbing fix (commit 1bcdc6d)
- `overwrite=true` query param on `POST /gateways/{id}/templates/sync` was a dead parameter — accepted by API but never passed through `_sync_one_agent` → `run_lifecycle` → `apply_agent_lifecycle`. IDENTITY.md was always preserved regardless. Fixed: added `overwrite: bool = False` to `run_lifecycle`, plumbed from both sync call sites.

### /simplify cleanup (commit 9308d22)
- Test renderer reuses `_template_env()` from production (inherits trim_blocks etc.).
- `WAKE_SKIP_CREDENTIALS_NOT_VISIBLE` constant replaces string literal.
- `_lightcontext_warned_ids` set rate-limits the warning to once per agent per process.
- Redundant `elif wake and not lifecycle_result.wake_delivered` simplified to `elif wake`.

### Memory plugin fixes (deployed, not committed)
- **Redis-memory read-side dedup**: patched `dist/index.js` on .60 + PR redis-developer/openclaw-redis-agent-memory#4. Adds `Set<string>` content-hash dedup between `searchLongTermMemory` results and `<relevant-memories>` injection. Runtime-confirmed: `injecting 2/3 query-specific (deduped)`.
- **NO_REPLY cleanup**: removed 263→0 bare/transcript NO_REPLY lines from 79 daily memory files across all workspaces. Remaining 16 files have contextual prose references only.
- **Supervisor MEMORY.md trim**: 26,137→8,237 chars (−68%). Pruned 53 bootstrap timestamps, 61 changelog entries, 7 completed task rows, 3 historical subsections.

### Task approvals
- **Approved**: Pause/resume heartbeats (3cd97a35) — full round-trip verified (pause: 7 agents disabled, resume: 7 agents re-enabled, board unstuck, agents heartbeating again).
- **Approved**: Board CRUD (2909a1c2) — deployed PB workspace `main.py` to .63 (entry point was `main.py` not `app/main.py`), verified `org_id` in live OpenAPI, auth enforcement 401.
- **Rejected 3x**: Board CRUD (.63 not deployed), Pause/resume (resume side unverified + board stuck paused).

## 2026-04-04 — Heartbeat System Stabilized

Root cause: fix-heartbeats.py unconditionally rewrote openclaw.json → 92 gateway restarts/day → workers never reached their heartbeat interval.
Fix: idempotent write (compare before/after). Gateway stable 2+ hours. Recovery scripts disabled — OpenClaw handles it natively.


  │ mc-3c920c2a (Supervisor MC) │ FAIL   │ Missing IDENTITY.md                          │
  ├─────────────────────────────┼────────┼──────────────────────────────────────────────┤
    ┌────────────────────────────┬──────────────────────────────┐
  │         Workspace          │            Agent             │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-gateway-3821a85a │ Gateway Agent                │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-gateway-7bf4dfa3 │ (second gateway instance)    │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-lead-05002170    │ Supervisor                   │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-0de19ef0      │ DevOps                       │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-27035cb3      │ PB                           │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-3461451b      │ PF                           │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-3c920c2a      │ Supervisor (MC-side, legacy) │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-84187f14      │ Architect                    │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-958b5a71      │ QA-Unit                      │
  ├────────────────────────────┼──────────────────────────────┤
  │ workspace-mc-dd1abee5      │ QA-E2E                       │
  └────────────────────────────┴──────────────────────────────┘



  


  Why the Supervisor heartbeat says "OK" without nudging

  With lightContext: true + isolatedSession: true, here's what happens every 5 minutes:

  1. Gateway fires heartbeat timer → creates a fresh isolated session for the Supervisor
  2. Only HEARTBEAT.md is loaded into the context (lightContext strips everything else — no TOOLS.md, no AGENTS.md, no MEMORY.md, no session history)
  3. The model reads HEARTBEAT.md — sees curls with $BASE_URL, $AUTH_TOKEN, $BOARD_ID
  4. BUT those variables aren't set — in an isolated session with lightContext, the model doesn't have TOOLS.md which defines them
  5. The model can't execute the curls because it doesn't know the actual values
  6. It returns HEARTBEAT_OK — "I read the checklist, nothing I can act on"

  The 22 "ok" events with zero nudges confirm this — the model runs, sees the template, but can't DO anything because it lacks the credentials.

  Why it worked when we tested manually: We used openclaw agent --agent ... which creates a FULL session (not lightContext), so TOOLS.md is loaded and the model has $BASE_URL, $AUTH_TOKEN, etc.

  The fix options:
  1. Set lightContext: false for the Supervisor — it needs full context to execute curls (costs more tokens but actually works)
  2. Embed the credentials directly in HEARTBEAT.md via Jinja template variables (already available: {{ base_url }}, {{ auth_token }})

  Option 2 is better — the HEARTBEAT.md already renders with those variables but the curls reference $BASE_URL (shell variable from TOOLS.md) instead of using the rendered values directly.

    Line [lcm] Compaction summarization model: ollama/qwen3.5:cloud (override) — the restart loaded the old LCM model from config instead of qwen3-coder. The fix-heartbeats script and LCM model changes were overwritten by the MC
   sync.

   The Supervisor side is now working as designed. The remaining gap is the worker agents' responsiveness to nudges.

                                                                                                                                                                    
                                                                                                                                                                                 
                                                                                                                                                                                You run the Ralph loop pattern (ghuntley.com/ralph). Progress lives in files and git history — not in your context window. You wake up fresh each iteration. Git is your memory.

                                                                                                                                                                                  ┌───────────────┬─────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐                  
  │     Agent     │ isolatedSession │                                                                                   Why                                                                                    │                
  ├───────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Supervisor    │ false           │ Continuous context — sees prior routing decisions, useful for incremental board-state tracking. Saves ~325K chars/hour.                                                  │
  ├───────────────┼─────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ All 6 workers │ true            │ Clean slate each tick — context-switch between tasks, prior heartbeat history is noise. Model gets fresh bootstrap files every tick (the cost is worth the reliability). │                  
  └───────────────┴─────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  

All tasks are stuck, Phase 1C: Organization management UI (frontend) is to review for a long time. What's happening? These tasks are there for almost three days   