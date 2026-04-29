# Changelog

All notable changes to the OpenClaw Mission Control fork.

## 2026-04-29

### Fixed
- **OpenClaw 2026.4.26 hardening follow-ups**: Treat boolean `runTimeoutSeconds` values as invalid during runtime guardrail merging, return `ok=false` for local `openclaw status --json` execution errors, and cover structured-review lead wake failures plus runtime-status admin auth wiring in tests.

## 2026-04-28

### Changed
- **AGENTS skill extraction**: Moved lead next-action, lead health scan, inbox routing, QA verdict, Architect verdict, reviewer recheck, and DevOps deploy-validation procedures into dedicated skills, leaving AGENTS.md as the visible role/index layer.
- **OpenClaw 2026.4.26 guardrails**: MC gateway provisioning now merges the 4.26 transcript byte-guard compaction settings, explicit subagent target policy, ACP run timeout/archive defaults, and disables automatic ACP dispatch while preserving explicit `sessions_spawn(runtime="acp")` flows.
- **Gateway runtime visibility**: Added a local OpenClaw runtime status endpoint backed by `openclaw status --json`, with JSON extraction tolerant of config-warning prefixes.

### Fixed
- **Structured review wake**: `/review-events` now wakes the board lead with `deliver=True` after the structured verdict is committed, making the `structured-review-verdict` skill contract true.
- **Gateway method catalog**: Updated the advertised OpenClaw RPC method list for 2026.4.26 by adding `node.pair.remove`.

## 2026-04-16

### Fixed
- **Heartbeat supervision gap**: Agents could appear `online` from ordinary authenticated API traffic while remaining effectively unsupervised because `agent_auth._touch_agent_presence()` updated `last_seen_at` without rearming `checkin_deadline_at`. This left the heartbeat sweep watching only agents with an already-populated deadline. Fixed by rearming the heartbeat deadline and resetting `wake_attempts` when authenticated agent traffic is the liveness signal.
- **Live `.64` heartbeat recovery**: Deployed the auth-touch heartbeat rearm fix to `.64`, restarted the backend, and reseeded missing `checkin_deadline_at` values for the currently online agents so all monitored agents returned to active supervision immediately.

### Changed
- **Model policy note superseded**: The older `2026-04-09` fallback/model notes below are historical only. Current validated fallback policy is the later live `.64` policy recorded in the gateway provisioning/troubleshooting docs and subsequent sync commits, not the earlier `m2.1`-forward recommendations in that section.

## 2026-04-09

### Added
- **Cancelled column on Kanban board**: Added `cancelled` status column to TaskBoard with show/hide toggle in board settings (Edit board > Rules > Show cancelled column). Persisted via localStorage per board.
- **Board settings: Show cancelled column toggle**: New toggle in board configuration page (Rules section) controls cancelled column visibility on the Kanban board.
- **Viewport-constrained Kanban grid**: Added `max-h-[calc(100vh-220px)]` with `overflow-y-auto` so horizontal scrollbar stays at the bottom of the viewport instead of at the bottom of the tallest column.

### Changed
- **Agent model fallback chains**: Updated all agent fallback chains based on real-template heartbeat comparison test (6 models x 6 agents with Jinja2-rendered prompts). qwen3.5 best all-rounder, m2.1 best speed. gpt-5.4 primary for all agents.
- **Supervisor model**: Reverted to gpt-5.4 primary with m2.1 as first fallback (was briefly m2.7 primary). m2.1 scored 7/7 on Supervisor heartbeat at 15s.
- **MiniMax direct API**: Fallback chains now use `minimax/minimax-m2.1` and `minimax/minimax-m2.7` via direct MiniMax API instead of Ollama cloud proxy for faster response.
- **Default model**: Changed defaults primary from claude-sonnet-4-6 to openai-codex/gpt-5.4.

### Fixed
- **Kanban column gap bug**: Fixed phantom 260px gap between Agents panel and Inbox column caused by "Show cancelled tasks" checkbox being rendered inside the CSS grid container. Moved toggle to board settings page.

## 2026-04-03

