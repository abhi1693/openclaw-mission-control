# Changelog

All notable changes to the OpenClaw Mission Control fork.

## 2026-03-27

### Fixed
- **Supervisor fake approval guardrail**: Supervisor was posting "Miguel approved. Moving to done." while approval was still PENDING. Added "NEVER approve tasks. Only HUMANS approve. PENDING = WAIT." to lead template.
- **Duplicate task creation guard**: Supervisor created 3 identical MIME-fix tasks in 30 seconds. Added "check /tmp/tasks.json before creating" guard.
- **Orphaned approval flow**: Tasks rejected back to inbox couldn't move to done because API requires `review→done`. Template now PATCHes to `review` first when approval is approved on non-review task.
- **config.patch overwriting gateway settings** (`provisioning.py`): `_updated_agent_list()` now MERGES heartbeat dict instead of replacing — preserves gateway-only fields (model, name). `DEFAULT_HEARTBEAT_CONFIG.lightContext` changed to `False`.
- **QA-E2E posting false PASS**: QA-E2E was grepping JS bundles instead of browser testing, recycling old validation from memory. Added: "MUST use Chrome MCP for ALL UI tasks", "re-validate EVERY time with fresh session", "bundle grep is NEVER valid evidence."

### Changed
- **Model config overhaul** (M2M live testing across all roles):
  - Primary: Sonnet 4.6 for PF/QA-Unit/DevOps/Supervisor, Opus 4.6 for Architect/QA-E2E, gpt-5.4 for PB
  - Heartbeat: Qwen 3.5 for Supervisor (10/10 escalation test), M2.1 for workers (9-10/10, fastest)
  - Fallback chain: Sonnet 4.6 → gpt-5.4 → qwen3.5:cloud → m2.1:cloud
  - Anthropic provider added: direct API (`anthropic-messages`), models: opus-4-6, sonnet-4-6, haiku-4-5
  - M2.5 retired from all roles (worst on all dimensions: 1/10 QA, 8/10 Supervisor, slowest)
- **`lightContext=false` for all agents**: Key fix — Supervisor escalation only worked with full file context. All agents now see TOOLS.md, IDENTITY.md, AGENTS.md in heartbeat sessions.
- **Worker heartbeats: 30m → 60m safety net**: Workers wake via `deliver=True` on task assign/nudge. 60m heartbeat catches orphaned inbox tasks. Supervisor: 5m → 10m.
- **Worker "pick next or idle" (step 8)**: After moving to review, worker checks for more inbox tasks or posts `@lead idle`.
- **`activeHours` 07:00-22:00**: All agents stop heartbeating overnight (America/Fortaleza timezone).
- **Review chain enforcement**: Supervisor must route Architect for code review BEFORE QA (skip for bugfixes/<3 files). Supervisor must reject QA-E2E PASS without Chrome MCP evidence for UI tasks.
- **PF Chrome MCP required**: Frontend workers must use Chrome MCP (navigate, screenshot, console check) before moving UI tasks to review.

### Investigated
- **Heartbeat model comparison** (local E2E tests via Ollama): M2.5 (8/10), M2.1 (9/10, 11s), M2.7 (9/10, 27s), Qwen 3.5 (10/10, 15s), Haiku 4.5 (poor — wrong targets, no escalation). All models perform well locally but fail in production with `lightContext=true` due to missing file context.
- **Execution environment vs model quality**: The "Supervisor discusses but won't execute curls" problem is NOT model-specific — Sonnet 4.6, gpt-5.4, and Qwen 3.5 all exhibit it in production. Root cause: `isolatedSession=true` + `lightContext=true` starves the model of context needed for multi-step curl execution. `lightContext=false` was the fix.

## 2026-03-26

### Fixed
- **Token minting root cause fix** (`lifecycle_orchestrator.py`): `run_lifecycle()` no longer mints a new token on every update/reconcile call. Only mints on first provision (no token hash) or explicit caller token. For updates, reads existing token from TOOLS.md via gateway RPC and reuses it. If gateway unreachable, skips lifecycle entirely (logs error, retries next cycle) instead of minting and creating DB/TOOLS.md mismatch. Verifies reused token against DB hash and resyncs if mismatched. Uses lazy imports to avoid circular dependency. This was the #1 infrastructure problem — caused 5-6 agent lockouts per day.
- **Multiple RQ workers** cleaned up: 4 stale workers were running simultaneously with old code. Killed all, started one clean worker with the fix.

