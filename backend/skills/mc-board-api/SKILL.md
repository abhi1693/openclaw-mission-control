---
name: mc-board-api
description: Use when posting comments, recording pipeline events, or filing reviewer verdicts to the Mission Control board API — instead of hand-rolling curl with the auth token. Replaces the curl-pattern in ACP children, scripts, and any agent that talks to MC's task endpoints.
---

# Mission Control Board API — typed access for ACP children

Two equivalent typed surfaces are available, depending on whether you're
calling MC from inside an ACP child (with MCP tool support) or from a
plain bash environment (CLI). Both wrap the same MC endpoints with the
same auth/board enforcement.

| Surface | When to use | Auth source |
|---|---|---|
| **MCP tools** (preferred for ACP children) | Inside Claude/Codex/OpenCode ACP children — MCP tools are typed, validated, and surface in the agent's tool list | Provided by ACPX spawn parent via env |
| **CLI** at `/usr/local/bin/mc_client.py` | Bash scripts, manual operator runs, automation that doesn't go through ACP | Same env vars |

## MCP tools (preferred when available)

When ACPX is configured with the MC MCP server (see "Wire-up" below),
ACP children automatically see four tools:

- `mc_task_read({ task_id })` → returns the task envelope
- `mc_comment_create({ task_id, message })` → posts a comment
- `mc_pipeline_event_create({ task_id, state, ...optional })` → records a pipeline event (`code_changed`, `committed`, `built`, `deployed`, `live_build_verified`, `runtime_verified`, `qa_ready`, `model_fallback`)
- `mc_review_event_create({ task_id, reviewer_role, verdict, ...optional })` → posts a structured review verdict (`pass | fail | inconclusive | infra_blocked`)

Tool input schemas constrain enum-valued fields (state, verdict,
reviewer_role) to the real MC schema Literals — if you pass an invalid
value the MCP host rejects the call before it reaches MC.

### Wire-up (operator action; restart-required)

Add the MC MCP server to ACPX's `mcpServers` config:

```bash
openclaw config set plugins.entries.acpx.config.mcpServers.mc-board-api '{
  "command": "python3",
  "args": ["/usr/local/bin/mc_mcp_server.py"],
  "env": {
    "LOCAL_AUTH_TOKEN": "<bearer token>",
    "BOARD_ID": "<board uuid>",
    "MC_BASE_URL": "http://192.168.2.64:8000"
  }
}' --strict-json
```

This change lives at `plugins.entries.acpx.config.*` — an
agent-context path that follows the **in-memory authority** model. The
file edit lands immediately, but the gateway will not pick it up until
its in-memory representation is refreshed by a restart cycle. **Do
not casually run `openclaw gateway restart` from this skill.** Restart
kills heartbeat scheduling for every agent (per
`feedback_acp_default_restart`) and aborts active ACP child runs in
the deferred-drain queue.

The right operator workflow:

1. Check current heartbeat state (`jq '.agents.list[] | select(.heartbeatsEnabled==true) | .id' /root/.openclaw/openclaw.json`).
   If all are `false`, the restart cost is essentially zero.
2. Drain or accept the cost of any active ACP child runs.
3. Trigger a restart at a planned window (typically `openclaw gateway
   restart` from the operator's session, OR the next natural restart
   cycle from an unrelated config change).
4. Verify the new MCP server is loaded by spawning a test ACP child
   and listing tools.

After the restart actually fires, every ACP child the gateway spawns
has `mc_*` tools available. Children should call them directly rather
than building curl strings.

## CLI alternative (plain bash environments)

A Python helper at `/usr/local/bin/mc_client.py` exposes the same MC
board endpoints as typed CLI subcommands. **Use this instead of constructing
`curl` commands by hand.** The CLI handles auth, JSON encoding, error
classification, and stays in sync with the real schema (verdict choices,
pipeline state names, evidence-key requirements).

## When to use

- Posting a task comment.
- Recording a structured pipeline event (`code_changed`, `committed`,
  `built`, `deployed`, `live_build_verified`, `runtime_verified`,
  `qa_ready`, `model_fallback`).
- Filing a reviewer verdict (`pass`, `fail`, `inconclusive`, `infra_blocked`).
- Reading a task's status / description / priority.

## When **not** to use

- Mutating task status (PATCH `/tasks/{id}`) — that's role-specific and
  often gated by board rules. Keep using your existing pattern for status
  changes.
- Approval create / unblock / patch — these have their own discipline
  (approval freshness, lead-only gates). Use the canonical approval flow
  documented in `lead-review-routing` and `architect-review-verdict`.
- Operating on a different board than your assigned one — the CLI
  enforces that the `BOARD_ID` env var matches the request.

## Required environment

Already present in every ACP child spawned by the standard flow:

| Var | Source | Notes |
|---|---|---|
| `LOCAL_AUTH_TOKEN` | spawn parent | bearer token; passed via `--token` if absent |
| `BOARD_ID` | spawn parent | board UUID; passed via `--board` if absent |
| `MC_BASE_URL` | optional, defaults to `http://192.168.2.64:8000` | passed via `--base-url` |

