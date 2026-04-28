---
name: lead-inbox-routing
description: Use when a board lead must route inbox work, decide whether decomposition is required, create planned subtasks, or assign new work to the right role.
---

# Lead Inbox Routing

Use this only as a board lead for `inbox` tasks or for
`lead-next-action-gate` actions that return `route_inbox`.

## Subtask Creation

Before creating a task, check the current task list for similar titles. Do not
create duplicates.

```bash
curl -fsS -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "X-Agent-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"T","description":"D","assigned_agent_id":"UUID","priority":"high"}'
```

## Decomposition Gate

Run this first for new inbox tasks or tasks assigned to the lead. Route to
Architect if any condition is true:

- five or more acceptance criteria
- multi-component deliverable
- two or more deliverables
- missing acceptance-criteria list
- new architecture: data model, API contract, auth scope, or state-machine
  status

Skip decomposition only when the task is a single deliverable, has fewer than
five acceptance criteria, follows a shipped pattern, and needs no architectural
decision. If skipping, record `[NO-DECOMPOSE: <reason>]`.

Architect route:

```json
{"assigned_agent_id":"ARCHITECT_ID","status":"review"}
```

Nudge text:

```text
DECOMPOSE $TASK_ID. Post per-AC to subtask map with roles, review_packet_type, validation_target*, and dependency order. Do NOT implement or move status.
```

If Architect already posted a plan, skip the route and run umbrella lifecycle.

## Umbrella Lifecycle

1. Create each subtask from Architect's plan with `assigned_agent_id`,
   `depends_on_task_ids`, and copied acceptance criteria.
2. Retire pure-container umbrella tasks with `{"status":"cancelled"}`.
3. If the umbrella has its own artifact, link real dependencies through
   `depends_on_task_ids` or an `OperatorDecision`. Do not write `is_blocked`
   directly.
4. Route subtasks as normal tasks.

## Normal Task Routing

- Frontend/UI/product surface work -> Programmer-Frontend.
- Backend/API/persistence/auth/service work -> Programmer-Backend.
- Infra/deploy/live-target/build-drift/operator-target work -> DevOps.
- Review, QA, or Architect validation tasks -> status `review`.
- Unassigned implementation inbox task plus idle implementation agent -> patch
  `{"assigned_agent_id":"UUID","status":"in_progress"}` and nudge once.

Use board-visible agent UUIDs from the current health scan. Do not hardcode
agent ids.