### Changed
- **HEARTBEAT template rewrite (Plan Task 2)**: Complete rewrite from 19KB to 9.5KB lead / 7.4KB worker. Three review rounds (self + Codex + Claude Code agent) caught and fixed 19 issues. Key improvements: comments-fetch curl for QA evidence discovery (was missing — root cause of Supervisor not acting on QA FAIL), approval-fetch with pending/approved filter, `APPROVAL_ID` captured via bash substitution, `{% else %}` branch for no-approval boards, QA agent IDs + idle flags extracted in health scan Python, Supervisor assigns review task to QA before nudging, 60+ min escalation curl, inbox routing with PATCH curl, `updated_at` None guard, worker check-in before task fetch, consistent placeholder style (no `$` prefix on Python-derived IDs), synthesis moved to `shared/docs/synthesis-protocol.md` using `claude -p`. Test budget: 10KB.
- **Supervisor Codex review removed entirely**: Step 3b codex exec block deleted from lead template. QA-E2E is the sole Evaluator. Supervisor reads QA evidence and approves/rejects — no Codex subprocess. Lead template: 16.9KB → 14.6KB.
- **QA routing**: Backend-only tasks use QA-Unit only (not "wait for BOTH"). Validation check matches correct prefixes ("QA-Unit validation" / "QA-E2E validation"). QA-E2E nudge includes "be SKEPTICAL" instruction.
- **Board API is source of truth**: Supervisor must always run health scan, never skip because MEMORY.md says "waiting for X".

## 2026-03-25

### Added
- **Agent harness improvements plan** (`docs/plans/2026-03-25-agent-harness-improvements.md`): 11-task plan based on Anthropic's "Harness Design for Long-Running Apps" article, Codex-reviewed to 100% compliance. Covers: liveness fixes, continuous workflow, template shrink (19KB→8-10KB), structured handoff files, high-level specs, design-quality anchoring, QA grading rubric with originality/craft dimensions, few-shot calibration, trace review loop, and agent consolidation analysis.
- **Architect-as-planner role**: Architect expands Supervisor's short task seeds into full specs with sprint contracts. Supervisor remains the sole hub for all assignment, QA routing, and escalation. Bypass rule: LOW/bugfix/<3 files skip Architect.
- **QA-E2E as sole Evaluator** (article-aligned): QA-E2E now owns the full evaluation — code quality, design quality, originality, craft, AND functionality with scored rubric. QA-Unit handles mechanical checks (typecheck, lint, tests). Supervisor no longer runs Codex review — reads QA evidence and approves/rejects. Three-role pattern: Planner (Supervisor+Architect), Generator (Programmers), Evaluator (QA-E2E+QA-Unit).
- **Skepticism rule for QA-E2E**: "Be SKEPTICAL by default. LLMs tend toward leniency — fight that instinct." Evaluator must cite specific evidence, score each rubric dimension, challenge weak evidence. Supervisor also challenges thin QA evidence.
- **Supervisor sandbox locked to read-only**: All Supervisor codex exec calls use `--sandbox read-only`. Supervisor can review code but NEVER implement. If task needs code changes, reject to inbox and assign Programmer.
- **QA grading rubric** with scored dimensions: Originality (20%), Craft (15%), Visual Quality (15%), Spec Fidelity (15%), Interaction (15%), Console/Network (10%), Responsiveness (5%), Code Quality (5%). Hard fail thresholds. 3-round reject/fix/retest loop before Supervisor escalation.
- **Refine-or-pivot rule**: If QA rejects twice on same issue, developer must decide to refine or pivot approach.
- **Contract negotiation**: QA signs off on sprint contract before implementation starts (HIGH/MEDIUM tasks).
- **Chrome MCP for agents**: Installed headless Chromium + chrome-devtools-mcp on gateway for Programmer-Frontend, QA-E2E, and Supervisor.
- **Frontend skills**: Enabled `frontend-design`, `feature-dev`, `code-simplifier` plugins on gateway. Updated all agent IDENTITY.md with mandatory skill activation instructions.
- **`BOARD_TIMEZONE` in TOOLS.md**: Agents now know the board's timezone. HEARTBEAT non-negotiable rule: use BOARD_TIMEZONE for date displays, not UTC. Prevents "today/tomorrow" meeting display bugs.
- **`agent-status.sh`**: CLI dashboard showing all agents, status, current task, heartbeat interval, last seen.
- **Model changes**: Supervisor, Architect, QA-Unit primary model changed to `openai-codex/gpt-5.4` with MiniMax M2.7 as first fallback. Heartbeat model remains `minimax-m2.5` for all agents.