### Added
- **MC heartbeat monitor design**: RQ sweep every 5min, nudge/wake/offline recovery ladder. Uses existing lifecycle infrastructure. Design doc at `docs/plans/2026-04-03-mc-heartbeat-monitor-design.md`. PB implementing.
- **Supervisor nudge rules**: Workers now nudge Supervisor via RPC after moving tasks to review or posting QA results. No more waiting for heartbeat tick.
- **Supervisor Architect hard rule**: "Every feature task MUST go through Architect review BEFORE QA." Enforced in SOUL.md + IDENTITY.md.
- **OpenClaw 2026.4.2 optimizations**: `agents.defaults.params.cacheRetention: "long"`, `compaction.notifyUser: false`, `pluginToolsMcpBridge: true`, `acp.stream.coalesceIdleMs: 1000`.

### Changed
- **Supervisor heartbeat**: 10m → 5m, removed `activeHours` (was causing timer to die overnight and not resume).
- **ACP TTL**: 120m → 30m. Prevents resource accumulation from long-lived ACP sessions that caused gateway crash (load avg 36+).
- **QA-E2E model**: claude-sonnet-4-6 → openai-codex/gpt-5.4 (sonnet as fallback). E2E tested both — equivalent quality, gpt-5.4 provides more verbose evidence.
- **Supervisor model**: claude-opus-4-6 → claude-sonnet-4-6. Orchestration doesn't need Opus reasoning.
- **BOARD_SOUL.md.j2**: Merged Ralph Loop + sessions_spawn into template. Cleared `soul_template` DB field for workers so template renders. Supervisor keeps DB override with Squad Matrix.
- **BOARD_IDENTITY.md.j2**: Added ACP Delegation section. Used `identity_template` DB override for all agents (IDENTITY.md is in PRESERVE_AGENT_EDITABLE_FILES, template sync won't overwrite).
- **BOARD_HEARTBEAT.md.j2**: Added nudge-Supervisor curls after moving to review and after QA posts results.
- **Removed `temperature: 0.2`** from agents.defaults.params — gpt-5.4 rejects it.

### Fixed
- **IPC path bug**: `get_ipc_base_dir()` wrote OTP files to `data/taskflow/data/ipc/` instead of `data/ipc/`. NanoClaw never saw them — WhatsApp OTPs were never delivered. One-line fix: `db_path.parent.parent / "ipc"`. 101 stale files cleaned up.
- **Gateway crash recovery**: All agents need manual wake after gateway restart. Poisoned sessions (tool_use without tool_result) need `/reset`. Documented pattern.
- **QA-E2E stale cron**: Deleted orphan `qa-e2e-heartbeat` cron job running every 30s, causing 81 timed_out + 7 failed background tasks.
- **Supervisor heartbeat not resuming**: `activeHours` pause/resume cycle killed the timer. Removed activeHours entirely.

### Security
- **TEST_OTP reverted**: Deployed as QA testing aid, flagged as backdoor. Code exists in main.py but env var not set. PB reverting through normal pipeline.
- **OTP phone validation**: Posted task for PB — `request-otp` should check if phone exists in board people before sending OTP. Currently any number can request codes.

### Investigated
- **Supervisor stuck pattern**: Gateway timer dies → Supervisor offline → nobody nudges workers → whole team idle. Root cause: `activeHours` and gateway restarts kill the timer. Fix: removed activeHours + MC heartbeat monitor (in development).
- **ACP session accumulation**: Multiple concurrent ACP Claude sessions (PF + Architect) consumed 100% CPU, gateway crashed (load avg 36+). Fix: reduced TTL from 120m to 30m.
- **Architect never used**: Supervisor never assigned tasks to Architect — 0 tasks in history. Fixed with hard rule in Supervisor SOUL.md + IDENTITY.md.
- **QA-E2E model comparison**: claude-sonnet-4-6 (35s, 73K tokens, concise table) vs gpt-5.4 (47s, 69K tokens, verbose JSON). Both produce correct 4/4 PASS results.

## 2026-04-02 (cont.)

### Changed
- **BOARD_SOUL.md.j2**: Merged Ralph Loop + sessions_spawn ACP delegation into worker template. `soul_template` DB field cleared for workers so template default renders. Supervisor soul_template updated with new Squad Matrix (sessions_spawn workflow).
- **BOARD_IDENTITY.md.j2**: Added ACP Delegation section. `identity_template` DB field set for all agents with role-specific content + sessions_spawn references.
- **Supervisor model**: claude-opus-4-6 → claude-sonnet-4-6 (orchestration doesn't need Opus). QA-E2E also switched from Opus to Sonnet.
- **Agent session resets**: All 7 agents reset to pick up new SOUL.md + IDENTITY.md content.

### Fixed
- **IDENTITY.md not syncing**: `PRESERVE_AGENT_EDITABLE_FILES` includes IDENTITY.md — template sync never overwrites existing files. Fix: set `identity_template` DB field (override path) and write directly to gateway.
- **Supervisor SOUL.md stale**: Lead branch of BOARD_SOUL.md.j2 didn't check `directory_role_soul_markdown`. Fixed template to render DB content for leads.
- **Phase 1C: org_id migration bug**: QA-Unit flagged `boards.org_id` skipped on fresh DB. PB fixed (commit 472314c), 24/24 tests. Approved.

### Security
- **TEST_OTP env var reverted**: Deployed as QA testing aid but flagged as security backdoor on production. PB reverting through normal pipeline. QA-E2E will read real OTP from IPC files via SSH instead.

### Investigated
- **Agent ACP usage**: Confirmed agents never used sessions_spawn — coded directly via Bash/Edit. Root cause: SOUL.md had vague "delegate via ACP" with no concrete tool call. Fixed with exact sessions_spawn JSON in templates.
- **Template sync mechanics**: `identity_template` and `soul_template` DB fields override Jinja templates entirely. IDENTITY.md is in PRESERVE_AGENT_EDITABLE_FILES — sync won't overwrite. Must delete file first or use DB override field.
- **Ollama heartbeat model**: E2E tested ollama/qwen3.5:cloud — makes correct tool calls. The "read without path" error was transient during gateway restart, not a chronic model issue.

## 2026-04-02

### Added
- **Phase 1B: Auth endpoints approved**: OTP request, verify (JWT + httpOnly cookies), refresh (token rotation), logout, /me. Rate limiting (5/15min → 429). DB tables: users, otp_requests, sessions. Full E2E validated via Chrome MCP browser login.
- **Phase 1B: OTP IPC plugin approved**: `send-otp.ts` on skill/taskflow branch (.160). Handles `send_otp` IPC type, verifies phone on WhatsApp via `lookupPhoneJid`, main-only guard. 5/5 tests pass.
- **Phase 1B regression fix approved**: verify-otp now sets httpOnly cookies (access_token 15min, refresh_token 7d, SameSite=lax). Frontend `credentials:include` flow works. 22/22 tests.
- **Phase 1D: Enhanced task editing approved**: Click-to-edit title, description textarea, labels add/remove with PATCH. Chrome MCP validated.
- **Chat unread badge approved**: HTTP polling (5s) detects new messages, red badge on Chat button, clears on panel open. No phantom badge on reload. 18+ QA rounds.
- **Codex plugin for Claude Code**: `codex@openai-codex` v1.0.2 installed on gateway (.60). Skills: /codex (review, adversarial-review, rescue), /simplify.

### Changed
- **ACP defaultAgent**: `codex` → `claude` in openclaw.json. ACP sessions now use Claude Code where /codex and /simplify skills are available.
- **Agent ACP workflow**: PF, PB, Architect SOUL.md updated with concrete `sessions_spawn` tool call (`runtime: "acp"`, `agentId: "claude"`). Previously said "delegate to Claude Code CLI via ACP" — agents didn't know how and never used ACP. E2E validated: sessions_spawn works, ACP Claude session sees /simplify + /codex skills.
- **HEARTBEAT IMPLEMENTING step**: Now defers to IDENTITY.md for tool choice instead of hardcoding "Claude Code CLI".
- **Superpowers symlink fix**: `/root/.agents/skills/superpowers` was a symlink outside configured root (rejected by gateway). Copied instead.

### Investigated
- **Why agents never used Codex or Claude Code**: `acp.defaultAgent` was "codex" but agents never called `sessions_spawn` — they coded directly via Bash/Edit tools. The SOUL.md instructions were vague ("delegate via ACP") with no concrete tool call. Fixed by adding exact `sessions_spawn` JSON to SOUL.md.
- **Claude Code skills ≠ OpenClaw skills**: Different format, different paths, not interchangeable. Claude Code plugins at `~/.claude/plugins/`, OpenClaw skills at `~/.agents/skills/`. Cannot add Claude Code plugin paths to OpenClaw `skills.load.extraDirs`.
- **`runtime` object in agent entries**: Gateway rejects it silently, breaks config reloads + heartbeat timers (2026-03-22 incident). ACP routing must use root-level `acp.defaultAgent`, not per-agent runtime fields.

## 2026-04-01 (cont.)

### Fixed
- **Chrome MCP zombie processes**: 98 `chrome-devtools-mcp` processes consuming 8.6 GB RAM. Root cause: `mcp.servers` config spawned per-session stdio processes, gateway mode never calls `disposeSessionMcpRuntime()`. Fix: removed `mcp.servers`, use native `browser` config (shared instance with session cache).
- **Heartbeat disable**: `0m` is the correct gateway value (per docs). Previous `"disabled"` string and key-stripping approaches didn't work. Updated provisioning to send `"0m"`, MC database updated.
- **Worker token burn**: All 6 workers had drifted to `1h` heartbeat (from lifecycle config.patch). Reset to `0m` (disabled). Only Supervisor (10m) heartbeats actively.

### Changed
- **Phase 1A deployed and approved**: PATCH/DELETE/comments endpoints + SQLite WAL live on production (.63). TaskDetailPanel edits, drag-and-drop, comments, delete all functional.
- **Removed Chrome MCP references**: All templates (HEARTBEAT, TOOLS.md) and agent identities (PF, QA-E2E) updated. Agents use native `browser` tool or Playwright — no more `mcp__chrome-devtools__*`.
- **PB model workflow**: Changed from Codex to Claude Code CLI. One session per task, `/simplify` mandatory before review.
- **PF workflow**: Added one Claude Code session per task, `/simplify` mandatory, no Codex.
- **HEARTBEAT IMPLEMENTING step**: Explicit "Use ONE Claude Code CLI session via ACP — do not spawn multiple. Then run `/simplify` on changed files."
- **Supervisor guardrail**: Spot-check worker evidence before accepting review tasks.

## 2026-03-31 / 2026-04-01

### Added
- **Board Chat (T1-T7)**: send/receive messages from board UI. API endpoints, messages.db injection, NanoClaw trigger bypass for `web:` sender, `send_board_chat` MCP tool, React BoardChat (Radix Dialog overlay), WebSocket `chat:new`. E2E verified on production.
- **Collapsible kanban columns**: per-column toggle with localStorage per board. Empty columns default collapsed.
- **Team panel improvements**: owner always first, default collapsed, collapsible toggle, per-board localStorage fix.
- **Hover lift effect**: People panel rows match kanban card hover (translate-y, shadow, border, 150ms transition).
- **Assignee dedup**: dropdown resolves person IDs to display names, hides test-user.
- **Scrollbar + background color**: scrollbar at viewport bottom (gap=0), bg-slate-200 tint, gap reduced to 36px.
- **Inbox + button / People + button**: quick task creation and add person placeholders.
- **Tailscale proxy CT** (`thales-tailscale`, VMID 111): remote access to 192.168.2.13 via Tailscale.
- **TaskFlow product roadmap**: 6-phase plan, Phase 1 final spec (reviewed by Codex + Claude Code agent), current capabilities inventory, technical architecture.
- **Phase 1A API contract**: Architect-reviewed spec for PATCH/DELETE/comments with production-verified schemas (task_history `by`/`at`/`details`, archive `task_snapshot`/`archive_reason`).

### Fixed
- **Lifecycle orchestrator stuck "updating"**: skip `mark_provision_requested` for disabled-heartbeat agents while allowing file sync.
- **Config.patch "invalid duration"**: send `0m` (per OpenClaw docs) instead of stripping `every` key for disabled agents. Previous approach left gateway on cached `1h`.
- **Heartbeat disable**: `0m` is the correct value per docs. Updated MC database, provisioning code, and gateway config. Workers no longer burn tokens hourly.
- **Task description truncation**: removed `[:500]`/`[:300]` limits. PF never saw item #2 of 1112-char task.
- **QA evidence fabrication**: QA-Unit reported PASS for T3 with fabricated code — added mandatory code existence check (`git log` + `grep`) and proof format to HEARTBEAT template.
- **Compaction model**: changed from failing `gpt-5.4` to `ollama/qwen3.5:cloud` (local). Fixed in MC database to survive lifecycle syncs.
- **Supervisor heartbeat model**: `minimax-m2.5` → `ollama/qwen3.5:cloud` in MC database.
- **Browser tools**: configured native browser (Chromium 145) + gateway-level Chrome DevTools MCP.
- **Board Config placement**: investigated original layout (commit 9bc6c6f) — restored `overflow-y-auto` on main content, Board Config below kanban in vertical flow.

### Changed
- **HEARTBEAT guardrails**: QA code existence check, proof format, Supervisor evidence spot-check, nudge-woken agents must follow all steps, parent task closure.
- **PF model trial**: Opus 4.6 delivered 3-item feature in 13 min vs Sonnet's 9 failures. Switched back after template fixes.
- **NanoClaw skill branch rule**: all changes on `skill/taskflow`, never `main`. Documented in Phase 1 plan.

### Investigated
- **NanoClaw TaskFlow architecture**: engine (7,816 lines, 10 MCP tools), 14 tables, scheduled reports, hierarchy, WhatsApp routing, IPC plugins. Gap is API + frontend, not engine.
- **Board chat plan**: 4 review rounds. Found: cross-DB write, prompt type mismatch, IPC outbound-only, schema mismatches.

## 2026-03-29

### Fixed
- **Task description truncation** (`BOARD_HEARTBEAT.md.j2`): Worker step 2 truncated descriptions at 500 chars — PF never saw background color requirements on 1112-char task. Removed `[:500]` limit. Also removed `[:300]` on Supervisor comment fetch and `[:500]` on worker comment fetch. Agents now read full descriptions, QA reports, and rejection details.
- **QA-E2E partial validation**: QA-E2E only validated items matching the task title, ignoring other acceptance criteria in the description. Added "Validate EVERY item in the task description — not just the title. Missing items = FAIL."
- **Supervisor nudge missing criteria**: When routing to QA-E2E, Supervisor only sent task title. Now must include ALL acceptance criteria from task description in the nudge.
- **Compaction model failing** (`gpt-5.4`): LCM plugin used `openai-codex/gpt-5.4` for context compaction which failed 10+ consecutive times, bloating sessions until agents couldn't function. Changed to `ollama/qwen3.5:cloud` (local, no API dependency). Required gateway restart — `touch` doesn't reload LCM plugin config.
- **`tools.allow` breaking exec**: Adding `tools.allow: ["browser"]` at global level blocked all agent tool calls despite Codex/docs saying it's additive. Caused 90+ min outage twice. Removed — browser tool not available via `coding` profile, agents use Playwright via exec instead.

### Changed
- **PF model**: Switched to `anthropic/claude-opus-4-6` primary (was Sonnet) with Sonnet as first fallback. Trial for scrollbar task after 9 consecutive Sonnet failures.
- **Supervisor heartbeat model**: Changed from `minimax/minimax-m2.5` to `ollama/qwen3.5:cloud`.
- **Compaction model**: `agents.defaults.compaction.model` set to `ollama/qwen3.5:cloud`, `plugins.entries.lossless-claw.config.summaryModel` set to `ollama/qwen3.5:cloud`.

### Added
- **Tailscale proxy CT** (`thales-tailscale`, VMID 111): Minimal Debian 12 container on Proxmox (192.168.2.14) for routing remote machine access to 192.168.2.13 via Tailscale. 1 core, 256MB RAM, exit node + subnet route, auto-start on boot.

## 2026-03-28

### Fixed
- **Lifecycle orchestrator stuck "updating" status** (`lifecycle_orchestrator.py`): Agents with disabled heartbeats (`every="disabled"`) got set to `status="updating"` during lifecycle reconciliation, but never reset because they have no heartbeat timer to check in. Fix: skip `mark_provision_requested` for disabled-heartbeat agents on `action="update"` while still allowing file sync to proceed.
- **Browser tools unavailable to agents**: `.mcp.json` files existed in PF/QA-E2E workspaces but were ignored — OpenClaw ACP bridge mode does not support per-session MCP servers. PF fell back to bundle grep (8 builds, 8 fails on scrollbar task). QA-E2E used Playwright as workaround.
- **PF blind copy-paste from old tasks**: PF copied CSS classes from a prior task (B1bt8iXR) without checking if the DOM still matched after layout changes (stats bar removal, header gap fixes). Added "Inspect current state before coding — NEVER copy fixes from other tasks without verifying they still apply" to IMPLEMENTING step.

### Added
- **Native browser support on gateway** (`openclaw.json`): Configured `browser` section with headless Chromium 145 (Playwright's bundled Chrome) on CDP port 18800. `browser.enabled=true`, `headless=true`, `noSandbox=true`. All agents now have the `browser` tool via `tools.allow: ["browser"]`.
- **Gateway-level Chrome DevTools MCP** (`mcp.servers.chrome-devtools`): Registered at gateway level (not per-workspace `.mcp.json`), connects to native browser on :18800. Gives all agents `mcp__chrome-devtools__*` tools. Bypasses ACP bridge mode limitation.
- **Browser tools in TOOLS.md**: All agents now see "Browser tools available: `browser` (native), `mcp__chrome-devtools__*` (Chrome MCP), `npx playwright test` (fallback)" in their TOOLS.md.
- **Browser tools in IDENTITY.md**: PF has "Browser Tools (MANDATORY for frontend/UI work)" section — diagnose before fixing, never use bundle grep. QA-E2E has "Browser Tools (MANDATORY for all UI tasks)" section — fresh browser session for every validation.
- **Three-option browser validation in HEARTBEAT template**: Workers' VALIDATING step now lists Chrome MCP, native `browser` tool, and Playwright as options. "Bundle grep is NOT evidence."

### Changed
- **HEARTBEAT template IMPLEMENTING step**: Added "Inspect current state (DOM/API/files) before coding — NEVER copy fixes from other tasks without verifying they still apply."

## 2026-03-27

### Fixed
- **Build freeze protocol**: PF kept deploying new builds while QA-E2E was mid-validation, causing double validation on different hashes. Added: worker must not deploy after moving to review (move back to in_progress first); QA must STOP if build hash changes mid-validation.
- **Supervisor fake approval guardrail**: Supervisor was posting "Miguel approved. Moving to done." while approval was still PENDING. Added "NEVER approve tasks. Only HUMANS approve. PENDING = WAIT." to lead template.
- **Board API is truth for ALL agents**: Architect posted "waiting for approval" on tasks done hours ago — relied on stale memory. Added "Board API is source of truth. Check API before posting idle/waiting/blocked" to shared Rules section (all agents).
- **QA-E2E false PASS from memory**: QA-E2E recycled old validation results instead of re-running Chrome MCP. Added "re-validate EVERY time with fresh session, previous PASS/FAIL is irrelevant."
- **Chrome MCP enforcement at all levels**: PF must use Chrome MCP before review (was optional). QA-E2E must use Chrome MCP for ALL UI tasks (bundle grep NEVER valid). Supervisor must reject QA PASS without Chrome MCP evidence.
- **Review chain: Architect before QA**: Supervisor was skipping Architect and routing directly to QA-E2E. Added "route Architect FIRST for code review, then QA" (skip for bugfixes/<3 files).
- **Supervisor @lead self-tag**: Supervisor was tagging @lead in its own messages. Added "You ARE the lead. Do NOT tag @lead."
- **Duplicate task creation guard**: Supervisor created 3 identical MIME-fix tasks in 30 seconds. Added "check /tmp/tasks.json before creating" guard.
- **Orphaned approval flow**: Tasks rejected back to inbox couldn't move to done because API requires `review→done`. Template now PATCHes to `review` first when approval is approved on non-review task.
- **config.patch overwriting gateway settings** (`provisioning.py`): `_updated_agent_list()` now MERGES heartbeat dict instead of replacing — preserves gateway-only fields (model, name). `DEFAULT_HEARTBEAT_CONFIG.lightContext` changed to `False`.
- **Supervisor frozen on PARTIAL QA result**: QA-E2E posted "6/7 PASS, F2 PARTIAL" — Supervisor had no branch for PARTIAL and froze 45 min. Added "FAIL or PARTIAL → treat PARTIAL as FAIL" to Step 3 decision tree.
- **Supervisor rejection rule AND gate**: Was OR (table OR evidence) — QA could satisfy with table but no Chrome MCP. Fixed to AND: BOTH scored rubric table AND literal `mcp__chrome-devtools__` output required.
- **QA rubric console error loophole**: "Excluding third-party deprecation warnings" gave QA rationalization path. Removed — `types:["error"]` filter already excludes warnings at tool level.

### Added
- **QA grading rubric** (`shared/qa/rubric.md`): 8 frontend dimensions with weights, hard fail thresholds, specific Chrome MCP tool calls per dimension. Mandatory literal tool output as evidence. BUILD hash must come from network log. Weighted scoring formula. "Be SKEPTICAL" enforcement referencing prior fabrication. 3-round reject/fix/retest loop.
- **Jarvis (main channel)**: Updated to Sonnet 4.6 primary with Opus 4.6 fallback.
- **Supervisor Opus 4.6 fallback**: Added as first fallback after gpt-5.4 — better curl execution discipline than Sonnet.

### Changed
- **Heartbeat optimization**: QA-Unit, QA-E2E, Architect, PB, DevOps heartbeats disabled (0m) — wake via deliver=True only. PF keeps 60m safety net. Supervisor 10m. Token burn: ~24/hour → ~6/hour.
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
