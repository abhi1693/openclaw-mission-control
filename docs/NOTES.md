
Review the tasks waiting for approval, use Chome MCP, the expected behavior is fully compliance with the task spect, approve only after a thorough and robust verification of the evidence, cite the @supervisor on the final notification

Investigate why the agents aren't nudging each other as instructed

## 2026-04-28 — Pipeline event validation, structured review verdict skill, VP-05/VP-10 approval

### Pipeline event server-side validation (prod .64)
- **Reject incomplete events at creation time** — `POST /pipeline/events` now returns 422 with `task_pipeline_event_missing_required_fields` error when required fields are missing per `PIPELINE_REQUIRED_FIELDS_BY_STATE`. Applies to ALL task types (not just `frontend_ui`).
- **Merge flag** (`"overwrite": true`) — finds the most recent event for the same task+state and fills in null fields from the new payload. Existing non-null values are preserved. Falls through to insert if no merge target exists.
- Root cause of VP-05 pipeline block: not "null-commit ghost states" — the backend already filters incomplete events at query time via `pipeline_event_has_required_fields()`. The real issue was partial per-state fields (deployed with `deploy_target` but no `artifact_hash`). Fixed by appending corrective events, not deleting.

### Structured review verdict skill (gateway .60)
- **New skill** at `/root/.openclaw/skills/structured-review-verdict/SKILL.md` — teaches reviewing agents to call `POST /review-events` after posting verdict comments. Single source of truth for the structured review event API, field reference, role mapping, and nudge mechanism.
- **Gap found**: QA-E2E, QA-Unit, and Architect had inline review-event curls in `BOARD_AGENTS.md.j2`, but DevOps had none. DevOps posted verdict comments but never called the structured API, causing `review-readiness` to show `missing_roles=["devops"]`.
- **Template updated**: DevOps identity section (line 383), Architect section (line 768), and QA section header now reference the skill.
- **Nudge mechanism fix**: skill initially used `tags=["chat"]` for board memory nudge — `is_chat` field is read-only and cannot be set via create payload. Changed to `@lead` task comment (deliver=True).
- **E2E tested** with real agent tokens (DevOps, QA-E2E): 6/6 tests pass including auth, role enforcement, validation rejection, agent_id attribution, and nudge delivery.

### deliver=True on @lead mentions (prod .64, committed locally)
- `_notify_task_comment_targets` now uses `deliver=mentioned` — True for @-mentioned agents, False for passive updates. Supervisor immediately woken when agents include @lead in comments.
- Logs notification failures as `task.comment_notify_failed` activity events.
- **Known gap**: operator-posted comments go through the same `create_task_comment` route but `@supervisor` mentions may not match the agent name mapping. System event (`openclaw system event --mode now`) is the reliable workaround for operator-to-Supervisor wakes.

### VP task pipeline
- VP-05 (Hero trust line + background texture): Chrome MCP verified at 375/768/1440, approved, moved to done
- VP-10 (Deploy visual-polish batch): Chrome MCP verified (build hash match, 149ms load, 0 errors), approved, moved to done
- VP-06: In progress with PF (header language selector accessibility)
- VP-11: In progress with QA-E2E (visual regression sweep)

### hqctl client-side validation (gateway .60)
- Operator hardened `workspace/hqctl.py:245` to reject missing required fields before POST. 10 tests pass at `workspace/test_hqctl_pipeline.py`.

The HEARTBEAT.md order is:

Check in
Refresh API discovery
Lead Next Action Gate — /lead/next-action (should catch VP-03/VP-04 done-gate)
Memory Intake Gate — creates tasks from operator memories
Run rest of Lead Board Playbook
The Lead Next Action Gate (Step 3) runs before Memory Intake (Step 4). So the Supervisor should see approved_review_needs_done_gate in Step 3 and execute the PATCH to done BEFORE reaching Memory Intake.

But the Supervisor is doing Memory Intake canaries and "Sent question to lead" — which means it's either:

Skipping Step 3 entirely
Step 3 returns clear (no action needed) because the Supervisor already acted on a different task
The Supervisor processes Step 3 but the model doesn't execute the done-gate, then continues to Step 4



There it is — the rule only says "tag @lead" in prose (line 232 of HEARTBEAT.md for QA/Architect). There's no concrete nudge curl for workers or reviewers to nudge the Supervisor after completing work.