### Changed
- **Continuous workflow** (Plan Task 1 — implemented): Workers run through PLAN → CONTRACT CHECK → IMPLEMENT → VALIDATE in one session. No forced stops. Stale WORKFLOW line cleanup. Zero-test guard restored.
- **OFFLINE_AFTER=35m** (Plan Task 0 — implemented): 30m-heartbeat agents no longer falsely marked offline. DEFAULT_HEARTBEAT_CONFIG now includes isolatedSession + lightContext.
- **Supervisor Codex review removed**: Entire Step 3b codex exec block deleted. Supervisor reads QA evidence only. Lead template: 16.9KB → 14.6KB.
- **Board API is source of truth**: Supervisor must always run health scan, never skip because MEMORY.md says "waiting".
- **Worker heartbeat interval**: 30m for all workers (deliver=True is the work driver, heartbeat is safety net only).
- **QA routing via Supervisor**: All QA work routed through Supervisor. QA-Unit for code quality, QA-E2E for browser validation. Supervisor sends sprint contracts to QA for pre-build signoff.
- **Role boundaries**: Workers must ask @lead for cross-role work. Progress updates every 30 min.
- **Lead nudge**: Changed from "Move to review NOW" to "Post a status update — are you blocked?" Respects workflow gates.
- **Task rejection**: Updated to match auto-reassignment behavior in backend code.
- **`board-stop.sh`**: Added `set-heartbeats` RPC (Step 2b), fixed JSON quoting (Step 4).
- **`board-start.sh`**: Replaced hardcoded Python SDK RPC with CLI command. Added template sync (Step 7b) before heartbeat check-in (Step 7c) for token hash resync.
- **Methodical rollout policy**: One task at a time, measure impact, rollback criteria. Model reassessment when new versions ship.

### Fixed
- **Meeting timezone bug**: Agents displayed "today" for tomorrow's meetings because they used UTC instead of board timezone. Added `BOARD_TIMEZONE` to TOOLS.md and HEARTBEAT rule.
- **Token rotation lockout — automated resync**: Two-layer fix for the recurring problem where gateway SIGUSR1 restarts rotate TOOLS.md tokens but leave stale hashes in the MC database, locking agents out with 401 Unauthorized.
  - **Layer 1** (`provisioning_db.py`): During template sync, if TOOLS.md token doesn't match DB hash, auto-resync the DB hash from TOOLS.md instead of logging a warning. Only resyncs existing agents (not new ones) and only from trusted gateway workspace reads.
  - **Layer 2** (`board-start.sh` Step 7b): After gateway restart, calls `POST /gateways/{id}/templates/sync` to trigger Layer 1 for all agents before attempting heartbeat check-in. Steps reordered: enable heartbeats (7) → sync templates + resync tokens (7b) → check in agents (7c). Codex-validated: confirmed the API call traces through `sync_gateway_templates → _sync_one_agent → _resolve_agent_auth_token → resync branch`.
  - **Root cause confirmed**: `lifecycle_orchestrator.run_lifecycle()` mints new tokens every cycle via `mint_agent_token()`, flushes to DB before gateway write, and commits even on gateway failure — creating DB-new/TOOLS-old mismatch when writes fail (e.g., active session blocks file write). Template sync is the only code path that reads TOOLS.md and can detect/fix the drift.
  - **RQ worker restart required**: The RQ worker process (lifecycle reconciler) must be restarted after deploying `provisioning_db.py` changes — `kill -HUP` only reloads the uvicorn web server, not the separate RQ worker process.

### Changed
- **RQ worker restarted** on MC server (was running since March 22 with old code).

## 2026-03-24

### Added
- **QA-first review flow**: Supervisor routes `review` tasks to QA-E2E for browser validation before running Codex coherence review. Previous flow skipped QA entirely. (`BOARD_HEARTBEAT.md.j2` Step 3)
- **QA failure routing**: Step 3a-fail — failed QA validation routes task back to `inbox` and reassigns to the developer for rework. Prevents tasks stalling in review.
- **Chrome MCP for agents**: Installed headless Chromium + `chrome-devtools-mcp` on the gateway. Configured `.mcp.json` for Programmer-Frontend, QA-E2E, and Supervisor workspaces. Template now instructs frontend workers and QA to validate with browser tools (navigate, screenshot, console errors, DOM evaluation).
- **Role boundaries**: Workers must ask `@lead` for work outside their role (e.g., frontend agent needing backend API changes). Prevents role violations.
- **Progress updates**: Workers must post task comments every 30 minutes while actively working. No comments = assumed stuck.
- **`_notify_lead_on_task_create`**: Board lead notified instantly when new tasks are created (already existed in codebase).
- **`agent-status.sh`**: New CLI script showing all agents, their status, current task, heartbeat interval, and last seen. Accepts optional `board_id` argument.
- **`isolatedSession` + `lightContext`**: Enabled for all agents on OpenClaw 2026.3.23-2. Each heartbeat runs in a fresh session seeing only HEARTBEAT.md — eliminates session poisoning and reduces token cost.

