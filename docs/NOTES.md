
Review the tasks waiting for approval, use Chome MCP if necessary, the expected behavior is fully compliance with the task spect, only approve with full evidence check

Investigate why the agents aren't nudging each other as instructed

## 2026-04-07 — System Restore + Post-Mortem + Process Guardrails + Phase 1 Complete

### Phase 1 Complete — 97/97 tasks done
- Phase 1C (Org Management UI) and Phase 1D (Profile + Board CRUD) approved and closed
- Phase 1 umbrella task closed
- Backend tasks (PATCH /auth/me + Org API extensions) approved and closed
- 5 phantom fix tasks cancelled (symptoms of rogue deployments)

### Auth Rehydration Fix
- Root cause: `useAuth.ts` used static `getStoredToken()` — not reactive to localStorage changes after OTP login
- Fix: `useSyncExternalStore` + `token-changed` custom event in `setStoredToken`/`clearStoredToken`
- Validated via Chrome MCP: cleared localStorage → real OTP login flow → landed on dashboard, NOT /login
- Build `index-CCko4tQP.js` (commit `a24c77e`) deployed and verified

### QA-E2E Test Methodology Bug
- QA-E2E authenticated via API calls (curl for OTP) but never injected JWT into Playwright browser localStorage
- Browser had no token → app redirected to /login → 68+ false FAILs over 6 days
- Fix: `playwright-auth-helper.mjs` shared helper + template rule mandating browser auth setup
- Template: "BROWSER AUTH SETUP — MANDATORY for authenticated features"

### Rogue Deployment Root Cause Found
- PF was deploying to `~/taskflow-dashboard/dist/` (wrong) instead of `~/taskflow-dashboard/` (root)
- The `serve` process serves from root — deploying to dist/ created a parallel build
- Fix: generic `deploy.sh` script reads `.deploy-config` per project, template "Deploy Target Rule"

### Process Guardrails (commits e2da873, 399aaca, 6da7911, 0d89786, 944e36f, 0675173)
- QA Failure Rework: structured DIAGNOSIS comment required before fixing (file:line, total bugs)
- RE-VALIDATION GATE: QA refuses re-validation without DIAGNOSIS comment
- BUILD HASH GATE: QA verifies live hash matches developer's claim
- Pre-QA Self-Test: typecheck+build+verify for PF/PB/DevOps (not QA/Architect)
- Escalation Rule: 3+ consecutive QA FAILs → stop and escalate to operator
- Supervisor Comment Discipline: max 3/task/hour, skip pure acks
- Supervisor Guard Rails: verify bugs in committed source before creating fix tasks
- Frozen Criteria: new issues outside scope → new task, not scope expansion
- Deploy Target Rule: read from task description, don't guess paths

### TDD Workflow (commits 3c12f8d, 4a77b06, f530001)
- PF and PB now follow red-green-refactor: tests BEFORE implementation
- ACP prompts start with "TDD:" — write failing tests, implement to pass, then review
- Scoped to PF (claude_with_skills) and PB (codex_then_claude_review) only
- QA, Architect, DevOps excluded — TDD impractical for validation/review/infra work

### Domain-Optimized Model Fallback Chains
- Benchmarked 6 Ollama cloud models on domain-specific tasks (frontend, backend, QA, architecture, DevOps, coordination)
- Each agent's fallback chain ranked by live test performance:
  - PF: gpt-5.4 → minimax/m2.7 → gemma4:31b → qwen3.5 (React/TS)
  - PB: gpt-5.4 → kimi-k2.5 → glm-5.1 → qwen3.5 (Python/FastAPI)
  - Architect: gpt-5.4 → kimi-k2.5 → minimax/m2.7 → qwen3.5 (deep analysis)
  - QA-E2E: gpt-5.4 → qwen3.5 → minimax/m2.7 → glm-5.1 (Playwright)
  - QA-Unit: gpt-5.4 → glm-5.1 → kimi-k2.5 → qwen3.5 (pytest)
  - DevOps: gpt-5.4 → qwen3.5 → kimi-k2.5 → glm-5.1 (bash/deploy)
  - Supervisor: gpt-5.4 → minimax/m2.7 → gemma4:31b → qwen3.5 (coordination)
- All minimax uses changed to `minimax/minimax-m2.7` (direct API, not Ollama cloud)
- No anthropic in any fallback chain
- Heartbeat model: qwen3.5:cloud (fastest, most consistent for tick tasks)

### Redis-Memory Plugin
- Disabled entirely (`enabled: false`, memory slot cleared)
- Was poisoning agent sessions with stale memories from failed fix attempts
- Agents use workspace MEMORY.md for structured persistent state instead
- Plugin doesn't support per-agent disable — global only

### Feature Audit (TaskFlow Dashboard vs WhatsApp bot)
- Dashboard is primarily view-only; all task management done via WhatsApp/NanoClaw
- User command frequency: assignment (~101), lookup (~69), deadlines (~45), capture (~44), notes (~19)
- Dashboard missing: 6-column GTD board (next_action/waiting), inbox triage, search/filter by person, project hierarchy, TaskFlow-native notes
- Codex corrected: dashboard DOES have task editing, drag-and-drop, approvals (I was wrong)
- Phase 2 priorities: 6-column board, inbox triage, search+filters, project hierarchy, notes

### Infrastructure
- OpenClaw upgraded to 2026.4.5 — 28 new RPC methods, heartbeat auto-restart on config.patch
- `bootstrapMaxChars` correctly set at `agents.defaults.bootstrapMaxChars` (not top-level)
- `board-stop.sh`/`board-start.sh` scripts for operator freeze (heartbeat only, not full freeze)
- `deploy.sh` + `deploy-lock.sh` for deployment pipeline
- `qa-smoke-test.sh` for pre-submission validation

