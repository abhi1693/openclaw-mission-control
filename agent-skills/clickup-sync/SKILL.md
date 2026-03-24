---
name: clickup-sync
description: Bidirectional sync between ClickUp tasks and Mission Control boards
---

# ClickUp Sync

Automatically synchronize tasks between ClickUp and Mission Control boards. Fetches tasks from ClickUp, creates corresponding Mission Control tasks (with deduplication), and syncs task status changes back to ClickUp when tasks complete.

## When to use

- When you need to keep ClickUp workspace/lists in sync with Mission Control boards
- On every heartbeat (watchdog pattern - checks every heartbeat, syncs if >15 minutes since last sync)
- When a Mission Control task moves to `done` status and needs to update ClickUp
- When setting up a new board that should mirror ClickUp tasks

## When NOT to use

- If ClickUp integration is not configured (missing env vars)
- For one-time imports (use manual task creation instead)
- When ClickUp API is unavailable (check board memory for recent errors)

## Prerequisites

**Environment Variables:**
- `CLICKUP_TOKEN` - ClickUp API token (from ClickUp settings)
- `CLICKUP_TEAM_ID` - ClickUp workspace/team ID
- `CLICKUP_LIST_ID` (optional) - Specific list ID to sync, if not set syncs all lists in team

**Tools Required:**
- `curl` - for API calls
- `jq` - for JSON parsing
- `date` - for timestamp calculations

**Mission Control Setup:**
- Agent must have read/write access to board
- Board memory access enabled

## Workflow

### 1. Check Sync Watchdog (on heartbeat)

```bash
# Read last sync timestamp from board memory
LAST_SYNC=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=clickup_sync_state" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.memories[0].content.last_sync_timestamp // 0')

CURRENT_TIME=$(date +%s)
TIME_DIFF=$((CURRENT_TIME - LAST_SYNC))

# If more than 15 minutes (900 seconds), trigger sync
if [ $TIME_DIFF -gt 900 ]; then
  echo "Triggering ClickUp sync (last sync: $TIME_DIFF seconds ago)"
  # Proceed to step 2
else
  echo "Sync not needed (last sync: $TIME_DIFF seconds ago)"
  exit 0
fi
```

### 2. Fetch ClickUp Tasks

```bash
# Get all tasks from ClickUp list
CLICKUP_TASKS=$(curl -s "https://api.clickup.com/api/v2/list/$CLICKUP_LIST_ID/task" \
  -H "Authorization: $CLICKUP_TOKEN" | jq -r '.tasks')

# Alternative: Get tasks from entire team
# CLICKUP_TASKS=$(curl -s "https://api.clickup.com/api/v2/team/$CLICKUP_TEAM_ID/task" \
#   -H "Authorization: $CLICKUP_TOKEN" | jq -r '.tasks')
```

### 3. Load Sync State (Task Fingerprints)

```bash
# Get existing sync state from board memory
SYNC_STATE=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=clickup_sync_state" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.memories[0].content // {}')

# Extract fingerprints (clickup_id -> mc_task_id mapping)
FINGERPRINTS=$(echo "$SYNC_STATE" | jq -r '.fingerprints // {}')
```

### 4. Create/Update Mission Control Tasks