### Changed
- **Worker workflow simplified**: `PLANNING → IMPLEMENTING → VALIDATING → review`. Code review with opposite ACP tool (Claude Code ↔ Codex) now happens inside IMPLEMENTING step, not as a separate REVIEWING state.
- **Worker task fetch**: Now includes `review` status so QA agents can see and act on assigned review tasks.
- **Lead nudge**: Changed from "Move to review NOW" to "Post a status update NOW — are you blocked?" — respects worker workflow gates instead of bypassing them.
- **Task rejection guidance**: Updated to match actual backend behavior — system auto-reassigns rejected tasks to previous worker, manual reassignment only as fallback.
- **Model configuration**: Primary model `minimax/MiniMax-M2.7` (direct API), heartbeat model `minimax/minimax-m2.5` (fastest), fallback chain M2.5 → M2.1 → ollama/m2.7:cloud → qwen3-coder.
- **Worker heartbeat interval**: Changed from 3-15m to 30m. Supervisor stays at 5m. Workers get instant notifications via `deliver=True` when assigned tasks.
- **`board-stop.sh`**: Added `openclaw gateway call set-heartbeats --params '{"enabled":false}'` (Step 2b) to disable heartbeats at runtime level. Fixed Step 4 JSON quoting.
- **`board-start.sh`**: Replaced hardcoded Python SDK RPC with `openclaw gateway call set-heartbeats` CLI command.
- **Agent IDENTITY.md**: Updated ACP tool lines per role — Programmers implement + review code (opposite tool), QA validates + reports, Architect designs.

### Fixed
- **Token rotation lockout** (`provisioning_db.py`): When TOOLS.md token doesn't match DB hash after gateway restart, the DB hash is now auto-resynced from TOOLS.md instead of leaving auth broken. Previously caused recurring agent lockouts requiring manual intervention.
- **HEARTBEAT_OK inconsistency**: Interrupted ACP sessions now consistently post blocker + return HEARTBEAT_OK (was contradictory between PLANNING and interrupted-session sections).
- **Approval path**: Codex coherence review approval no longer tries to "reassign back to lead" (which was forbidden by API). Approved tasks proceed to human approval flow or done.

### Investigated (not merged)
- **PR #247 Auto Heartbeat Governor**: Reviewed upstream PR with Codex (GPT-5.4 high). Found 4 high-severity bugs: broken lead cap logic, unfixed #266 config.patch loop, unsafe advisory lock with SQLAlchemy pooling, conflict with lifecycle reconciler. Documented in memory for future implementation.

## 2026-03-22

### Added
- **Supervisor approval flow**: Supervisor creates approval requests (POST /approvals) with confidence score and lead reasoning when Codex approves a task. Human signs off in MC UI.
- **Stale agent recovery**: `POST /agents/{id}/recover` endpoint for recovering agents without forging heartbeats.
- **Offline detection grace period**: `HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL` (1 min) added to offline detection for agents with 10m heartbeat intervals.
- **Dependency unblock notifications**: `_notify_agents_on_dependency_unblocked()` notifies assignees when blocking task completes.
- **Inline mention notifications**: `_record_task_comment_from_update()` sends mention notifications for inline PATCH comments.
- **`deliver=True`**: Fixed in `_send_lead_task_message` and `_send_agent_task_message` (was False).
- **Exec guard**: Added to BOOTSTRAP.md and HEARTBEAT.md — "Do not assume exec is blocked based on an earlier session."

### Changed
- **BOARD_HEARTBEAT.md.j2**: Complete rewrite with REX workflow, lead 5-step checklist, Codex review delegation, synthesis protocol, plugin integration (redis-agent-memory, lossless-claw).
- **`CHECKIN_DEADLINE_AFTER_WAKE`**: 30s → 35m (prevents reconcile restart loops).
- **`bootstrapMaxChars`**: 15,000 → 20,000 (template was being truncated).

### Fixed
- **SIGUSR1 restart loop**: 3 stale agents from another board caused config drift → constant config.patch → SIGUSR1. Fixed by aligning gateway config.
- **Supervisor exec block hallucination**: Model assumed exec was blocked from prior sessions. Fixed with exec guard in templates.
- **Board scripts**: Fixed JSON quoting, added `lead-*` prefix handling, added `/pause`/`/resume` for UI sync.