## 2026-04-07 — System Restore + Post-Mortem + Process Guardrails

### Dashboard Restore
- Restored .63:3000 to build `index-KYqUn_wm.js` (1.12MB, commit 101388d) — the last working PF build
- 5 rogue builds (~870KB each) had overwritten the working build overnight by an unknown process, stripping Google Fonts, org management UI, and ~250KB of features
- Cancelled 5 tasks (4 phantom fix tasks + 1 unnecessary split) created as symptoms of rogue deployments

### useAuth.ts Fix
- Applied `enabled: hasToken` guard to `useAuth.ts` useQuery — the actual 1-line fix that stops 401 noise on unauthenticated pages
- Built `index-DmfeZOa9.js`, deployed to .63:3000, committed as `4771594` in PF workspace
- Codex fact-checked this claim: fix was necessary but NOT sufficient — additional bugs (ProfilePage token sync, LoginPage mounting, PeoplePanel API) were also real and correctly fixed by PF overnight

### Redis-Memory Plugin Disabled
- Plugin was injecting stale/wrong memories into agent sessions via `before_prompt_build` hook
- Stale memories ("interceptor already exists", "401 fix: retry:0 + catch()") caused PF to repeat failed approaches
- `autoRecall: false`, `autoCapture: false`, then `enabled: false` + memory slot cleared
- Per-agent disable not supported by the plugin — global only
- Agents still have workspace `memory/` directory + `MEMORY.md` for file-based state

### PF Model Comparison
- Live-tested 6 Ollama cloud models (qwen3.5, gemma4:31b, minimax-m2.7, kimi-k2.5, nemotron-3-super, glm-5) on a real bug fix from agent interactions
- All 6 produced correct fixes; gemma4:31b-cloud best balance of speed (5.8s) + exact pattern match; nemotron fastest (4.3s)
- PF reverted to `claude_with_skills` ACP flow with `openai-codex/gpt-5.4` as primary model

### Post-Mortem: Why 2 simple tasks took 6 days and 580 comments
- **Phase 1D**: 450 comments, 27 builds, 47 QA FAILs, 7 ACP sessions, 6.3 days
- **Phase 1C**: 130 comments, 18 builds, 21 QA FAILs, 6.3 days
- Combined: 580 comments, 45 builds, 68 QA FAILs for tasks needing ~4 components + 1 fix
- **91% of Phase 1D activity** happened after 18:00 Apr 6 — the explosion was hyperactivity, not inaction
- 10 failure modes identified: ACP death, memory poisoning, deployment chaos, layered auth bugs, Supervisor overhead, permission deadlocks, auth/QA friction, no pre-deploy validation, phantom fix tasks, tick budget waste
- Codex balanced review: PF did real RCA in some cases, Supervisor was 64% substantive (not pure noise), operator interventions also caused harm (scope churn, premature "STOP ALL WORK", overconfident fix claims)

### Process Guardrails Added (commit e2da873 + 399aaca)
**Worker rules:**
- QA Failure Rework: diagnose ALL root causes, fix all in one rework cycle, not one at a time
- Pre-QA Self-Test: typecheck+build, verify live build matches commit — excludes QA and Architect
- Escalation Rule: 3+ consecutive QA FAILs → stop and escalate to operator
- Scope Authority: operator decisions are authoritative, deferred items stay deferred unless operator revises

**Supervisor rules:**
- Comment Discipline: only comment when routing/deciding/identifying — skip pure acks, max 3/task/hour
- Guard Rails: 3+ QA FAILs → escalate and stop fix cycles; verify bugs in committed source before creating fix tasks (prevents phantom tasks from deployment drift)

