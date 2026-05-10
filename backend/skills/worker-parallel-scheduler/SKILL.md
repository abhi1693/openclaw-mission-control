---
name: worker-parallel-scheduler
description: Use when a worker agent operates in worktree-parallel mode and must select implementation work without overspawning, isolate each task in a deterministic worktree, and serialize merge-back.
---

# Worker Parallel Scheduler

This skill is the authoritative source for worker-agent worktree-parallel mode mechanics. `HEARTBEAT.md` points here instead of duplicating the cap-aware scheduler, worktree procedure, or per-board merge-back lock.

Use this skill only when `identity.worker_parallel_mode` (or legacy `identity.frontend_parallel_mode`) is set to `worktree` or equivalent AND `@lead` or the operator has posted live ACP `cwd` smoke-test evidence for this board.

The scheduler is role-agnostic for frontend and backend workers. Parallelism is per task, not per acceptance criterion.

## Hard Rules

- **Cap = 4 active implementation tasks** unless the operator explicitly raises it for this board. "Active" = task with an accepted `ACP_EXECUTOR_STARTED` marker AND no processed child completion. Parked, blocked, or `operator_decision_required=true` tasks do NOT count toward the cap.
- **Atomic spawn gate.** Acquire the per-agent scheduler lock before active-count/candidate selection. Keep file descriptor 8 open through `sessions_spawn` and `ACP_EXECUTOR_STARTED` posting. Release it only after no candidate, spawn rejection, or accepted marker post.
- **One spawn per heartbeat tick.** The cap is a concurrent-max, not a per-tick budget. Going from 0 to 4 active children takes 4 heartbeat-or-completion cycles. This throttles worktree creation, ACP spawn handshakes, and gateway load.
- **One worktree per task.** Use `acp-delegation` Worktree Task Mode for the ACP payload integration.
- **Post `ACP_EXECUTOR_STARTED` only after the ACP spawn is accepted**, then release the scheduler lock and return `HEARTBEAT_OK` for the current tick.
- **Completion-woken ticks process child results only.** Do NOT spawn new work on a completion wake. Do NOT merge child work before parent verification and required stage-2 review PASS. After locked merge, run post-merge verification before posting `FINAL_EVIDENCE_PACKET` or routing.

## Atomic Spawn Gate

Run this on each non-completion heartbeat tick after the standard check-in curl, before any spawn or task status mutation:

```bash
WT_SCHED_LOCK="/tmp/mc-wt-scheduler-${BOARD_ID}-${AGENT_ID}.lock"
exec 8>"$WT_SCHED_LOCK"
if ! flock -w 30 8; then
  echo "WT_SCHED_LOCK_BUSY board=$BOARD_ID agent=$AGENT_ID"
  exit 0
fi
# Keep file descriptor 8 open until after there is no TASK_ID, the spawn is
# rejected, or sessions_spawn is accepted and ACP_EXECUTOR_STARTED is posted.

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
    """Fetch the latest 250 comments so ACP marker scans use the newest state."""
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
if len(active) < 4:
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

If `TASK_ID` is empty, release the scheduler lock and return `HEARTBEAT_OK` without posting a filler comment:

```bash
if [ -z "$TASK_ID" ]; then
  flock -u 8
  exit 0
fi
```

If the ACP spawn is rejected, do not post `ACP_EXECUTOR_STARTED`; record the rejection/error per `acp-delegation`, release the scheduler lock, and follow retry/escalation policy.

After the ACP spawn returns accepted, post `ACP_EXECUTOR_STARTED` while file descriptor 8 is still open. Then release the scheduler lock and return `HEARTBEAT_OK`:

```bash
# post ACP_EXECUTOR_STARTED here with the accepted child/run/label
flock -u 8
exit 0
```

## Worktree Creation

Before spawning an implementation child, create or reuse the deterministic board-scoped worktree:

```bash
BOARD_SHORT="$(printf '%s' "$BOARD_ID" | cut -c1-8)"
TASK_SHORT="$(printf '%s' "$TASK_ID" | cut -c1-8)"
WT_PATH="/tmp/mc-${BOARD_SHORT}-wt-$TASK_SHORT"
WT_BRANCH="wt/${BOARD_SHORT}/$TASK_SHORT"
BASE_HEAD="$(git -C "$WORKSPACE_PATH" rev-parse HEAD)"