If any of these is missing, the CLI exits with a clear message instead of
silently posting to the wrong place. Re-export them from the spawn parent's
env before invoking.

## Subcommands and canonical examples

### Read a task

```bash
mc_client.py task-read --task <task-uuid>
```

Returns the full task envelope (id, title, description, status,
priority, packet metadata) as JSON on stdout. Hits ``GET /api/v1/boards/
{board_id}/tasks/{task_id}`` directly — one request, no pagination.
Exit code 2 + 404 detail on stderr if the task is not on the
configured board.

### Post a task comment

```bash
mc_client.py comment-create --task <task-uuid> --message "Body in markdown."
```

For multi-paragraph or generated comment bodies, pipe stdin:

```bash
my_evidence_generator | mc_client.py comment-create --task <id> --message -
```

The bare `-` for `--message` reads stdin until EOF. Use this when the
comment is constructed by another tool to avoid quoting hazards.

### Record a pipeline event

```bash
# Standard build/deploy progress
mc_client.py pipeline-event-create --task <id> --state committed --commit-sha abc1234
mc_client.py pipeline-event-create --task <id> --state built --commit-sha abc1234 --artifact-hash index-x.js
mc_client.py pipeline-event-create --task <id> --state deployed --artifact-hash index-x.js --deploy-target http://192.168.2.63:3002/

# Informational fallback step (rare — usually populated by the cron tailer)
mc_client.py pipeline-event-create --task <id> --state model_fallback \
  --evidence '{"from_model":"ollama/qwen3.5:cloud","to_model":"ollama/glm-5.1:cloud","reason":"timeout"}'
```

The `--state` choices are constrained to the real `PipelineState` Literal
in `backend/app/schemas/task_pipeline_events.py`. The validator enforces
that `model_fallback` events carry `from_model`, `to_model`, and `reason`
in `--evidence` (a JSON object string).

### File a reviewer verdict

```bash
# Architect approves
mc_client.py review-event-create --task <id> --reviewer-role architect --verdict pass \
  --commit-sha 4c313c0 --build-hash index-CjvZkdm5.js --target http://192.168.2.63:3002/ \
  --evidence '{"comment":"AC1/2/3 verified live; no console errors"}'

# QA flags infra issue
mc_client.py review-event-create --task <id> --reviewer-role qa_e2e --verdict infra_blocked \
  --evidence '{"comment":"Playwright cannot reach .63:3002 — gateway 502s"}'
```

The verdict choices match the real `ReviewVerdict` Literal:
`pass | fail | inconclusive | infra_blocked`. `partial` is **not** valid;
inconclusive is the right answer when evidence is incomplete.

The `--reviewer-role` choices are constrained to roles that can actually
record review events: `architect | qa_unit | qa_e2e | devops | lead`.

## Output and exit codes

- **Stdout** is always JSON (compact). Use `--pretty` for human-readable
  formatting when running interactively.
- **Stderr** carries error detail (HTTP status, network failure, JSON
  decode error).
- **Exit codes**: `0` success; `1` argument / config error; `2` HTTP
  non-2xx response; `3` network / decoding error.

Use `$?` to branch on the result; do not parse stderr text — it's for
humans.

## Replacing curl patterns in existing skills

If you previously wrote, in a skill or agent prompt, something like:

```bash
curl -fsS -H "Authorization: Bearer $LOCAL_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"...\"}" \
  "$BASE_URL/api/v1/boards/$BOARD_ID/tasks/$TASK_ID/comments"
```

Replace it with:

```bash
mc_client.py comment-create --task "$TASK_ID" --message "..."
```

The CLI handles the rest. This eliminates a class of bugs (wrong header,
quoting hazards in messages, JSON encoding, stale endpoint paths after
MC API refactors).

## Hostname / location

The CLI lives on the gateway host `.60` at `/usr/local/bin/mc_client.py`
(deployed alongside `ingest_model_fallbacks.py` for the `mc-fallback-tailer`
cron). ACP children spawned with the standard ACPX wrapper inherit a PATH
that includes `/usr/local/bin/`, so they can call `mc_client.py` directly.

If you're running outside an ACP child (e.g., in a manual SSH session),
make sure `LOCAL_AUTH_TOKEN`, `BOARD_ID`, and optionally `MC_BASE_URL`
are exported. The gateway's `/etc/mc-fallback-tailer/env` file has these
values for the tailer; do not source it for ad-hoc work — generate a
short-lived token through the operator instead.

## Source of truth

Script: `backend/scripts/mc_client.py` in the `openclaw-mission-control`
repo. Tests: `backend/tests/test_mc_client.py`. The CLI's `--state`,
`--reviewer-role`, and `--verdict` choices are kept in sync with MC's
schema Literals (`task_pipeline_events.py`, `task_review_events.py`).
If you see a mismatch in production, it's a bug — file it; do not fall
back to hand-rolled curl.