```bash
# Map ClickUp status to MC status
map_status() {
  case "$1" in
    "to do") echo "inbox" ;;
    "in progress") echo "in_progress" ;;
    "review") echo "review" ;;
    "complete") echo "done" ;;
    *) echo "inbox" ;;
  esac
}

# Process each ClickUp task
echo "$CLICKUP_TASKS" | jq -c '.[]' | while read -r task; do
  CLICKUP_ID=$(echo "$task" | jq -r '.id')
  TASK_NAME=$(echo "$task" | jq -r '.name')
  TASK_DESC=$(echo "$task" | jq -r '.description // ""')
  CLICKUP_STATUS=$(echo "$task" | jq -r '.status.status')
  MC_STATUS=$(map_status "$CLICKUP_STATUS")

  # Check if task already exists in MC (via fingerprint)
  MC_TASK_ID=$(echo "$FINGERPRINTS" | jq -r --arg cid "$CLICKUP_ID" '.[$cid] // empty')

  if [ -z "$MC_TASK_ID" ]; then
    # Create new MC task
    echo "Creating MC task for ClickUp#$CLICKUP_ID: $TASK_NAME"

    MC_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
      -H "Authorization: Bearer $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"title\": \"$TASK_NAME\",
        \"description\": \"$TASK_DESC\\n\\n---\\nClickUp ID: $CLICKUP_ID\",
        \"status\": \"$MC_STATUS\",
        \"tags\": [\"clickup-sync\"]
      }")

    MC_TASK_ID=$(echo "$MC_RESPONSE" | jq -r '.task.id')

    # Update fingerprints
    FINGERPRINTS=$(echo "$FINGERPRINTS" | jq --arg cid "$CLICKUP_ID" --arg mcid "$MC_TASK_ID" '. + {($cid): $mcid}')
  else
    # Task exists, check if status changed in ClickUp
    MC_TASK=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$MC_TASK_ID" \
      -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.task')

    MC_CURRENT_STATUS=$(echo "$MC_TASK" | jq -r '.status')

    if [ "$MC_CURRENT_STATUS" != "$MC_STATUS" ]; then
      echo "Updating MC task $MC_TASK_ID status: $MC_CURRENT_STATUS -> $MC_STATUS"

      curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$MC_TASK_ID" \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$MC_STATUS\"}"
    fi
  fi
done
```

### 5. Sync MC Completed Tasks Back to ClickUp

```bash
# Get all done tasks with clickup-sync tag
DONE_TASKS=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=done&tags=clickup-sync" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.tasks')

echo "$DONE_TASKS" | jq -c '.[]' | while read -r task; do
  MC_TASK_ID=$(echo "$task" | jq -r '.id')
  TASK_DESC=$(echo "$task" | jq -r '.description')

  # Extract ClickUp ID from description
  CLICKUP_ID=$(echo "$TASK_DESC" | grep -oP 'ClickUp ID: \K\d+')

  if [ -n "$CLICKUP_ID" ]; then
    echo "Marking ClickUp task #$CLICKUP_ID as complete"

    # Update ClickUp task status to complete
    curl -s -X PUT "https://api.clickup.com/api/v2/task/$CLICKUP_ID" \
      -H "Authorization: $CLICKUP_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"status": "complete"}'
  fi
done
```

### 6. Save Sync State

```bash
# Update sync state in board memory
CURRENT_TIME=$(date +%s)

curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"content\": {
      \"fingerprints\": $FINGERPRINTS,
      \"last_sync_timestamp\": $CURRENT_TIME
    },
    \"tags\": [\"clickup_sync_state\"]
  }"

echo "Sync complete at $(date -r $CURRENT_TIME)"
```

## API Reference (Mission Control)

### List Tasks
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=inbox" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Create Task
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Task title",
    "description": "Task description",
    "status": "inbox",
    "tags": ["clickup-sync"]
  }'
```

### Update Task Status
```bash
curl -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'
```

### Read Board Memory
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=clickup_sync_state" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Write Board Memory
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": {"key": "value"},
    "tags": ["clickup_sync_state"]
  }'
```

## ClickUp API Reference

### Get Tasks from List
```bash
curl "https://api.clickup.com/api/v2/list/$CLICKUP_LIST_ID/task" \
  -H "Authorization: $CLICKUP_TOKEN"
```

### Update Task Status
```bash
curl -X PUT "https://api.clickup.com/api/v2/task/$TASK_ID" \
  -H "Authorization: $CLICKUP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "complete"}'
```

## Watchdog / Continuity

This skill uses a **watchdog pattern** to ensure continuous sync:

1. **On every agent heartbeat**, check the last sync timestamp stored in board memory (tag: `clickup_sync_state`)
2. **If >15 minutes** since last sync, trigger a full sync cycle
3. **If sync fails**, the timestamp is not updated, so next heartbeat will retry
4. **Fingerprinting** via board memory prevents duplicate task creation across restarts

**Error Handling:**
- If ClickUp API is unavailable, skip sync and retry on next heartbeat
- If MC task creation fails, continue processing other tasks (partial sync is OK)
- Log errors to board memory with tag `clickup_sync_errors` for debugging

**Recovery:**
- If fingerprints are corrupted/lost, manual cleanup may be needed to avoid duplicates
- Consider adding a "dry-run" mode that compares but doesn't create tasks
