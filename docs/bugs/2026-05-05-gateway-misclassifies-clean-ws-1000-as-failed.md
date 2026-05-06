# Gateway misclassifies clean ACP child terminal as `failed` when WebSocket closes with code 1000

**Filed:** 2026-05-05
**Component:** OpenClaw gateway (`.60`) — task-runs persistence layer (`/root/.openclaw/tasks/runs.sqlite`)
**Severity:** HIGH (causes false-positive operator BLOCKERs on successful child runs)
**Reproduced on:** OpenClaw v2026.4.x running on `192.168.2.60`, MC backend on `192.168.2.64`

## Symptom

ACP child agents that complete their work successfully are recorded in the gateway's `task_runs` table with `status='failed'` and `error='WebSocket closed 1000'` whenever the upstream WebSocket closes cleanly (RFC 6455 normal closure) after the child returned its final response. The on-disk artifacts (commits, evidence files, screenshots) match the child's transcript, but the parent agent reading `task_runs` sees the run as failed and posts a BLOCKER.

## Concrete reproducer

Mission Control board `05002170-201b-4c66-bae1-26c0c833f206`, task `fcfa94f1-9800-45d2-9e5c-86a682bd6334` (Phase 3 / E.05 — Docs code-block syntax highlighting), 2026-05-05 23:33–23:42 UTC:

1. Programmer-Frontend (`3461451b-...`) spawned ACP child `mc-task-fcfa94f1-impl-a2` →  `agent:claude:subagent:eb9454aa-e369-4d78-912c-a6e29869273f` at `23:33:21Z`.
2. The child ran end-to-end inside `/tmp/wt-fcfa94f1/taskflow-web-presence-vite`:
   - Added `prismjs` dep + custom `taskflow-command` Prism grammar.
   - Wrote `tests/docs-code-highlighting.spec.js` covering en/pt/es/fr.
   - Captured `artifacts/docs-code-highlight/docs-code-highlight-{en,pt,es,fr}.png` from a Playwright run, plus `docs-code-highlight-live-evidence.json` (`highlightedBlockCount: 6`, `consoleMessages: []`, `failedRequests: []` per locale).
   - Ran `git commit -m "Add docs code syntax highlighting"` at `23:41:55.309Z` → SHA `73e3adb`.
   - Killed its own vite-dev server (`pkill -f 'vite --host 0.0.0.0 --port 3002'`).
   - Posted a final assistant text summary at `23:42:23Z` and let the WebSocket close.
3. `task_runs.sqlite` recorded the run as:
   ```
   label=mc-task-fcfa94f1-impl-a2
   status=failed
   delivery_status=pending
   started_at=2026-05-05 23:33:21Z
   ended_at=2026-05-05 23:36:19Z   ← gateway-recorded end is ~6 minutes early
   error=WebSocket closed 1000
   ```
4. Programmer-Frontend posted `BLOCKER: Two ACP children failed on E.05` at `23:39:19Z`, two minutes BEFORE the child actually committed.
5. Supervisor accepted the BLOCKER framing and chose option (1) "increase timeout, retry with bigger ACP payload" at `23:43:44Z`. The retry is wasted work — the implementation is already on disk at `73e3adb`.

## Why the misclassification happens

Per [`backend/app/models/gateway_session_state.py:52`](../../backend/app/models/gateway_session_state.py#L52) (MC's projection of the gateway's broadcast snapshot), the authoritative ACP completion signal is `last_status` from the `subagent-status` lifecycle event — `done` / `failed` / `timed_out` / `running`. The gateway-side `task_runs.status` adapter, however, appears to write `failed` whenever the child WebSocket closes with code 1000 before a `subagent-status: done` event has been observed by the persistence layer.

Two ways this can happen on a successful run:

1. The child's final assistant text response is the last frame on the wire; the child then exits cleanly, which closes the WS with code 1000. If the gateway's persistence layer has not yet processed (or never receives) a separate `subagent-status: done` lifecycle event, it falls back to interpreting the WS close as a failure.
2. The gateway's `ended_at` timestamp lags: in this incident `ended_at=23:36:19Z` was recorded ~6 minutes before the agent's actual `git commit` and final summary. So the persistence layer "ended" the run while the child was still actively producing artifacts that did land on disk.

`error="WebSocket closed 1000"` is RFC 6455 normal closure — explicitly NOT an error condition at the transport level. Surfacing it as `error` and `status=failed` is a layer mismatch.

## Impact

- **False BLOCKERs.** Parent agents read `task_runs` and report failures to the lead. Operators waste cycles rerouting work that's already done.
- **Wasted retry cost.** Supervisor's natural reaction is "increase timeout, respawn"; each respawn is a full ACP child runtime that duplicates already-completed work.
- **Worktree drift.** Successful commits like `73e3adb` sit unmerged on a branch named after the task (`wt/fcfa94f1`) while a parallel a3 spawns its own implementation in the same worktree, risking conflicts.
- **Operator confidence.** Repeated false failures on the Phase 3 children erode trust in the gateway's run-state truth.

## Suggested fix

The gateway's persistence layer should treat the run terminal status as:

- **`done`** if at least one `subagent-status: done` lifecycle event was received for the run, regardless of WS close code.
- **`done`** if the WS closed with code 1000 AND the child produced any tool output AND no terminal lifecycle event marked it `failed`/`timed_out`/`aborted`. (This is the conservative "default to success on clean close" rule.)
- **`failed`** ONLY if the gateway received an explicit `subagent-status: failed`, an explicit `aborted` event, or the WS closed with a non-1000 code.

The `error` column should remain NULL on clean WS close. `WebSocket closed 1000` is not an error message and surfacing it under `error` confuses every consumer.

If the persistence layer cannot reliably observe the `subagent-status` event (e.g., timing race with WS close), it should at minimum reconcile against the on-disk transcript: the child's session jsonl ends with an assistant text frame and a clean stdin close on success, vs. an `error`/`abort` frame on failure.

## Forensic queries

```bash
# Pull the false-failure row.
sqlite3 /root/.openclaw/tasks/runs.sqlite \
  "SELECT label, status, error, started_at, ended_at FROM task_runs \
   WHERE child_session_key = 'agent:claude:subagent:eb9454aa-e369-4d78-912c-a6e29869273f';"

# Verify the child actually completed by reading the transcript tail.
tail -3 /root/.openclaw/agents/claude/sessions/5c7cf444-5ff9-46c9-ae61-4a24c7626d80.jsonl

# Verify the on-disk artifact matches the run.
cd /tmp/wt-fcfa94f1/taskflow-web-presence-vite && git show --format=fuller --stat 73e3adb
```

## Related

- Mission Control issue: false PF BLOCKER on E.05 (2026-05-05). Operator left Supervisor's a3 retry in place rather than override.
- ACP completion contract: [`gateway_session_state.py:52`](../../backend/app/models/gateway_session_state.py#L52) — `last_status` under `subagent-status` is the authoritative signal.
- ACP post-review skill ([`backend/skills/acp-post-review/SKILL.md`](../../backend/skills/acp-post-review/SKILL.md)) already requires the parent to inspect child output as evidence rather than trusting the gateway run-status verbatim. Aligning the gateway's run-status with the actual completion signal would let parents trust it again.