### Board Status (end of session)
- 92/95 tasks done (5 cancelled phantom/split tasks counted as done)
- 3 remaining: Phase 1C (in_progress), Phase 1D (review), Phase 1 umbrella (in_progress)
- All 8 agents online and heartbeating
- Dashboard live on .63:3000 with build `index-DmfeZOa9.js`

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
All 6 models got it right this time. Here's the real-world comparison:

  ┌────────────────────────┬───────┬────────┬───────────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────┐
  │         Model          │ Time  │ Tokens │                                Correct Fix                                │                            Code Quality                             │
  ├────────────────────────┼───────┼────────┼───────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
  │ nemotron-3-super:cloud │ 4.3s  │ 257    │ Yes — inline enabled: typeof window !== "undefined" && !!getStoredToken() │ Clean, minimal, no variable. Slightly different but equally correct │
  ├────────────────────────┼───────┼────────┼───────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
  │ gemma4:31b-cloud       │ 5.8s  │ 320    │ Yes — hasToken variable + enabled: hasToken                               │ Exact match of the reference pattern. Clean formatting              │
  ├────────────────────────┼───────┼────────┼───────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
  │ glm-5:cloud            │ 6.3s  │ 749    │ Yes — same hasToken pattern                                               │ Correct, more verbose output                                        │
  ├────────────────────────┼───────┼────────┼───────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
  │ minimax-m2.7:cloud     │ 28.2s │ 1,348  │ Yes — same hasToken pattern                                               │ Correct, added // ignore comment                                    │
  ├────────────────────────┼───────┼────────┼───────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
  │ qwen3.5:cloud          │ 37.1s │ 2,981  │ Yes — same hasToken pattern                                               │ Correct but 3K tokens for a simple fix                              │
  ├────────────────────────┼───────┼────────┼───────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
  │ kimi-k2.5:cloud        │ 51.1s │ 1,011  │ Yes — same hasToken pattern                                               │ Correct, compact style                                              │
  └────────────────────────┴───────┴────────┴───────────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────┘

  Real-world ranking

  1. nemotron-3-super:cloud — 4.3s, 257 tokens, correct. Inlined the guard instead of creating a variable — slightly different but equally valid. Fastest by far.
  2. gemma4:31b-cloud — 5.8s, 320 tokens, exact pattern match. Closest to the reference implementation.
  3. glm-5:cloud — 6.3s, 749 tokens, correct. Unexpectedly fast here vs the first test (48s → 6s, likely cached).
  4. minimax-m2.7:cloud — 28s, correct this time (fixed the inversion bug from test 1).
  5. qwen3.5:cloud — 37s, correct but 3K tokens of bloat.
  6. kimi-k2.5:cloud — 51s, correct but slowest.

  gemma4:31b-cloud is the best balance — fast (5.8s), exact pattern match, clean code, no unnecessary output. nemotron is faster but takes liberties with the pattern. For a frontend dev agent that needs to follow existing
  codebase conventions, gemma4 is the safer pick.

                                                                                                                                                                                                                                    
  PF has clear instructions: one fix (enabled: !!getStoredToken() in useAuth.ts), one deploy, one validation cycle. The rogue deployment source still needs investigation to prevent recurrence. 


  Three layers: template rules (today), MC backend features (this week), process discipline (ongoing).                                                                                                                            
                                                                                                                                                                                                                                
  Layer 1: Template Rules (implementable now)                                                                                                                                                                                     
                                                                                                                                                                                                                                  
  1. Pre-QA self-test gate                                                                                                                                                                                                        
                                                                                                                                                                                                                                
  Before submitting to QA, the agent must run a self-test checklist and post results. This catches the layered bugs that created the deploy→fail loop.                                                                            
                                                                                                                                                                                                                                
  ### Pre-QA Self-Test (mandatory before moving to review)                                                                                                                                                                        
  Before posting evidence or moving to review, run ALL checks:                                                                                                                                                                    
  1. `curl -s http://192.168.2.63:3000/ | grep -c '401\|error'` — must be 0                                                                                                                                                       
  2. Open the app unauthenticated — zero console errors expected                                                                                                                                                                  
  3. Login with OTP — verify the authenticated flow works                                                                                                                                                                         
  4. Test the SPECIFIC feature you changed — click through it                                                                                                                                                                     
  5. `git diff --stat` — list exactly what files you changed                                                                                                                                                                      
  If ANY check fails, fix before submitting. Do NOT submit partial fixes.                                                                                                                                                         
                                                                                                                                                                                                                                  
  2. Diagnose-all-before-fixing rule                                                                                                                                                                                              
                                                                                                                                                                                                                                  
  ### Bug Fix Protocol                                                                                                                                                                                                            
  When QA reports a FAIL:                                                                                                                                                                                                       
  1. Read the FULL QA report — list every failing criterion                                                                                                                                                                       
  2. Read the SOURCE CODE for each failing area — diagnose root causes                                                                                                                                                            
  3. Post a comment listing ALL bugs found with file:line references                                                                                                                                                              
  4. Fix ALL bugs in ONE commit, not one at a time                                                                                                                                                                                
  5. Then deploy and submit to QA                                                                                                                                                                                                 
  Do NOT deploy after fixing only one bug. Batch your fixes.                                                                                                                                                                      
                                                                                                                                                                                                                                  
  3. Overnight escalation gate                                                                                                                                                                                                    
                                                                                                                                                                                                                                  
  ### Escalation Rule                                                                                                                                                                                                             
  If a task has received 3+ consecutive QA FAILs without a PASS:                                                                                                                                                                
  - STOP working on it                                                                                                                                                                                                            
  - Post: "ESCALATION: 3+ QA FAILs. Requesting operator review before continuing."                                                                                                                                                
  - Do NOT deploy again until operator responds                                                                                                                                                                                   
                                                                                                                                                                                                                                  
  4. Supervisor comment throttle                                                                                                                                                                                                  
                                                                                                                                                                                                                                
  ### Lead Comment Rules                                                                                                                                                                                                          
  - Do NOT acknowledge every agent comment. Only comment when:                                                                                                                                                                  
    - Routing to a different agent                                                                                                                                                                                                
    - Making a scope/priority decision
    - Identifying a problem the agent missed                                                                                                                                                                                      
    - Answering a question                                                                                                                                                                                                      
  - Pure acknowledgments ("Acknowledged. Stay in progress.") are NOISE. Skip them.                                                                                                                                                
  - Maximum 3 comments per task per hour                                                                                                                                                                                          
                                                                                                                                                                                                                                  
  5. Scope authority                                                                                                                                                                                                              
                                                                                                                                                                                                                                
  ### Scope Authority                                                                                                                                                                                                             
  Operator scope decisions are FINAL. Do not reopen deferred items.                                                                                                                                                             
  If Architect or QA flags a deferred item, respond:
  "Item X was explicitly deferred to Phase 2 by operator. Not in scope."                                                                                                                                                          
                                                                                                                                                                                                                                  
  Layer 2: MC Backend Features (this week)                                                                                                                                                                                        
                                                                                                                                                                                                                                  
  1. Deploy tracking                                                                                                                                                                                                            

  MC should track the expected build hash per deployment:                                                                                                                                                                         
  - After PF deploys, PF posts the build hash in a structured comment
  - MC stores it: {agent_id, task_id, build_hash, commit_sha, deployed_at}                                                                                                                                                        
  - Heartbeat sweep checks: is the live build still what was deployed?                                                                                                                                                          
  - Alert if build drift detected                                                                                                                                                                                                 
                                                                                                                                                                                                                                  
  2. QA fail counter                                                                                                                                                                                                              
                                                                                                                                                                                                                                  
  MC counts consecutive QA FAILs per task:                                                                                                                                                                                        
  - After 3 FAILs without a PASS, automatically post escalation comment + pause heartbeat for the assigned agent on that task                                                                                                   
  - Operator must explicitly resume                                                                                                                                                                                               
                                                                                                                                                                                                                                
  3. Deploy lock                                                                                                                                                                                                                  
                                                                                                                                                                                                                                
  Only one deploy to a target (e.g., .63:3000) at a time:                                                                                                                                                                         
  - PF requests deploy via MC API
  - MC checks: is another deploy in progress? Is the target locked?                                                                                                                                                               
  - If locked, reject with "Deploy target locked by task X"                                                                                                                                                                     
                                                                                                                                                                                                                                  
  Layer 3: Process Discipline (ongoing)                                                                                                                                                                                           
  
  For the operator (me)                                                                                                                                                                                                           
                                                                                                                                                                                                                                
  - Don't claim a fix is complete without QA validation                                                                                                                                                                           
  - Don't stop agents mid-work unless the system is actively breaking
  - Scope decisions must be explicit, final, and posted ONCE                                                                                                                                                                      
  - When intervening, diagnose ALL issues before deploying — not just the obvious one                                                                                                                                             
                                                                                                                                                                                                                                  
  For the agents                                                                                                                                                                                                                  
                                                                                                                                                                                                                                  
  - PF: batch fixes, self-test before QA, don't deploy partial work                                                                                                                                                               
  - Supervisor: less acking, more routing. 3 comments/hour max
  - QA-E2E: test against the COMMITTED build hash, not whatever happens to be live                                                                                                                                                
                                                                                                                                                                                                                                  
  ---                                                                                                                                                                                                                             
  The template rules are the fastest win — they address the deploy→fail loop, overnight autonomy, and supervisor noise directly. Want me to implement them in BOARD_AGENTS.md.j2 now?         



 Why PF never finishes — 4 root causes                                                                                                                                                                                           
                                       
  1. PF fixes one symptom at a time (iterative symptom-chasing)                                                                                                                                                                   
                                       
  Codex traced Phase 1C's sequence: org switcher → cache → testids → stale bundle → TEST_MODE → settings testids → name attrs. Seven deploys for what should have been one diagnosis pass. PF never reads the FULL QA report and  
  diagnoses ALL issues before deploying. Each deploy fixes the first thing QA mentioned.
                                                                                                                                                                                                                                  
  2. PF's fixes sometimes don't work or cause regressions                                                                                                                                                                         
  
  QA explicitly called index-CmlBnMyV.js a regression. PF's auth-routing "fix" still left authenticated users on /login. PF then blamed QA for being "unauthenticated" — QA contradicted with authenticated evidence. PF is not   
  always verifying its own fix works before deploying.
                                                                                                                                                                                                                                  
  3. Build drift — PF deploys to the wrong place or QA tests the wrong build                                                                                                                                                      
  
  The deployment target on .63 is not a git repo. PF deployed to the wrong directory path (DevOps had to fix it). QA repeatedly found a different live hash than what PF claimed. The operator's build was overwritten within     
  hours.                               
                                                                                                                                                                                                                                  
  4. Scope keeps moving                                                                                                                                                                                                           
  
  Phase 1C reached PASS on index-nidwUDk3.js (4/4), but then new criteria appeared (dashboard query invalidation, WhatsApp integration) causing fresh FAILs. Phase 1D was narrowed 3 times by different authorities (operator,    
  Supervisor, Architect) — each time changing what PF was targeting.
                                                                                                                                                                                                                                  
  Why QA always finds a bug                                                                                                                                                                                                       
  
  QA-E2E is actually doing its job correctly:                                                                                                                                                                                     
  - Uses authenticated testing (OTP/JWT)
  - Tests the live deployed build, not just what PF claims                                                                                                                                                                        
  - Reports specific failing criteria with evidence       
  - The FAILs are REAL — they're finding genuine issues                                                                                                                                                                           
                                                       
  The problem isn't QA finding too many bugs. It's that PF submits before verifying and the environment is unstable (build drift, wrong deploy path, scope changes).                                                              
                                                                                                                                                                                                                                  
  The "STOP ALL WORK" was ignored                                                                                                                                                                                                 
                                                                                                                                                                                                                                  
  Agents acknowledged the STOP at ~10:55 UTC but resumed deploying new builds within hours. Supervisor kept routing after STOP. The template rule is advisory — there's no enforcement mechanism in the gateway to actually freeze
   an agent.                           
                                                                                                                                                                                                                                  
  What would actually close these tasks                                                                                                                                                                                           
  
  Codex's recommendation (which I agree with):                                                                                                                                                                                    
                                       
  1. Lock the build: Deploy ONE build, verify QA can reach it at the correct URL, refuse to redeploy until QA PASSes or explicitly identifies all bugs                                                                            
  2. Freeze the acceptance criteria: No new requirements. Any new issue becomes a new task.
  3. PF must reproduce the QA flow: Before submitting, PF runs the EXACT same authenticated test QA will run, on the EXACT live build, and posts that evidence                                                                    
  4. STOP must be enforced: Use set-heartbeats {enabled: false} to actually freeze agents, not just post a comment they can ignore   


  Use codex to review and validate your assumptions and implementation 

  ┌─────────────────────────────────────────────────┬──────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                       Gap                       │  Status  │                                                            Why acceptable for now                                                            │
  ├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ board-stop.sh only stops heartbeats, not nudges │ Known    │ Full freeze needs MC API gate — future work. Heartbeat stop prevents 90% of autonomous activity.                                             │
  ├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Deploy Target Rule is advisory                  │ Known    │ BUILD HASH GATE at QA level provides enforcement — QA refuses to test mismatched builds                                                      │
  ├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ DIAGNOSIS format not machine-checkable          │ Accepted │ Human-readable is sufficient. Machine enforcement would need MC backend schema changes                                                       │
  ├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ No deploy lock acquisition in template          │ Known    │ Lock script exists on .63 but template doesn't mandate calling it. Deploy target in task description + QA hash gate is the enforcement layer │
  └─────────────────────────────────────────────────┴──────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