The memory file feedback_agents_must_nudge_supervisor.md says agents must nudge Supervisor, but the templates only have @lead prose mentions — no actual API nudge curl.

The deliver=True fix partially solves this: @lead mentions now wake the Supervisor immediately. But agents that don't include @lead in their comments won't trigger any notification.

The missing piece: a concrete nudge curl in the QA/Architect heartbeat section — "after posting your verdict, nudge the Supervisor." And in the worker section — "after moving to review, nudge the Supervisor."

But with deliver=True on @lead mentions, the prose @lead tag IS now functional — it triggers an immediate wake. The agents just need to consistently include @lead in their comments. Want me to verify that all verdict/evidence comments have @lead?



Supervisor heartbeated at 21:46 — 3 minutes after the @lead mention. It's alive but still not creating approvals. The Supervisor is fundamentally not converting inspect_review_gates + ready=true into an approval POST.

This is the model comprehension problem. The HEARTBEAT.md Step 3 says "Run Lead Next Action Gate" and the API returns the clear action, but the Supervisor model doesn't know the mapping: ready=true + approval_state=none → POST /approvals.

The AGENTS.md probably has this mapping, but the Supervisor isn't following it. This is the same "dog chasing tail" pattern — the instruction exists but the model doesn't execute.

The immediate unblock: I can create the approvals manually for VP-08/VP-09 so they can move to done, while we investigate why the Supervisor ignores the action.


The lead path (_apply_lead_task_update) calls _lead_apply_assignment and _lead_apply_status, but does NOT call _assign_review_task_to_lead. The auto-assign to Supervisor only happens in _finalize_updated_task (agent/admin path).

So when I (operator/lead) PATCHed VP-08/VP-09 to review, the lead path ran but skipped the auto-assignment to Supervisor. The tasks stayed assigned to whoever they were assigned to before — which was Architect (from my earlier manual assignment).

The normal flow would have been: PF PATCHes status=review → goes through agent path → _finalize_updated_task → _assign_review_task_to_lead → auto-assigns to Supervisor. My operator intervention broke this chain.

This is a consequence of operator bypass — when I intervened to move tasks to review because the Supervisor was dead, the auto-assignment didn't fire. In a healthy pipeline where PF moves tasks to review, the Supervisor would be auto-assigned correctly.



## 2026-04-13 — OpenClaw v2026.4.11/4.12 upgrade evaluation + context-overflow fix

### Verified post-upgrade
- **`tick timeout` keepalive fix (v2026.4.12)** — zero events on `.60` today, fix is preventative not curative
- **Cron heartbeat preservation (v2026.4.12)** — confirmed across both config touches AND a real OOM-kill restart at 18:34:56 UTC. All 9 agent heartbeat overrides survived (5m Supervisor, 10-40m others). The "manually re-set heartbeats after every config change" toil from `feedback_sigusr1_resets_heartbeats.md` is retired.
- **Active Memory plugin (v2026.4.12)** — silently auto-enabled by the upgrade. Visible in gateway startup log: "ready (11 plugins: acpx, **active-memory**, browser, device-pair, lossless-claw, memory-core, memory-wiki, phone-control, talk-voice, whatsapp, whatsapp-scheduler; 5.2s)". Contributes to memory pressure on top of exi
sting lossless-claw.

### Critical fix applied
- **`agents.defaults.contextTokens` bumped 128000 → 200000** to fix a context-overflow flood (50 events on Apr 13, 19 post-restart). Root cause: gateway pre-flight safe-threshold check uses the global `agents.defaults.contextTokens` budget; gpt-5.4 sessions were getting rejected at 32-200 messages because their estimated context exceeded 128k. Hot-reloaded at 18:25:41 UTC. Verified zero overflow events in the 10+ minutes since (vs ~3 events per 30-min window before).
- Backup: `/root/.openclaw/openclaw.json.pre-contextTokens-fix-20260413-181814`

### Schema discoveries (failed override paths, kept for future reference)
- `models.providers.openai-codex.models[]` → schema requires `baseUrl` + `models[].name` (not just `id`). Docs example was incomplete.
- `agents.defaults.models[<modelId>].contextTokens` (sibling of params) → rejected, "Unrecognized key"
- `agents.list[i].contextTokens` (per-agent) → rejected, "Unrecognized key"
- `params.contextTokens` (inside passthrough) → accepted but **passthrough-only, no effect on the safe-threshold check**
- **Only `agents.defaults.contextTokens` (global) actually affects the gateway's pre-flight overflow check.**