if git -C "$WT_PATH" rev-parse --show-toplevel >/tmp/wt-root.txt 2>/tmp/wt-create.err; then
  WT_BRANCH_ACTUAL="$(git -C "$WT_PATH" rev-parse --abbrev-ref HEAD)"
  WT_HEAD="$(git -C "$WT_PATH" rev-parse HEAD)"
  WT_STATUS="$(git -C "$WT_PATH" status --short)"
  if [ "$WT_BRANCH_ACTUAL" != "$WT_BRANCH" ] || [ "$WT_HEAD" != "$BASE_HEAD" ] || [ -n "$WT_STATUS" ]; then
    {
      echo "WT_STALE_OR_DIRTY path=$WT_PATH branch=$WT_BRANCH_ACTUAL expected=$WT_BRANCH"
      echo "WT_HEAD=$WT_HEAD BASE_HEAD=$BASE_HEAD"
      printf '%s\n' "$WT_STATUS"
    } >/tmp/wt-create.err
    exit 1
  fi
else
  git -C "$WORKSPACE_PATH" worktree add -B "$WT_BRANCH" "$WT_PATH" HEAD
fi
git -C "$WT_PATH" rev-parse --show-toplevel
git -C "$WT_PATH" rev-parse --abbrev-ref HEAD
git -C "$WT_PATH" status --short
```

If any worktree command fails, release the scheduler lock, post one structured blocker with the exact command and stderr from `/tmp/wt-create.err`, then continue sequentially in the main workspace until lead/operator re-enables parallelism.

For the ACP implementation payload, add:

```json
{ "cwd": "$WT_PATH" }
```

## Completion And Pre-Merge Review

On a completion-woken tick, do not run the spawn gate. Process the finished child only.

Do NOT merge child work before parent verification. Use `acp-post-review` Worktree Pre-Merge Gate against the child output and worktree diff. If the role flow requires stage-2 review, spawn that review against the worktree diff before merge. Continue only after:

- child output and worktree diff match the task scope
- required parent runtime/browser checks are captured when possible from the worktree
- required stage-2 review PASS
- no child Mission Control write contamination

Record this state locally before merge:

```bash
PRE_MERGE_REVIEW_PASSED=1
```

## Per-Board Merge-Back Lock

With multiple ACP children completing in the same window, two heartbeat sessions can race the merge into shared `$WORKSPACE_PATH`. Wrap merge/cleanup with `flock` against a per-board file lock. If the lock is held longer than 60s, log busy and exit this heartbeat tick; the next heartbeat retries.

```bash
: "${PRE_MERGE_REVIEW_PASSED:?run acp-post-review Worktree Pre-Merge Gate before merge}"
WT_MERGE_LOCK="/tmp/mc-wt-merge-${BOARD_ID}.lock"
exec 9>"$WT_MERGE_LOCK"
if ! flock -w 60 9; then
  echo "WT_MERGE_LOCK_BUSY task=$TASK_SHORT board=$BOARD_ID"
  exit 0
fi
git -C "$WORKSPACE_PATH" merge --no-ff "$WT_BRANCH" -m "merge $WT_BRANCH into main workspace" || {
  flock -u 9
  exit 1
}
git -C "$WORKSPACE_PATH" worktree remove --force "$WT_PATH" || true
git -C "$WORKSPACE_PATH" branch -D "$WT_BRANCH" || true
flock -u 9
```

The lock file at `/tmp/mc-wt-merge-${BOARD_ID}.lock` is per board, not per task.

After merge, run parent-side post-merge verification from `$WORKSPACE_PATH`. Set `POST_MERGE_VERIFICATION_PASSED=1` only after the relevant checks pass. Then post the parent-owned `FINAL_EVIDENCE_PACKET` and route according to `acp-post-review`.

## Failure Handling

On any worktree create, pre-merge review, merge, cleanup, or ACP `cwd` uncertainty:

1. Release held scheduler/merge locks.
2. Stop parallelism for this agent.
3. Post one structured blocker with the exact failing command/output.
4. Continue in sequential main-workspace mode until lead/operator re-enables it.

## Sequential Fallback

When `worker_parallel_mode` is not set or is `off`, do not create git worktrees, isolated sessions, or parallel workspace branches during heartbeat work. Continue the oldest active `in_progress` task first. If none is active, pick one eligible task and finish it through evidence, ACP post-review, and handoff before starting another.
