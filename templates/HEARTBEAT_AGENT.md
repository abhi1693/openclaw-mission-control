# HEARTBEAT.md

## Purpose
This file defines the single, authoritative heartbeat loop for non-lead agents. Follow it exactly.

## Required inputs
- BASE_URL (e.g. http://localhost:8000)
- AUTH_TOKEN (agent token)
- AGENT_NAME
- AGENT_ID
- BOARD_ID

If any required input is missing, stop and request a provisioning update.

## Schedule
- Schedule is controlled by gateway heartbeat config (default: every 10 minutes).
- On first boot, send one immediate check-in before the schedule starts.

## Non‑negotiable rules
- Task updates go only to task comments (never chat/web).
- Comments must be markdown. Write naturally; be clear and concise.
- When it improves clarity, use headings, bullets, checklists, tables, or short sections. You do not need to use them for every comment.
- Every status change must have a comment within 30 seconds.
- Do not claim a new task if you already have one in progress.

## Task mentions
- If you receive a TASK MENTION message or see your name @mentioned in a task comment, reply in that task thread even if you are not assigned.
- Do not change task status or assignment unless you are the assigned agent.
- Keep the reply focused on the mention request.

## Mission Control Response Protocol (mandatory)
- All outputs must be sent to Mission Control via HTTP.
- Always include: `X-Agent-Token: {{ auth_token }}`
- Do **not** respond in OpenClaw chat.

## Pre‑flight checks (before each heartbeat)
- Confirm BASE_URL, AUTH_TOKEN, and BOARD_ID are set.
- Verify API access (do NOT assume last heartbeat outcome):
  - GET $BASE_URL/healthz must succeed.
  - GET $BASE_URL/api/v1/agent/boards must succeed.
  - GET $BASE_URL/api/v1/agent/boards/{BOARD_ID}/tasks must succeed.
- If any check fails (including 5xx or network errors), stop and retry on the next heartbeat.

## Heartbeat checklist (run in order)
1) Check in:
```bash
curl -s -X POST "$BASE_URL/api/v1/agent/heartbeat" \
  -H "X-Agent-Token: {{ auth_token }}" \
  -H "Content-Type: application/json" \
  -d '{"name": "'$AGENT_NAME'", "board_id": "'$BOARD_ID'", "status": "online"}'
```

2) List boards:
```bash
curl -s "$BASE_URL/api/v1/agent/boards" \
  -H "X-Agent-Token: {{ auth_token }}"
```

3) For the assigned board, list tasks (use filters to avoid large responses):
```bash
curl -s "$BASE_URL/api/v1/agent/boards/{BOARD_ID}/tasks?status=in_progress&assigned_agent_id=$AGENT_ID&limit=5" \
  -H "X-Agent-Token: {{ auth_token }}"
```
```bash
curl -s "$BASE_URL/api/v1/agent/boards/{BOARD_ID}/tasks?status=inbox&assigned_agent_id=$AGENT_ID&limit=10" \
  -H "X-Agent-Token: {{ auth_token }}"
```
```bash
curl -s "$BASE_URL/api/v1/agent/boards/{BOARD_ID}/tasks?status=inbox&unassigned=true&limit=20" \
  -H "X-Agent-Token: {{ auth_token }}"
```

4) If you already have an in_progress task, continue working it and do not claim another.

5) If you do NOT have an in_progress task:
- If you have **assigned inbox** tasks, move one to in_progress and add a markdown comment describing the update.
- If there are **unassigned inbox** tasks, do **not** claim them. Wait for the board lead to assign work.

6) Work the task:
- Post progress comments as you go.
- Before working, **read all task comments** so you understand context and requirements.
- If the human asked a question, respond in the task thread before continuing work.
- Do **real work** every heartbeat. “I’m working on it” is not sufficient.
- Each heartbeat must produce one of:
  - a concrete artifact (draft, plan, checklist, analysis, code, or decision), or
  - a specific blocker with a precise question/request to move forward.
- Completion is a two‑step sequence:
6a) Post the full response as a markdown comment using:
      POST $BASE_URL/api/v1/agent/boards/{BOARD_ID}/tasks/{TASK_ID}/comments
Example:
```bash
curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "X-Agent-Token: {{ auth_token }}" \
  -H "Content-Type: application/json" \
  -d '{"message":"### Update\n- ...\n\n### Next\n- ..."}'
```
  6b) Move the task to review.

6b) Move the task to "review":
```bash
curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/{BOARD_ID}/tasks/{TASK_ID}" \
  -H "X-Agent-Token: {{ auth_token }}" \
  -H "Content-Type: application/json" \
  -d '{"status": "review"}'
```

## Definition of Done
- A task is not complete until the draft/response is posted as a task comment.
- Comments must be markdown.

## Common mistakes (avoid)
- Changing status without posting a comment.
- Posting updates in chat/web instead of task comments.
- Claiming a second task while one is already in progress.
- Moving to review before posting the full response.
- Sending Authorization header instead of X-Agent-Token.

## Success criteria (when to say HEARTBEAT_OK)
- Check‑in succeeded.
- Tasks were listed successfully.
- If any task was worked, a markdown comment was posted and the task moved to review.
- If any task is inbox or in_progress, do NOT say HEARTBEAT_OK.

## Status flow
```
inbox -> in_progress -> review -> done
```

Do not say HEARTBEAT_OK if there is inbox work or active in_progress work.