claude --resume 5d1faf84-b059-49c3-bfcc-49416c1d4a95

Features used via WhatsApp (NanoClaw/TaskFlow skill) vs Dashboard UI                                                                                                                                                            
  
  What users DO via WhatsApp (from real conversations):                                                                                                                                                                           
                                                                                                                                                                                                                                
  ┌─────────────────────┬─────────────────────────────────────────┬────────────────────────────────┬──────────────────────────────────────────────────────────────┐                                                               
  │       Command       │                 Example                 │            API Used            │                        Dashboard UI?                         │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ View project        │ P18, P2, p11                            │ GET tasks + filter             │ Partial — board view exists, no project drill-down           │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤
  │ Add subtask         │ P11 adicionar tarefa ...                │ POST tasks                     │ No — only "New Board" button, no task creation inside boards │                                                               
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Assign task         │ P18.3 atribuir para Beatriz             │ PATCH task                     │ No — no assignee picker in UI                                │                                                               
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Set deadline        │ prazo 07/04/26                          │ PATCH task                     │ No — no date picker in UI                                    │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Add note            │ P11.17 adicionar nota ...               │ POST comments                  │ No — no comment input in UI                                  │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ View person's tasks │ Tarefas Mauro, Atividades de Mariany    │ GET tasks filtered by assignee │ No — People panel shows names but no task filter             │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Process inbox       │ processar inbox, Inbox                  │ GET tasks?status=inbox         │ Partial — Kanban has Inbox column                            │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Change status       │ tirar de inbox e colocar como atividade │ PATCH task status              │ No — no drag-and-drop or status change                       │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Reassign            │ Reatribuir T-005 para Rafael            │ PATCH task assignee            │ No                                                           │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Approve/review      │ todas as atividades foram revisadas     │ PATCH task status to done      │ No — no approval flow in UI                                  │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ View overdue        │ quais tarefas estão sem prazo           │ GET tasks/overdue              │ Partial — overdue table exists on dashboard                  │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ View by status      │ tarefas do Mauro em revisão             │ GET tasks filtered             │ No — no combined filter (person + status)                    │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Cross-board         │ sec-t-004 prazo 30/04/26                │ PATCH across boards            │ No                                                           │                                                             
  ├─────────────────────┼─────────────────────────────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────┤                                                               
  │ Standup report      │ Automated [TF-STANDUP]                  │ GET stats + report             │ Partial — stats cards exist but no standup view              │                                                             
  └─────────────────────┴─────────────────────────────────────────┴────────────────────────────────┴──────────────────────────────────────────────────────────────┘                                                               
                                                                                                                                                                                                                                
  Summary of gaps                                                                                                                                                                                                                 
                                                                                                                                                                                                                                
  The dashboard is VIEW-ONLY. It displays boards, tasks, stats, and overdue items, but users cannot:                                                                                                                              
  
  1. Create tasks inside a board (only "New Board")                                                                                                                                                                               
  2. Edit tasks — no assignee, deadline, status, or priority changes                                                                                                                                                            
  3. Add comments/notes to tasks                                                                                                                                                                                                  
  4. Filter by person — "Show me Mauro's tasks"                                                                                                                                                                                 
  5. Filter by person + status — "Mauro's tasks in review"                                                                                                                                                                        
  6. Drag-and-drop tasks between columns                                                                                                                                                                                          
  7. Approve/reject tasks                                                                                                                                                                                                         
  8. View project hierarchy — drill into P18 → see subtasks P18.1, P18.2, P18.3                                                                                                                                                   
  9. Process inbox — bulk review/assign inbox items                                                                                                                                                                               
  10. Generate standup/digest reports                                                                                                                                                                                           
                                                                                                                                                                                                                                  
  The WhatsApp bot via NanoClaw is the primary interface — users do ALL their work there. The dashboard is only used for high-level monitoring (28 boards, 298 tasks, overdue chart).                                             


  Corrected Feature Audit (Codex-validated)                                                                                                                                                                                       
                                                                                                                                                                                                                                
  My claims that were WRONG                                                                                                                                                                                                       
                                                                                                                                                                                                                                
  ┌───────────────────────────────────────┬───────────────────────────────────────────────────────────────────┬─────────────────────────────┐                                                                                     
  │               My claim                │                         Codex correction                          │          Evidence           │                                                                                     
  ├───────────────────────────────────────┼───────────────────────────────────────────────────────────────────┼─────────────────────────────┤                                                                                     
  │ "No task creation inside boards"      │ Wrong — exists as "new task to inbox" flow                        │ page.tsx:1980               │                                                                                     
  ├───────────────────────────────────────┼───────────────────────────────────────────────────────────────────┼─────────────────────────────┤                                                                                     
  │ "No assignee/deadline/status editing" │ Wrong — all exist in the board detail UI                          │ page.tsx:2679, 4140         │                                                                                     
  ├───────────────────────────────────────┼───────────────────────────────────────────────────────────────────┼─────────────────────────────┤                                                                                     
  │ "No drag-and-drop"                    │ Wrong — already implemented                                       │ TaskBoard.tsx:305           │                                                                                     
  ├───────────────────────────────────────┼───────────────────────────────────────────────────────────────────┼─────────────────────────────┤                                                                                     
  │ "No approval flow"                    │ Wrong — BoardApprovalsPanel.tsx exists                            │ BoardApprovalsPanel.tsx:444 │                                                                                     
  ├───────────────────────────────────────┼───────────────────────────────────────────────────────────────────┼─────────────────────────────┤                                                                                     
  │ "No comments"                         │ Partially wrong — comments exist, but TaskFlow-native notes don't │ page.tsx:2598               │                                                                                     
  └───────────────────────────────────────┴───────────────────────────────────────────────────────────────────┴─────────────────────────────┘                                                                                     
                                                                                                                                                                                                                                  
  What's ACTUALLY missing (validated by conversations + code)                                                                                                                                                                     
                                                                                                                                                                                                                                  
  ┌──────────┬─────────────────────────────────────────────────┬──────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────┐                      
  │ Priority │                     Feature                     │          User frequency          │                                             Why it matters                                             │                      
  ├──────────┼─────────────────────────────────────────────────┼──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤                      
  │ #1       │ 6-column TaskFlow board (next_action + waiting) │ Every session                    │ Dashboard has 4 columns, TaskFlow uses 6. Users constantly reference "próximas ações" and "aguardando" │                      
  ├──────────┼─────────────────────────────────────────────────┼──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤                      
  │ #2       │ Inbox triage UI                                 │ ~44 captures + ~11 status moves  │ Users process inbox via WhatsApp with batch assign/deadline/action. No web equivalent                  │                      
  ├──────────┼─────────────────────────────────────────────────┼──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤                      
  │ #3       │ Search + filter by person/status/ID             │ ~69 lookups + ~15 person filters │ "Tarefas do Mauro em revisão", "P18.3", "quais tarefas sem prazo" — most frequent command category     │                      
  ├──────────┼─────────────────────────────────────────────────┼──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤                      
  │ #4       │ Project/subtask hierarchy                       │ ~44 creates + ~7 hierarchy ops   │ Users drill into P18→P18.1, P18.2, P18.3. Dashboard is flat                                            │                      
  ├──────────┼─────────────────────────────────────────────────┼──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤                      
  │ #5       │ TaskFlow-native notes                           │ ~19 note adds                    │ "adicionar nota..." is distinct from comments — notes are structured, editable, numbered               │                    
  └──────────┴─────────────────────────────────────────────────┴──────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────┘                      
                                                                                                                                                                                                                                
  What I missed entirely                                                                                                                                                                                                          
                                                                                                                                                                                                                                
  - next_action and waiting columns — the web board only has inbox/in_progress/review/done. TaskFlow has 6 GTD columns. This is the biggest UX gap.                                                                               
  - People registration — users register new team members via WhatsApp (cadastrar Rafael, telefone...). No web UI for this.
  - Recurring tasks — users create recurring tasks via WhatsApp. No web support.                                                                                                                                                  
  - Cross-board operations — users reference tasks from other boards (sec-t-004, sec-p24.1). Dashboard is single-board.                                                                                                           
                                                                                                                                                                                                                                  
  Usage frequency from real conversations                                                                                                                                                                                         
                                                                                                                                                                                                                                  
  Assignment/reassign:  ~101 commands                                                                                                                                                                                           
  Lookup/query:         ~69 commands                                                                                                                                                                                              
  Deadline changes:     ~45 commands
  Capture/create:       ~44 commands                                                                                                                                                                                              
  Notes:                ~19 commands                                                                                                                                                                                              
  Person filters:       ~15 commands
  Status moves:         ~11 commands                                                                                                                                                                                              
  Hierarchy/people:     ~7 commands                                                                                                                                                                                             
  Approvals:            ~2 commands                                                                                                                                                                                               
  
  The dashboard already has the low-frequency features (approvals, drag-and-drop) but is missing the high-frequency ones (search, filters, inbox triage, 6-column board).                                                         
                                                                                                                                                                                                                                                                                                                                                            
                                                                                                                                                                                 
                                                                                                                                                                                 Does the embenddings skill do the same work as https://github.com/redis-developer/openclaw-redis-agent-memory           
