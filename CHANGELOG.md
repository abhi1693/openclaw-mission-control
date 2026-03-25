# Changelog

All notable changes to the OpenClaw Mission Control fork.

## 2026-03-25

### Fixed
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