### Pre-existing issues surfaced during investigation (not fixed)
- **`minimax/minimax-m2.7` "Unknown model" errors — 381 occurrences today**, first at 05:53:40 (well before any of my changes). Cause: `models.providers.minimax` is **not registered in providers section at all**. References exist in 7 fallback chains (defaults + Architect + Programmer-Backend + QA-E2E + DevOps + Gateway Agent + Supervisor). Same pattern as openai-codex. When gpt-5.4 fails over, fallback chain hits "Unknown model" and falls through to ollama (which works) — degraded but functional.
- Dead passthrough params on `gpt-5.4`: `model_context_window: 1050000` and `model_auto_compact_token_limit: 200000` — added earlier in session under the assumption they'd be honored. They aren't. Should be cleaned up.

### Gateway OOM at 18:34:56 UTC (rolled back, not from my changes)
- Previous gateway PID 2541642 had been running since 15:20:08 UTC (~3h 14min uptime, 1.9GB memory at peak)
- Hit `--max-old-space-size=4096` ceiling, V8 OOM, systemd `Result: oom-kill`
- Auto-restart fired cleanly, new PID 2567051 since 18:35:01
- Memory now stable oscillating 800MB-1.0GB
- Likely contributors: `active-memory` plugin (auto-enabled by upgrade) + `lossless-claw` plugin (couldn't disable earlier) + 3+ hour accumulation. The contextTokens=200000 bump may have accelerated but isn't the root cause (took ~9 minutes from bump to OOM, gateway memory was already trending up before).
- Heartbeat preservation through OOM kill: ✓ verified

### Codex harness plugin investigation (deferred to maintenance window)
- New bundled Codex harness plugin from v2026.4.12 (`plugins.entries.codex.enabled = true`). Simpler config than the providers.codex path.
- Prerequisites all met on .60: `codex-cli 0.120.0` at `/usr/bin/codex`, `~/.codex/auth.json` present (Apr 12 19:08), gateway can read both.
- **Plugin enable requires gateway RESTART, not hot reload.** Tried at 18:33:16, gateway responded: "config change requires gateway restart (plugins.entries.codex) — deferring until 11 operation(s), 1 reply(ies), 2 embedded run(s), 14 task run(s) complete". Rolled back immediately to cancel the deferred restart.
- Migration would also require changing `model.primary` for each of 9 agents from `openai-codex/gpt-5.4` → `codex/gpt-5.4`. Per-agent updates, not bulk.
- Codex app-server reportedly handles compaction natively, may eliminate the need for the contextTokens bandage.

### Maintenance window TODO (do NOT execute without scheduling)
1. **Pause dev-squad board** before any restart
2. **Bump `NODE_OPTIONS=--max-old-space-size`** in `/root/.config/systemd/user/openclaw-gateway.service.d/node-options.conf` from `4096` to `8192` (gateway needs more headroom now that active-memory is loaded)
3. **Enable `plugins.entries.codex.enabled = true`** in same change
4. **Optionally disable active-memory plugin** (`plugins.entries.active-memory.enabled = false`) if user decides the memory cost outweighs the benefit
5. **One controlled restart** via `systemctl --user restart openclaw-gateway` to apply all 4 changes at once
6. **Verify after restart**: gateway PID changed, all 9 agents online, heartbeat overrides preserved, no schema validation errors, plugin loaded ("ready (12 plugins: ...codex...)" or similar)
7. **Test ONE non-critical agent** (DevOps or Gateway Agent) by changing its `model.primary` to `codex/gpt-5.4`, watch one heartbeat cycle
8. **If clean, expand migration** to remaining 8 agents in a single config patch
9. **If migration succeeds**, consider reverting `agents.defaults.contextTokens` from 200000 back to 128000 (Codex harness handles compaction natively)
10. **Resume dev-squad board**

### Pre-existing issues to fix (separate from above)
- Add `models.providers.minimax` provider entry with proper baseUrl + per-model declarations OR scrub `minimax/minimax-m2.7` and `minimax/minimax-m2.1` from all 7 fallback chains (Architect, PB, QA-E2E, DevOps, Gateway Agent, Supervisor, defaults)
- Clean up dead passthrough params on `agents.defaults.models["openai-codex/gpt-5.4"].params`: remove `model_context_window` and `model_auto_compact_token_limit` (no-ops)

### Files changed today on .60
- `/root/.openclaw/openclaw.json`: `agents.defaults.contextTokens` 128000 → 200000 (live)
- Backups: `openclaw.json.pre-gpt54-params-20260413-010625`, `openclaw.json.pre-context-params-20260413-011907`, `openclaw.json.pre-contextTokens-fix-20260413-181814`, `openclaw.json.pre-codex-plugin-20260413-183*`

## 2026-04-12 — Rework Column State Machine + Template Discipline

### Tier 3 — Dedicated `rework` task status (backend + template + frontend)
- **Problem**: Failed-review tasks were re-routed to `inbox`, causing the Supervisor to confuse them with new work and thrash (task `60a29e0f` bounced inbox↔review 8 times in 36 min)
- **Backend state machine** (`backend/app/api/tasks.py`): added `rework` to `ALLOWED_STATUSES` + `TaskStatus` Literal; lead can move `review → {done, inbox, rework}` with explicit-assignee-wins fallback; worker cannot PUT a task into rework (403); worker in rework can only move to `in_progress` or `inbox` (shortcut to review/done rejected); admin `review → rework` clears assignee if not explicit (prevents stranding on auto-assigned lead); both `POST /tasks` endpoints reject `status=rework` on create; `_notify_agent_on_task_rework` fires on review→rework in addition to review→inbox
- **Tests** (`backend/tests/test_task_agent_permissions.py`): 6 new cases — lead explicit assignee wins, fallback to last reviewer, worker cannot set rework, worker cannot shortcut rework→review, worker cannot shortcut rework→done, valid rework→in_progress pickup. All 19 permission tests pass
- **Codex (gpt-5.4) adversarial review** caught: worker shortcut holes, admin stranding on lead, TaskCreate rejection gap, template Jinja gate inconsistency, `board_group_snapshot.py` status ordering missing rework. All 5 must-fix items applied
- **Template** (`BOARD_AGENTS.md.j2`): Supervisor QA-FAIL routing now PATCHes `{status: rework, assigned_agent_id: DEV}` (was inbox); worker Step 3 pick rules Jinja-gated — implementation role prioritizes rework above inbox; Step 4 pickup prose + "do NOT work" guard include rework; QA/review roles never see rework instructions
- **Frontend** (`TaskBoard.tsx` + generated models): new amber Rework column; initially placed after Review (semantically wrong — implied Review→Rework→Done forward flow), then reordered to **Inbox → Rework → In Progress → Review → Done → Cancelled** to express actual backward flow (rework tasks go back to in_progress) and match template pickup priority
- Backend dirty files on `.64` quarantined to commit `911e086` before surgical deploy; 4 pre-rework backup files kept on server for rollback
- `mc-backend.service` + `mc-frontend.service` restarted; smoke test `POST /tasks {"status": "rework"}` returns 400 with correct error message; all 7 agents synced via Sync Templates API (board temporarily unpaused for the sync)

### Template stale-FAIL memory discipline (Tier 1/Tier 2 recovery)
- Added **Re-review rule** for reviewers: when a previously-reviewed task comes back after rejection, re-test NOT re-cite; required steps — read rejection comment, check `git log` since last review (no new commits → FAIL "no code changed since previous review"), re-run the SAME failing test in the browser for UI/functional ACs
- Added **structured DIAGNOSIS format** for workers after any rejection: verbatim rejection quote, root cause with file:line, fix applied with git diff summary, re-test evidence showing original failure no longer reproduces
- Added **git diff empty guard**: if diff since last-rejection-commit is empty, do not re-submit
- Added **functional evidence requirement**: ACs mentioning "functional", "works", "interactive", "switches", "toggles" need click+observe in browser, not just DOM presence
- Added **multi-reviewer handling**: when multiple rejections posted, address each one separately
- **3+ rejections escalation** extended to any reviewer (not just QA); board API blocks the 4th submission until `@Miguel` mention

### Template concurrent-overwrite incident
- Commit `990db7d` was intended to include 7 rework template edits but silent concurrent overwrite reverted them between Edit tool calls and `git add`
- Recovery commit `9cc09ac` restored the 7 edits (with compacted parentheticals to fit the 23000-char lead variant budget)
- A second concurrent overwrite added legitimate Tier 1/Tier 2 discipline content between `9cc09ac` and the next `git diff` check — committed as `5cbd8ad` since the additions filled the Tier 1 line-480 / Tier 2 gap that was drafted but never applied
- Added `feedback_template_read_after_write.md` auto-memory documenting the pattern for future sessions

## 2026-04-10 — TaskFlow API Codex Review Fixes

### TaskFlow API — Codex (gpt-5.4) Review + 6 Fixes
- **High**: Schema migrations in `ensure_support_tables` — `boards.owner_person_id` column + `board_id_counters` table with composite PK
- **Medium**: `/auth/me` backfill UPDATE runs on separate `read_only=False` connection, guarded with `WHERE name IS NULL OR name = ''`
- **Medium**: `_resolve_person_id` rewritten — requires 9+ digits, pre-filters on last 9 in SQL, confirms full-digit equivalence in Python, returns None on ambiguity (no silent LIMIT 1 mis-mapping)
- **Low**: `TaskNotePayload.normalize_fields` strips whitespace before emptiness check
- **Low**: Debug `traceback.print_exc()` replaced with `logger.exception()`
- 76 tests pass (71 original + 5 new regression tests)
- Gateway Agent recovered — was stale since Apr 8, heartbeat sent, now online
- Board agent heartbeat intervals doubled (except Supervisor 5m, Gateway 10m)

## 2026-04-09 — TaskFlow Dashboard Fixes + WhatsApp Notifications + Cancelled UI

### TaskFlow Dashboard Layout Restoration (.63)
- Restored last-week's kanban layout broken by agent deploy drift (DevOps rsync --delete)
- Columns default expanded (not auto-collapsed when empty)
- Columns sized to content (items-start) with maxHeight cap for scrollbar
- Gray bg-slate-200 backdrop restored, horizontal scrollbar at viewport edge
- People panel overflow-y-auto for large teams (Seci 13 members)
- Cancelled column removed from TASK_COLUMNS, kept in type

### TaskFlow Dashboard UX Improvements (.63)
- Personal boards aggregate tasks from parent board (assigned to owner)
- Orphan subtasks render as top-level cards when parent not in same column
- Board owner name hidden on own cards (uses owner_person_id from DB)
- Delegation chain resolution: non-member assignees resolved to board member via subtasks
- Parent project title shown on subtask cards (P1 - Migração SEI)

### TaskFlow API Enhancements (.63)
- WhatsApp notifications via NanoClaw IPC: task create, move, reassign, comment
- Unified task ID counters: uses board_id_counters (same table as NanoClaw engine)
- /auth/me resolves person_id, role from board_people via phone matching
- Board filtering by owner_person_id + descendants (BFS traversal)
- parent_task_title subquery in fetch_tasks (cross-board)
- VALID_COLUMNS includes cancelled

### MC Dashboard Cancelled UI (.64)
- AC6: Cancel button in task detail footer with confirmation
- AC7: window.confirm before cancel
- AC8: Cancelled column hidden by default
- AC9: Toggle in board configuration/edit page (DB-backed show_cancelled_column)
- AC10: Strikethrough title + muted opacity + red border on cancelled cards
- API types updated: TaskCardReadStatus, TaskUpdate include cancelled
- StatusDot includes cancelled color

### MC Frontend Systemd Fix (.64)
- Fixed mission-control.service: corrected WorkingDirectory, ExecStart, .env path
- Fixed .next/ ownership (root → mcontrol)
- Service enabled for auto-start on boot

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




  Do you want me to proceed with appending the auditor-fix entry to .claude/skills/add-taskflow/CHANGELOG.md on this assumption, or pause here? 

  Do you want me to proceed with appending the auditor-fix entry to .claude/skills/add-taskflow/CHANGELOG.md on this assumption, or pause here

    Architectural note. The cleaner long-term fix is to stop inferring DM-send success from task_history altogether and add a verifiable send signal. Best version: emit an audit trail for send_message tool calls. Acceptable fallback: cross-check messages.db for bot outbound        
  messages to non-origin chats within the window and correlate by target JID or content snippet. Codex flagged this as the "right" direction; what I shipped is a noise-reduction patch, not a verification patch.

  heartbeats RPC path 

    1. Deploy. The commit is local-only. ./scripts/deploy.sh will rsync dist/ + container/agent-runner/src/ + groups/ to production when you're ready. (Not pushed — per your standing policy I haven't touched git remotes.)                                                             
  2. skill/taskflow refresh. Documented in the CHANGELOG as an outstanding housekeeping task. skill/taskflow is still 90 commits behind main. Whenever you want to tackle it, I can plan + execute the catch-up.                                                                        
  3. Architectural follow-up. Codex's "right fix" — emit a verifiable audit trail for send_message tool calls, so we can actually verify cross-group sends instead of regex-exempting them. Deferred to a separate, larger task.                                                        
  4. Commit author identity — git warned that it used a fallback root <root@nanoclaw.mylocal> identity. If you want the commit to be attributed to a specific name/email, let me know and I can amend it (or you can git commit --amend --reset-author yourself after setting user.name
  / user.email).   


   When an LLM-native approach would be right                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                                       
    If you wanted to replace the regex with an LLM, the right design would be a separate, small-model prefilter (e.g., Haiku) that classifies each message into {dm_send, task_write, both, neither} once at ingest time and writes the label into messages.db. Then the auditor would
    read the stored label instead of running regex. That's a legitimate future direction — it's closer to the "emit a verifiable send_message audit trail" item in the deferred follow-ups. But it requires a schema change, a backfill, and a new ingest-time pipeline. The regex fix 
    is the right short-term move because it's a 6-line patch that closes the active false-positive without touching the data model.                                                                                                                                                    
                                                                                                                                                  
    Short version                                                                                                                                                                                                                                                                       
                                                                                                                                                  
    The regex lives in a non-LLM pre-filter whose job is cheap deterministic triage. The LLM downstream trusts the pre-filter's labels. Plural imperatives slipping through the regex means the LLM gets lied to, not that the LLM is failing to understand Portuguese. The minimal fix 
    restores the pre-filter's recall until we're ready to replace it with an ingest-time classifier — which is a bigger, separately-scoped change.  

      Commit still lands as root <root@nanoclaw.mylocal> — same as 391226b. Not pushed. The open follow-ups from last round still stand:                                                                                                                                                    
  1. Deploy — ./scripts/deploy.sh                                                                                                                                                                                                                                                       
  2. skill/taskflow refresh — now 91 commits behind                                                                                                                                                                                                                                     
   PB simply chose to code directly instead of delegating. There's no technical blocker — it's a model behavior choice. GPT-5.4 read the skill, had sessions_spawn available, had SSH access, and still decided to implement directly.                                                   
                                                                                                                                                                                                                                                                                        
  The fix is stronger template language — the AGENTS.md should not just say "use the skill" but should make it a hard rule: "You MUST delegate via sessions_spawn. Direct coding via exec/ssh is NOT allowed for implementation work."                                                  
                                      
  Want me to add that guardrail?   






  Three-agent template review — aggregated findings                   
                                                                                                                                                                                                                                                                                      
  Overall: 12 HIGH / 23 MEDIUM / 17 LOW across all three reviews. The template is largely correct on action names and engine semantics but has real bugs in a handful of specific rows and significant drift from user-facing docs.                                                     
                                                                                                                                                                                                                                                                                        
  HIGH priority issues (shipped bugs that will cause real failures or user-bot divergence)                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                        
  Engine alignment (1 HIGH):                                                                                                                                                                                                                                                            
  - L303-L307 manage_holidays uses wrong parameter names. Template says operation: 'add' with date: 'YYYY-MM-DD', but engine (ipc-mcp-stdio.ts:940) requires holiday_operation (not operation), holidays: [{date, label?}] array (not single date), holiday_dates array (not single
  date), and holiday_year (not year). Every holiday call the agent issues verbatim will fail.                                                                                                                                                                                           
                                                                                             
  Internal consistency (4 HIGH):                                                                                                                                                                                                                                                        
  - L1015-L1017 Batch Operations table lists cancel under taskflow_move actions, but cancel is a taskflow_admin action (cancel_task) everywhere else in the template.                                                                                                                   
  - L423 references "Board View Format" section that doesn't exist (actual content is at L715 under "Rendered Output Format").                                                                                                                                                          
  - L30 vs L532 give contradictory formulas for "can this board create a child board" — level + 1 < max_depth vs level < max_depth. The two flip for any parent-level board at max depth.                                                                                               
  - L258 "estender RXXX por mais N ciclos" tells the agent to do CURRENT_CYCLE + N arithmetic, but Schema Reference at L833 declares current_cycle TEXT (JSON object) — arithmetic on a JSON object.                                                                                    
                                                                                                                                                                                                                                                                                        
  Cross-document drift (7 HIGH):                                                                                                                                                                                                                                                        
  - revisao command mismatch: template maps bare revisao → weekly report (L525), but user manual maps @Case revisao → Review column query. Users will get the wrong thing.                                                                                                              
  - reparent/detach verbs: template teaches "mover T5 para projeto P10" / "desvincular T5 do projeto"; manual teaches "mover T001 para dentro de T002" / "destacar T001.1". Zero overlap. destacar never appears in the template.                                                       
  - cadastrar flow: template L286/L532 requires a hidden division/sigla question; manual L443 documents cadastrar as a 3-field command with no sigla follow-up. Users blindsided.                                                                                                       
  - Inbox one-shot shortcut "T1 para Alexandre, prazo sexta": in user manual L374, not in template at all.                                                                                                                                                                              
  - add_external_participant field name: template uses name, meetings-reference uses display_name.                                                                                                                                                                                      
  - remove_external_participant shape: template passes { name: 'Maria' }, meetings-reference passes external_id as a string.                                                                                                                                                            
  - scheduled_at timezone: template (L319) says local, no Z; meetings-reference (L13, L43, L164, L196) says "ISO-8601 UTC" with Z examples. Memory backs the template but the doc needs to catch up.                                                                                    
                                                                                                                                                                                                                                                                                        
  MEDIUM issues (summary)                                                                                                                                                                                                                                                               
                                                                                                                                                                                                                                                                                        
  - Three conflicting names for "create child board": create_group IPC tool vs provision_child_board MCP tool vs taskflow_admin register_person → auto_provision_request flow (L30, L874, L861).                                                                                        
  - Subtask-update contradiction: table mostly passes parent-ID for subtask operations, but one row passes subtask-ID directly, and L264 says "always use subtask-ID". Three different conventions.
  - boards, external_contacts tables referenced in SQL fallback examples but not in Schema Reference — agent has nowhere to look up the columns.                                                                                                                                        
  - Template mentions reassign confirmed: false shortcut for bulk but skips explaining that taskflow_admin has no dry-run mode — agent might drop confirmed: false from reassigns too.                                                                                                  
  - User manual says column is 👁️  Revisão, template says 🔍 Revisão; operator-guide's sample board shows English column labels.                                                                                                                                                         
  - Próxima Ação vs Próximas Ações (singular vs plural) — template plural, manual singular.                                                                                                                                                                                             
  - Meeting return action documented in meetings-reference but missing from template's Meeting Movement row.                                                                                                                                                                            
  - mudancas/feriados/como está?/status command aliases in user manual, no template mapping.                                                                                                                                                                                            
  - SKILL.md claims template is ~400 lines; actual is 1124. SKILL.md also references CLAUDE.md.template.v1 rollback file that no longer exists.                                                                                                                                         
  - Template teaches INSERT INTO attachment_audit_log (L1118) but operator-guide + feature matrix mark the table as dormant/stale-in-prod.                                                                                                                                              
                                                                                                                                                                                                                                                                                        
  LOW (cosmetic / no behavior impact)                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                                                        
  - Undefined placeholder conventions (TARGET_ID, CURRENT_CYCLE, YESTERDAY_ISO, EXT_ID, FREQ used without introduction)                                                                                                                                                                 
  - Mixed code-fence language tags (only sql tagged explicitly, other 40+ fences bare)
  - Task-ID example format: template uses T1/M1, user manual T001/M001, quick-start TXXX — all accepted by engine, cosmetic only                                                                                                                                                        
  - L846 "All timestamps: ISO-8601 UTC" blanket statement conflicts with repeated local-time guidance (stored=UTC vs wire=local, template never states this explicitly)                                                                                                                 
  - Meeting phase mapping: template adds done → post, meetings-reference only documents through review → post (template more complete, not a bug)                                                                                                                                       
                                                                                                                                                                                                                                                                                        
  Verified correct (no findings)                                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                                        
  The engine-alignment agent verified ~60 factual claims against the actual code: all action vocabularies (taskflow_move, taskflow_admin, taskflow_hierarchy, taskflow_dependency), all column names, task types, recurrence frequencies, priority enum, undo window semantics,         
  offer_register / requires_confirmation / wip_warning response shapes, WIP enforcement points, meeting note phase mapping, schema column names, duplicate-detection thresholds, force_create override, reparent_task/detach_task requirements, external invite flow, IPC tool shapes,
  and more. The core template is factually accurate — the bugs are concentrated in a specific set of rows.                                                                                                                                                                              
                                                            
  Recommended action priority

  1. Fix the 5 HIGH bugs first (1 engine + 4 internal) — these break real commands                                                                                                                                                                                                      
  2. Reconcile revisao, reparent/detach verbs, cadastrar flow with user manual — pick canonical form
  3. Fix add_external_participant/remove_external_participant shape with meetings-reference + engine                                                                                                                                                                                    
  4. Either update SKILL.md line count or accept that it's stale metadata                                                                                                                                                                                                               
  5. Decide on column emoji (👁️  vs 🔍) and Próxima/Próximas pluralization across all sources    