In resume what the Openclaw memory plugin does: auto-captures conversation summaries → stores in redis → auto-injects as <relevant-memories> on each tick based on semantic search.                                                                                                                                                                                 

⏺ Agents are ticking again. Gateway Agent (4m), PB (8m), Architect (13m), PF (17m), Supervisor (18m), DevOps (18m) — all active recently. The set-heartbeats {enabled: false} didn't stick. The gateway likely re-enabled them on
  a config reload or internal timer reset.                                                                                                                                                                                        
                                                                                                                                                                                                                                  
  The board-stop.sh approach is unreliable. To truly stop them, you'd need to either:                                                                                                                                             
  1. Pause the board via the MC API (/boards/{id}/pause)                                                                                                                                                                          
  2. Or restart the gateway with heartbeats disabled in openclaw.json                                                                                                                                                             
                                                                                                                                                                                                                                
  Want me to try the board pause API?                                                                                                                                                                                             
                                         

⏺ Let me break each feature into what MC needs to do to use it.                                                                                                                                                                   
                                                                                                                                                                                                                                
  1. Memory/Wiki — replace redis-memory                                                                                                                                                                                           
   
  What it is: Structured memory with claims/evidence fields, staleness detection, contradiction clustering, freshness-weighted search. Unlike redis-memory (semantic search on conversation dumps), wiki memory stores verified   
  facts with expiry dates.                                                                                                                                                                                                      
                                                                                                                                                                                                                                  
  How to enable:                                                                                                                                                                                                                
  openclaw config set plugins.slots.memory memory-wiki
  openclaw config set plugins.entries.memory-wiki.enabled true                                                                                                                                                                    
                                                              
  MC integration: No MC code changes needed — it's a gateway plugin. But MC could add a new RPC helper to query wiki memory:                                                                                                      
                                                                                                                                                                                                                                  
  # gateway_rpc.py — new helper                                                                                                                                                                                                   
  async def get_wiki_claims(agent_id: str, *, config: GatewayConfig) -> object:                                                                                                                                                   
      return await openclaw_call("doctor.memory.status", {"agentId": agent_id}, config=config)                                                                                                                                    
                                                                                                                                                                                                                                  
  Evaluation needed: Test if wiki memory solves the stale memory problem before enabling fleet-wide. The key question is whether agents produce good claims/evidence or noise.                                                    
                                                                                                                                                                                                                                  
  2. Heartbeat prompt controls — reduce template bloat                                                                                                                                                                            
                                                                                                                                                                                                                                
  What it is: Suppress heartbeat instructions from being injected every turn while keeping heartbeat runtime active.                                                                                                              
  
  How to enable:                                                                                                                                                                                                                  
  openclaw config set agents.defaults.heartbeat.promptGuidance false                                                                                                                                                            
                                                                                                                                                                                                                                  
  What changes: Currently HEARTBEAT.md (~2.3K chars) is injected into every heartbeat tick. With promptGuidance: false, the heartbeat still ticks but doesn't inject the HEARTBEAT.md content. The agent gets AGENTS.md (operating
   rules) but not the per-tick checklist.                                                                                                                                                                                         
  
  MC impact: If we disable prompt guidance, the HEARTBEAT.md template becomes unused. The agent would need the checklist in AGENTS.md instead (already mostly there — "Worker Execution Loop" section). This saves ~2.3K chars per
   tick, freeing context for task content.                                                                                                                                                                                      
                                                                                                                                                                                                                                  
  Tradeoff: Agents lose the per-tick setup vars ($BASE_URL, $AUTH_TOKEN, etc.) unless we move them to AGENTS.md.                                                                                                                  
  
  3. systemPromptOverride — controlled prompt experiments                                                                                                                                                                         
                                                                                                                                                                                                                                
  What it is: Inject a system prompt override via gateway config instead of workspace files.                                                                                                                                      
  
  How to use:                                                                                                                                                                                                                     
  openclaw config set agents.defaults.systemPromptOverride "You are a task management agent. Follow AGENTS.md strictly."                                                                                                        
                                                                                                                        
  Or per-agent:                                                                                                                                                                                                                   
  openclaw config set agents.list[1].systemPromptOverride "Custom PF instructions..."                                                                                                                                             
                                                                                                                                                                                                                                  
  MC impact: MC could use this for A/B testing template changes — set override for one agent, compare behavior with others. No code changes needed, just config.patch RPC.                                                        
                                                                                                                                                                                                                                  
  4. Webhooks plugin — external triggers                                                                                                                                                                                          
                                                                                                                                                                                                                                  
  What it is: HTTP endpoints that create/drive TaskFlows via shared-secret auth.                                                                                                                                                  
  
  How to enable:                                                                                                                                                                                                                  
  openclaw config set plugins.entries.webhooks.enabled true                                                                                                                                                                     
  openclaw config set plugins.entries.webhooks.config.routes '[{"path":"/deploy","secret":"..."}]'
                                                                                                  
  MC integration: MC backend could call the webhook to trigger agent work:                                                                                                                                                        
  # After a deploy completes, trigger QA validation                                                                                                                                                                               
  async def trigger_qa_webhook(build_hash: str, task_id: str):                                                                                                                                                                    
      await httpx.post("http://192.168.2.60:18789/webhooks/deploy",                                                                                                                                                               
          json={"build": build_hash, "task": task_id},                                                                                                                                                                            
          headers={"X-Webhook-Secret": "..."})                                                                                                                                                                                    
                                                                                                                                                                                                                                  
  MC code needed: New webhook trigger service + API endpoint for operator to configure webhook routes.                                                                                                                            
                                                                                                                                                                                                                                  
  5. Session branch/restore — recovery                                                                                                                                                                                            
                                                                                                                                                                                                                                  
  What it is: Persisted compaction checkpoints. Operators can inspect and restore pre-compaction state.                                                                                                                           
                                                                                                                                                                                                                                
  How to use: Available in Control UI (openclaw dashboard). No MC code needed — it's an operator tool.                                                                                                                            
  
  MC integration (optional): Could add a "Restore session" button to MC's agent management UI that calls the sessions.restore RPC.                                                                                                
                                                                                                                                                                                                                                
  6. Compaction provider — custom summarization                                                                                                                                                                                   
                                                                                                                                                                                                                                
  What it is: Replace built-in LLM compaction with a custom pipeline.                                                                                                                                                             
  
  How to configure:                                                                                                                                                                                                               
  openclaw config set agents.defaults.compaction.provider "custom-compactor"                                                                                                                                                    
                                                                            
  MC integration: MC could configure per-agent compaction models (e.g., fast model for Supervisor, thorough model for Architect). Uses config.patch RPC — no new MC code needed.                                                  
                                                                                                                                                                                                                                  
  7. Model fallback 404 fix — automatic after upgrade                                                                                                                                                                             
                                                                                                                                                                                                                                  
  No MC changes needed. After upgrading to 2026.4.8, HTTP 404 from model providers triggers the fallback chain instead of stopping. This improves resilience for our Ollama cloud models.                                         
                                                                                                                                                                                                                                
  ---                                                                                                                                                                                                                             
  Implementation priority                                                                                                                                                                                                       
                         
  ┌──────────┬──────────────────────────────┬─────────────────────┬──────────────────────────────────────┐
  │ Priority │           Feature            │       Effort        │                Impact                │                                                                                                                        
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤
  │ 1        │ Upgrade to 2026.4.8          │ openclaw update run │ Gets all fixes + new features        │                                                                                                                        
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                      
  │ 2        │ Heartbeat prompt controls    │ 1 config line       │ Frees ~2.3K chars per tick           │                                                                                                                        
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                        
  │ 3        │ Memory/Wiki evaluation       │ Enable + test       │ Could solve stale memory permanently │                                                                                                                        
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                        
  │ 4        │ Model fallback 404           │ Automatic           │ Better resilience                    │                                                                                                                      
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                        
  │ 5        │ Webhooks for deploy triggers │ New MC service      │ Automated QA after deploys           │                                                                                                                      
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                        
  │ 6        │ systemPromptOverride         │ Config only         │ A/B testing templates                │                                                                                                                      
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                        
  │ 7        │ Session branch/restore       │ Control UI          │ Operator recovery tool               │                                                                                                                      
  ├──────────┼──────────────────────────────┼─────────────────────┼──────────────────────────────────────┤                                                                                                                        
  │ 8        │ Compaction provider          │ Config only         │ Per-agent compaction tuning          │                                                                                                                      
  └──────────┴──────────────────────────────┴─────────────────────┴──────────────────────────────────────┘                                                                                                                        
                                                                                                                                                                                                                                
  Items 1-4 are config-only (no MC code). Items 5+ need MC development.                                                                                                                                                           
  
  Want me to upgrade and configure?   


