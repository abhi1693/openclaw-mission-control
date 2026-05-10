---
name: worker-parallel-scheduler
description: Use when a worker agent (frontend or backend) operates in worktree-parallel mode and must select the next task across an active-child cap, create deterministic worktrees, and serialize merge-back into the main workspace.
---

# Worker Parallel Scheduler

This skill is the authoritative source for worker-agent worktree-parallel mode mechanics. `HEARTBEAT.md` points here instead of duplicating the cap-aware scheduler, worktree procedure, or per-board merge-back lock.

Use this skill **only when** `identity.worker_parallel_mode` (or legacy `identity.frontend_parallel_mode`) is set to `"worktree"` (or equivalent) AND `@lead` or the operator has posted live ACP `cwd` smoke-test evidence for this board.

The current implementation is opt-in for any worker role that fits the worktree-isolation pattern (frontend code, backend services, etc.). The scheduler logic is role-agnostic; the cap and pickup-order mirror the worker execution loop in `AGENTS.md`.

## Hard Rules

- **Cap = 5 active implementation tasks** unless the operator explicitly raises it for this board. "Active" = task with an accepted `ACP_EXECUTOR_STARTED` marker AND no processed child completion. Parked, blocked, or `operator_decision_required=true` tasks do NOT count toward the cap.
- **One spawn per heartbeat tick.** The cap is a concurrent-max, not a per-tick budget. Going from 0→5 active children takes 5 heartbeat-or-completion cycles. This is intentional throttling — keeps worktree creation, ACP spawn handshakes, and gateway load bounded.
- **One worktree per task, not per acceptance criterion.** Use `acp-delegation` § Worktree Task Mode for the ACP payload integration.
- **Post `ACP_EXECUTOR_STARTED` only after the ACP spawn is accepted**, then return `HEARTBEAT_OK` for the current tick.
- **Completion-woken ticks process child results only.** Do NOT spawn new work on a completion wake. Merge `wt/$TASK_SHORT` back to the main workspace, remove the worktree/branch after a clean merge, then run `acp-post-review`. (Order matters: merge/cleanup before review so the parent's verification runs against the merged state, not against the worktree branch in isolation.)

## Cap-aware scheduler

Run this on each heartbeat tick (after the standard check-in curl, before any spawn or status mutation):

```bash
curl -fsS "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?assigned_agent_id=$AGENT_ID" \
  -H "X-Agent-Token: $AUTH_TOKEN" -o /tmp/mc-my-tasks.json
BASE_URL="$BASE_URL" AUTH_TOKEN="$AUTH_TOKEN" BOARD_ID="$BOARD_ID" AGENT_ID="$AGENT_ID" \
python3 - <<'PY' > /tmp/mc-worker-scheduler.env
import json
import os
import shlex
import urllib.request

base = os.environ["BASE_URL"].rstrip("/")
token = os.environ["AUTH_TOKEN"]
board_id = os.environ["BOARD_ID"]
tasks = json.load(open("/tmp/mc-my-tasks.json")).get("items", [])
comment_cache = {}

def task_comments(task_id):
    """Fetch the LATEST 250 comments so the ACP marker scan is correct.

    The cap-aware scheduler counts active children by scanning for the
    latest ACP_EXECUTOR_STARTED vs FINAL_EVIDENCE_PACKET / ACP_POST_REVIEW_COMPLETE
    marker. The MC comments endpoint returns OLDEST first, so a naive
    offset=0 page fetches the wrong window. Probe ``total`` first, then
    fetch from offset=total-250 forward.
    """
    if task_id not in comment_cache:
        page_size = 50
        max_window = 250
        probe_url = f"{base}/api/v1/agent/boards/{board_id}/tasks/{task_id}/comments?limit={page_size}&offset=0"
        with urllib.request.urlopen(
            urllib.request.Request(probe_url, headers={"X-Agent-Token": token}),
            timeout=15,
        ) as resp:
            probe = json.load(resp)
        total_raw = probe.get("total")
        if not isinstance(total_raw, int) or total_raw < 0:
            # Fail closed: synthesize a START marker so unfinished_child()
            # returns True and the scheduler does NOT pick this task as a
            # fresh-spawn candidate. Better to leave a real child uncounted
            # than to double-spawn.
            comment_cache[task_id] = [{"message": "ACP_EXECUTOR_STARTED [pagination_total_missing_fail_closed]"}]
            return comment_cache[task_id]
        total = total_raw
        if total <= max_window:
            all_comments = list(probe.get("items", []))
            offset = page_size
        else:
            all_comments = []
            offset = total - max_window
        while offset < total:
            url = f"{base}/api/v1/agent/boards/{board_id}/tasks/{task_id}/comments?limit={page_size}&offset={offset}"
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"X-Agent-Token": token}),
                timeout=15,
            ) as resp:
                page = json.load(resp).get("items", [])
            all_comments.extend(page)
            if not page or len(page) < page_size:
                break
            offset += page_size
        comment_cache[task_id] = all_comments
    return comment_cache[task_id]

def unfinished_child(task):
    last_start = -1
    last_parent_finish = -1
    for idx, comment in enumerate(task_comments(task["id"])):
        message = comment.get("message") or ""
        if "ACP_EXECUTOR_STARTED" in message:
            last_start = idx
        if "FINAL_EVIDENCE_PACKET" in message or "ACP_POST_REVIEW_COMPLETE" in message:
            last_parent_finish = idx
    return last_start >= 0 and last_start > last_parent_finish

def usable(task):
    return not task.get("is_blocked") and not task.get("operator_decision_required")

active = [
    task for task in tasks
    if task.get("status") in {"in_progress", "rework"} and usable(task) and unfinished_child(task)
]
candidate = None
if len(active) < 5:
    for status in ("in_progress", "rework", "inbox"):
        for task in tasks:
            if task.get("status") == status and usable(task) and not unfinished_child(task):
                candidate = task
                break
        if candidate:
            break

print(f"WORKER_PARALLEL_ACTIVE_COUNT={len(active)}")
print("TASK_ID=" + shlex.quote(str(candidate["id"])) if candidate else "TASK_ID=")
PY
. /tmp/mc-worker-scheduler.env
```

If `TASK_ID` is empty, there is no eligible task or the active child cap is full — return `HEARTBEAT_OK` without posting a filler comment.

## Worktree creation

Before spawning an implementation child, create or reuse the deterministic worktree:

```bash
TASK_SHORT="$(printf '%s' "$TASK_ID" | cut -c1-8)"
WT_PATH="/tmp/wt-$TASK_SHORT"
WT_BRANCH="wt/$TASK_SHORT"
if ! git -C "$WT_PATH" rev-parse --show-toplevel >/tmp/wt-root.txt 2>/tmp/wt-create.err; then
  git -C "$WORKSPACE_PATH" worktree add -B "$WT_BRANCH" "$WT_PATH" HEAD
fi
git -C "$WT_PATH" status --short
```

If any worktree command fails, post one structured blocker with the exact command and stderr from `/tmp/wt-create.err`, then fall back to sequential main-workspace mode until lead/operator re-enables parallelism.

For the ACP implementation payload, add:
```json
{ "cwd": "$WT_PATH" }
```

## Per-board merge-back lock (cap=5 contention)

With multiple ACP children completing in the same window, two heartbeat sessions can race the merge into shared `$WORKSPACE_PATH` and leave the working tree in a half-merged state. Wrap the merge/cleanup with `flock` against a per-board file lock. If the lock is held longer than 60s, log busy and exit this heartbeat tick — the next heartbeat retries.

Lock contention is normal at higher caps; only post a structured blocker for actual merge/cleanup failure (the explicit `exit 1` branch below), not for transient busy-lock waits:

```bash
WT_MERGE_LOCK="/tmp/mc-wt-merge-${BOARD_ID}.lock"
exec 9>"$WT_MERGE_LOCK"
if ! flock -w 60 9; then
  # Another completion wake is mid-merge. Stop this tick and let it
  # finish; the next heartbeat will pick this child up.
  echo "WT_MERGE_LOCK_BUSY task=$TASK_SHORT board=$BOARD_ID"
  exit 0
fi
git -C "$WORKSPACE_PATH" merge --no-ff "$WT_BRANCH" -m "merge $WT_BRANCH into main workspace" || {
  flock -u 9
  # Post a blocker via the standard worktree-failure path; do NOT
  # leave the lock held.
  exit 1
}
git -C "$WORKSPACE_PATH" worktree remove --force "$WT_PATH" || true
git -C "$WORKSPACE_PATH" branch -D "$WT_BRANCH" || true
flock -u 9
```

The lock file at `/tmp/mc-wt-merge-${BOARD_ID}.lock` is per board, not per task — only one merge into `$WORKSPACE_PATH` runs at a time, while worktree builds, tests, and child spawns continue in parallel inside their own `wt/$TASK_SHORT` directories.

## Failure handling

On any worktree create, merge, cleanup, or ACP `cwd` uncertainty:
1. Stop parallelism for this agent.
2. Post one structured blocker with the exact failing command/output.
3. Continue in sequential main-workspace mode until lead/operator re-enables it.

## Sequential fallback (when parallel mode is OFF)

When `worker_parallel_mode` is not set (or is `"off"`), DO NOT create git worktrees, isolated sessions, or parallel workspace branches during heartbeat work. Those isolation paths have previously hidden state and caused stale merges.

When multiple assigned tasks are present, continue the oldest active `in_progress` task first. If none is active, pick one eligible task and finish it through evidence, ACP post-review, and handoff before starting another.

Only if `@lead` explicitly routes independent parallel slices may you run more than one ACP child without worktree mode. In that case, use `acp-delegation` with disjoint file/AC ownership, unique labels, and parent-owned final integration.
