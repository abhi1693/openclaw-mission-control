---
name: lead-memory-intake
description: Use when a board lead must run the Memory Intake Gate after lead-next-action clears and before health scan, to verify recent operator-memory intake tasks.
---

# Lead Memory Intake Gate

Use this only as a board lead, after the Lead Next Action Gate clears and before any health scan or routing work. This skill is canonical for which memories fire the gate, the reconcile call, the gate's output ABI, and failure handling.

For Mission Control, this skill is the canonical source for the Memory Intake Gate Python, output markers, exit codes, and no-manual-create rule. `AGENTS.md § Lead Board Playbook / Step 2` and `HEARTBEAT.md` should point here instead of duplicating the gate logic.

## Contract

The backend normally creates intake tasks on memory write. The lead-side gate first calls the deterministic reconcile endpoint, then verifies recent actionable operator memory covered by the backend reconcile window. Returning `HEARTBEAT_OK` is forbidden until the gate clears. Do not manually create a task with `source_memory_id`; the generic task-create schema intentionally does not accept that field.

The reconcile endpoint is synchronous: it awaits task creation and commits
before returning. If a future backend response explicitly reports
background/pending work instead, poll tasks briefly before declaring
`MEMORY_INTAKE_FAILED`; otherwise do not add sleeps or loops around this gate.

## Tag Rules

A memory item fires the gate when **all** of these are true:

- `"operator"` is in `tags`
- at least one of `"findings"` or `"marketing_site_review"` is in `tags`
- `"e2e_canary"` is **not** in `tags`
- no existing task references it via `source_memory_id`

If multiple memories qualify after reconcile, report the first unresolved link failure and stop.

## Gate Script

Run after Lead Next Action clears and before health scan. Backend reads/exit codes are the contract; do not paraphrase.

```bash
LEAD_RECONCILE_JSON="$(mktemp "${TMPDIR:-/tmp}/mc-lead-reconcile-${BOARD_ID}-${AGENT_ID}.XXXXXX.json")"
LEAD_MEMORY_JSON="$(mktemp "${TMPDIR:-/tmp}/mc-lead-memory-${BOARD_ID}-${AGENT_ID}.XXXXXX.json")"
LEAD_TASKS_JSON="$(mktemp "${TMPDIR:-/tmp}/mc-lead-tasks-${BOARD_ID}-${AGENT_ID}.XXXXXX.json")"
export LEAD_RECONCILE_JSON LEAD_MEMORY_JSON LEAD_TASKS_JSON
curl -fsS -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory/intake/reconcile" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_RECONCILE_JSON"
curl -fsS "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?limit=200" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_MEMORY_JSON"
curl -fsS "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?limit=200" -H "X-Agent-Token: $AUTH_TOKEN" -o "$LEAD_TASKS_JSON"
python3 - <<'PY'
import json, os
memory_items=json.load(open(os.environ["LEAD_MEMORY_JSON"])).get("items", [])
tasks=json.load(open(os.environ["LEAD_TASKS_JSON"])).get("items", [])
linked={str(t.get("source_memory_id")) for t in tasks if t.get("source_memory_id")}
for item in memory_items:
    tags={str(t).lower() for t in (item.get("tags") or [])}
    if "e2e_canary" in tags or "operator" not in tags:
        continue
    if not ({"findings","marketing_site_review"} & tags):
        continue
    memory_id=str(item.get('id'))
    content=(item.get('content') or "").strip()
    if memory_id and memory_id not in linked:
        print("MEMORY_INTAKE_FAILED unlinked_after_reconcile", memory_id, content[:160])
        raise SystemExit(2)
print("MEMORY_INTAKE_CLEAR")
PY
```

## Output ABI

Three terminal outputs are possible. Downstream automation (HEARTBEAT_OK gate, supervisor heartbeat scheduler) reads these literal strings.

| Output | Exit | Meaning |
|---|---|---|
| `MEMORY_INTAKE_FAILED unlinked_after_reconcile <memory_id> <content_first_160>` | 2 | Reconcile did not produce a linked intake task for a qualifying operator memory. Report failure and do not return `HEARTBEAT_OK` |
| `MEMORY_INTAKE_CLEAR` | 0 | No qualifying memory needs a task. Proceed to next gate |
| Any uncaught exception or curl failure | non-zero | Treat as `MEMORY_INTAKE_FAILED`; report `HEARTBEAT_FAILED`, do not return `HEARTBEAT_OK` |

## Action on Failure

If reconcile or the verification script fails, report `MEMORY_INTAKE_FAILED` with the HTTP status/body or printed unresolved memory id. Do not retry manual task creation in the same tick. Do not return `HEARTBEAT_OK`.

Run the script exactly as written. The quoted Python block is part of the
contract; do not inline-edit heredoc quoting inside rendered templates.

If the board has more than 200 recent memory entries or tasks and the reported
memory should already be linked, fetch additional pages before manual action.
The backend reconcile endpoint is still the source of truth for creating links.

## When Not To Use

- Worker roles (PF/PB/DevOps/QA/Architect): the gate fires only for the board lead. Workers should not run it.
- After the gate has already cleared this tick: the gate is idempotent on `MEMORY_INTAKE_CLEAR` but should not be re-run unnecessarily.
- For non-`operator` memories: chat memory, agent-internal memory, and `e2e_canary` memories are all out of scope by design.