Try again the test againt the Gemma4, maybe the same case, outputs to a thinking field, not response

 Programmer-Frontend Agent Analysis (2026-04-08)

  What the agent is working on

  Two tasks, both currently blocked:
  - Phase 2D: Project/subtask hierarchy view (9f32504c)
  - Phase 2E: TaskFlow-native notes on tasks (56f4737a)

  Deploy target: nanoclaw@192.168.2.63 / verify URL: http://192.168.2.63:3000/

  ---
  Root Cause: HTTP 404 on verify endpoint

  http://192.168.2.63:3000/ is returning 404 for both tasks. This is a shared infrastructure blocker — the target
  service/routing on that host is down or misconfigured. The agent confirmed this with curl, documented it on the board,
  and is correctly waiting.

  The supervisor already acknowledged this and classified it as a DevOps routing issue (not a code issue). The agent's
  response:
  ▎ "Holding both tasks on the shared live blocker. Will wait for target routing/service recovery or contradictory evidence
   before retrying live browser validation."

  ---
  The frequent resets are normal

  The session resets every ~20–80 minutes throughout the day — this is the openclaw control framework intentionally
  trimming context bloat. Not a failure signal.

  ---
  Is the agent actually failing?

  No — the agent is behaving correctly. It:
  1. Detected the 404 blocker independently
  2. Escalated to the supervisor (@lead)
  3. Is holding both tasks, not looping or spinning
  4. Awaiting DevOps intervention on the server at 192.168.2.63

  The real problem is infrastructure: the frontend deployment target (192.168.2.63:3000) is not serving, so the agent
  cannot verify any work it does. Until that service is up, both tasks are stuck in in_progress limbo.

  Action needed: Check why the service on 192.168.2.63:3000 is returning 404 — it may be down, misconfigured, or the deploy
   path changed.

     ┌─────────────────────┬───────────────────────────────────────────────────┬─────────────────────────────────────────────────┬────────────────────────────────────┐                                                              
  │       Source        │                   What it shows                   │                  How to access                  │                Size                │                                                              
  ├─────────────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────┼────────────────────────────────────┤                                                              
  │ Session JSONL files │ Every model turn — prompts, tool calls, responses │ /root/.openclaw/agents/<id>/sessions/*.jsonl    │ 142MB for PF, 180MB for Supervisor │                                                              
  ├─────────────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Gateway command log │ All gateway RPC calls                             │ /root/.openclaw/logs/commands.log (301KB)       │ Commands only                      │                                                              
  ├─────────────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────┼────────────────────────────────────┤                                                              
  │ Config audit log    │ Config changes                                    │ /root/.openclaw/logs/config-audit.jsonl (4.8MB) │ Config mutations                   │                                                              
  ├─────────────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────┼────────────────────────────────────┤                                                              
  │ openclaw logs       │ Real-time gateway log tail                        │ openclaw logs on .60                            │ Live stream                        │                                                            
  ├─────────────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────┼────────────────────────────────────┤                                                              
  │ Task comments       │ Agent posts to board                              │ MC API /tasks/{id}/comments                     │ What we've been reading            │                                                            
  ├─────────────────────┼───────────────────────────────────────────────────┼─────────────────────────────────────────────────┼────────────────────────────────────┤                                                              
  │ Board memory        │ Agent chat posts                                  │ MC API /boards/{id}/memory                      │ Inter-agent messages               │                                                            
  └─────────────────────┴───────────────────────────────────────────────────┴─────────────────────────────────────────────────┴────────────────────────────────────┘  

  What's the solution for Until Playwright auth works, no frontend task can close through QA.? 

  ---                                                                                                                                                                                                                                                                                   
 Phase 2E backend: persist task notes via TaskFlow API
Comment
Programmer-Backend
·
Backend Developer
·
Apr 8, 07:32 PM
Update

Local implementation complete: notes field added to TaskFlow API schemas, handlers, and DB migration in /root/.openclaw/workspace/taskflow-api/app/main.py
Tests pass: pytest -q tests/test_api.py -k notes -> 2 passed
BLOCKED on AC5 (live evidence): taskflow-api on .63:8100 does not have the notes deployment yet
Live .63:8100 OpenAPI does not show notes in task payloads
Evidence

Local code: grep -n notes /root/.openclaw/workspace/taskflow-api/app/main.py shows schema, parse, migration, PATCH logic
Tests: 2 passed, 72 deselected in 3.58s
Live check: curl -s http://192.168.2.63:8100/openapi.json -> notes NOT in CreateTaskPayload or UpdateTaskPayload
Request Now

Need deploy path/runbook for taskflow-api to .63:8100 from @DevOps or @Miguel
Once deployed, will run live PATCH+GET round-trip evidence for AC5
Next

Waiting on deploy access to complete AC5 and route to Architect @lead