Goal: Design a 3-page web presence for Nanoclaw's Taskflow Skill product, developed by the MC Squad Team.
Step 1 — Research & Context Gathering

Documentation & Skill codebase: Access the .160 development machine to read Nanoclaw's Taskflow Skill user documentation and understand the product's features, architecture, value proposition, and target audience.
Frontend UI codebase: Access the .63 production machine to review the existing Taskflow Mission Control UI — note current design patterns, components, and UX conventions already in use.
Design reference: Use Chrome MCP to visit https://dribbble.com/shots/23360548-TaskFlow-A-SasS-template-design — extract from the image of the layout, layout patterns, color palette, typography, and component styles for inspiration.

Step 2 — Plan & Design
Using the frontend design skills, create a detailed plan and build three pages that align with the existing Mission Control UI while elevating the visual style based on the Dribbble reference:

Landing Page — Hero section, key features, social proof, and CTA. Conversion-focused first impression.
Product Page — Deeper feature breakdown, screenshots/demos, pricing or plans, and use cases.
Documentation Page — Clean, navigable docs layout with sidebar, code examples, and search-friendly structure.

Environment Reference:

.160 (dev) — Taskflow Skill codebase & documentation
.63 (prod) — Taskflow Mission Control UI (frontend)

Constraints:

Team: MC Squad Team
Style: SaaS-modern, clean (Dribbble reference), consistent with existing Mission Control UI (to be improved too)
Output: Working React or HTML artifacts for each page        



  What's NOT done                                                                                                                                                                                                                                                                       
                                                                                                                                                                                                                                                                                        
  - Step 2 (codex harness) is still pending. Open question: do you want to wait and observe whether strict-agentic alone is enough before committing to the bigger change with the gateway restart + compaction-config unknown? 




  The real fix is finding what's leaking (likely
   lossless-claw conversation accumulation, or memory-core's vector store, or whatsapp-scheduler's context cache)








   How to solve this: Between v2 and v3 the Architect's session ended and restarted. The new session's model prior ("for a marketing SPA with routing and SEO concerns, default to Next.js app router") weighted heavier than the thread history I'd pinned. The coordination task I created has the Vite-only rule in its description, but the Architect's heartbeat loop apparently doesn't re-inject the full task description — it works from a summarization, and the summarization lost the word "Vite-only".

Compounding this: the v3 plan also hallucinated a Status page that was never in the original spec. That's the model filling in a plausible 3-page web presence from scratch ("Landing / Docs / Status") rather than re-reading the original task c5c5a6a6 which specified Landing / Product / Docs. So the Architect on its third tick didn't just drift on the framework — it drifted on the entire product definition, because its context summary was lossy on both dimensions.


hard_constraints schema column — deferred as codex suggested. The immediate defect is prompt visibility, not storage. Revisit if post-patch behavior still drifts.



The honest tradeoff: Vite SPA has worse SEO and worse image delivery out of the box. If you add prerendering (vite-plugin-ssg or migrate to Astro) and vite-imagetools, you close most of the gap. If this is a real marketing site that needs to rank on Google and show nice link previews on social, Next.js SSG would be meaningfully better. If it's an internal landing page or documentation, Vite is fine.

My recommendation: for a public marketing site, I'd actually pick Astro over both — it uses Vite under the hood, gives you zero-JS static pages by default (perfect for marketing), file-based routing, image optimization, and you can drop React components in where you need interactivity. But your team already invested in the Vite tree and the hard constraint is "Vite only" — so sticking with Vite is fine as long as you add SSG/prerendering later if SEO becomes a concern.



