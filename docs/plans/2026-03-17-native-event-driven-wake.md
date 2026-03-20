# Native Event-Driven Agent Wake Plan

**Goal:** Replace board-agent polling as the primary work-discovery mechanism with Mission Control initiated wakes that use OpenClaw's native event surfaces: direct session messages for targeted board agents, gateway `wake`/`system-event` for gateway-main or global main-session work, and gateway `/hooks/agent` for isolated, scoped runs (pending verification).

**Outcome target:** Heartbeats become a low-frequency safety net instead of the main scheduling primitive. Work reaches agents because Mission Control emits events when board state changes.

**Prerequisite:** Execute the heartbeat token optimization plan (`2026-03-17-heartbeat-token-optimization.md`) first. That plan adds `isolatedSession` and `lightContext` to defaults, which is Stage 1 of this plan's Safety Net.

**Why this matches OpenClaw:** OpenClaw already supports event-driven execution in three forms that Mission Control can use today:
- Session-targeted message delivery: send a message to a known agent session.
- Main-session wake: enqueue a system event and trigger heartbeat now or on the next scheduled tick.
- Isolated agent turn: POST to `/hooks/agent` to run a dedicated agent turn with its own prompt/session.

This plan uses those mechanisms directly instead of trying to turn `HEARTBEAT.md` into a pre-LLM execution hook.

## Current State

Mission Control already does partial push delivery today:
- Task assignment and rework notifications send messages directly to the assignee session.
- New task / task returned to inbox notifications send messages to the board lead.
- Approval resolution notifies the lead.
- Board memory, group memory, and board webhooks can notify agents directly.
- Task comment mentions notify assignees and mentioned agents (`_notify_task_comment_targets` in tasks.py).

The gap is that these paths are inconsistent and transport-specific:
- Some events go straight to the main session via `chat.send` style dispatch.
- Some work still relies on periodic heartbeat polling to discover it (dependency unblocking, human status changes, drift detection).
- There is no shared dedupe/coalescing layer, so event routing policy is spread across many API modules.
- The `deliver` parameter is inconsistent: control commands use `deliver=True` (immediate execution), but task/webhook notifications use `deliver=False` (wait for next active poll).

## Architecture

Introduce one Mission Control service that owns outbound agent wake decisions.

### Transport Types

1. `direct_session_message`
- Use the existing `GatewayDispatchService.send_agent_message` path.
- Best for: targeted board-agent delivery where Mission Control already knows the recipient session.
- This is the primary per-agent event-driven primitive available today.
- **Deliver policy:** Use `deliver=True` for event-driven wakes to achieve immediate execution. This is a behavioral change from the current `deliver=False` used by task notifications and webhooks. The change is intentional — without `deliver=True`, agents still rely on heartbeat polling to discover the queued message.

2. `system_wake`
- Use gateway RPC `wake` with `{text, mode}`.
- Best for: gateway-main or default-agent work where a generic main-session wake is acceptable.
- Do **not** assume this can target an arbitrary board-agent heartbeat session.
- Note: The `wake` RPC method is listed in `GATEWAY_METHODS` but has zero existing usage in the MC codebase. Verify behavior on the actual gateway before relying on it for production routing.

3. `isolated_turn`
- Use gateway HTTP `POST /hooks/agent`.
- Best for: scoped, high-signal tasks where Mission Control already knows the exact payload to process.
- Keeps expensive work out of the main heartbeat session.
- **IMPORTANT: Unverified dependency.** Neither `/hooks/agent` nor `/hooks/wake` HTTP endpoints have any existing usage or verification in the MC codebase. Before implementing Task 4, verify these endpoints exist on the target gateway. If `/hooks/agent` is unavailable, do **not** invent synthetic per-job session keys. Keep webhook delivery on the existing `direct_session_message` path for that gateway and treat `isolated_turn` as unsupported there until OpenClaw hook support is confirmed.

4. `future_targeted_wake`
- Reserved for a possible later OpenClaw enhancement that supports agent-targeted heartbeat wake directly.
- Not part of the first implementation.

### Routing Rules

Use `direct_session_message` when Mission Control needs to reach a specific board agent or lead with known context:
- New unassigned task for the lead.
- Task returned to inbox for the lead.
- Approval resolved for the lead.
- Task assignment or rework request for a worker.
- Task comment mention for assignee or mentioned agent.
- Group-level broadcast or direct mention.

Use `isolated_turn` when Mission Control has a concrete unit of work (pending endpoint verification):
- A board webhook payload with a specific triage instruction.
- A targeted "summarize / classify / reconcile this payload" job.
- A single external event that should not consume main-session history.

Use `system_wake` only when a gateway-wide or default main-session wake is correct:
- Gateway-main automation.
- A global "check now" operator action.
- A low-priority deferred nudge routed to the default/main agent intentionally.

### Known Gaps in Event Coverage

These work-discovery paths currently rely on heartbeat polling and are NOT covered by event-driven wake in the first implementation:
- **Task dependency unblocking:** When a blocking task completes, the assignee of the now-unblocked task is not notified. Add `direct_session_message` for this in Phase 2.
- **Human-initiated status changes:** When a human moves a task status, no agent notification fires. Lower priority — human actions are less time-sensitive.
- **Board/agent config changes:** When workspace files or board settings change, agents discover via heartbeat. Can be routed through `system_wake` in a future phase.

The safety-net heartbeat covers these gaps until explicit event routing is added.

### Safety Net

Do not remove heartbeats entirely in the first pass.

Set heartbeats to recovery mode in two stages:
- Stage 1: keep cadence within current Mission Control liveness expectations. Apply `isolatedSession: true` and `lightContext: true` (covered by the heartbeat token optimization plan).
- Stage 2: after liveness is decoupled from heartbeat cadence, reduce further.

Stage 1 recommended posture:
- Lead agents: keep at `10m` until `OFFLINE_AFTER` no longer assumes heartbeat-driven liveness.
- Worker agents: keep at `10m` initially, then reduce board-by-board only after proving event coverage.

Important liveness constraint:
- A wake being sent is **not** itself a check-in.
- `last_seen_at` only advances when the agent later makes an authenticated Mission Control request or heartbeat.
- Mission Control's lifecycle reconcile path still expects prompt post-wake check-in behavior for lifecycle wakes.
- Therefore, do not assume event delivery alone is enough to support slower heartbeat cadences.

Stage 2 recommended posture:
- Lead agents: `30m` to `60m`.
- Worker agents: `2h` to `6h`, or disabled on boards with verified full push coverage.

The heartbeat then serves two purposes only:
- Recover from missed events.
- Periodically detect drift or stalled work.

## Implementation Plan

### Task 0: Verify gateway hook endpoints

**Before any implementation**, verify that the gateway HTTP hook endpoints exist and work.

```bash
# Test /hooks/agent
curl -v -X POST "<gateway-http-base-url>/hooks/agent" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <gateway-token>" \
  -d '{"agent": "<agent-id-or-session>", "message": "test"}'

# Test /hooks/wake
curl -v -X POST "<gateway-http-base-url>/hooks/wake" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <gateway-token>" \
  -d '{"text": "test", "mode": "now"}'

# Test wake RPC via WebSocket (already available)
# This uses the existing openclaw_call pattern
```

Document the request/response format for each endpoint. If `/hooks/agent` returns 404 or unexpected behavior, mark `isolated_turn` unsupported for that gateway and keep webhook delivery on the existing `direct_session_message` path.

### Task 1: Add a shared event wake service

**Files:**
- Create: `backend/app/services/openclaw/event_wake.py`
- Create: `backend/tests/test_event_wake_service.py`
- Modify: `backend/app/services/openclaw/gateway_dispatch.py`

Create a single service that accepts a normalized wake intent and selects the transport.

The service should extend `OpenClawDBService` (matching existing patterns like `GatewayDispatchService` and `AgentLifecycleOrchestrator`) and instantiate `GatewayDispatchService` internally for `direct_session_message` routing.

Suggested API:

```python
class AgentWakeIntent(BaseModel):
    board_id: UUID
    agent_id: UUID | None = None
    kind: Literal["system_wake", "isolated_turn", "direct_session_message"]
    reason: str
    title: str
    body: str
    dedupe_key: str
    priority: Literal["high", "normal", "low"] = "normal"
    deliver: bool = True
```

Service responsibilities:
- Resolve board -> gateway config.
- Resolve target agent session / lead session when needed.
- Route `direct_session_message` through `GatewayDispatchService` with `deliver=intent.deliver`.
- Call gateway RPC `wake` for `system_wake`.
- Call gateway hook `POST /hooks/agent` for `isolated_turn` when Task 0 verifies support.
- If hooks are unsupported on a gateway, return a structured `unsupported_transport` result so callers can deliberately degrade webhook handling to `direct_session_message` instead of pretending an isolated run happened.
- Return a structured result that can be logged into activity.

Test cases:
- `direct_session_message` chooses session-targeted dispatch.
- `system_wake` chooses gateway RPC wake.
- `isolated_turn` chooses hook client.
- unsupported hook transport returns a non-raising unsupported result.
- missing gateway/session returns a non-raising skipped result.
- dedupe key is preserved for caller-side logging.

### Task 2: Centralize dedupe and coalescing

**Files:**
- Create: `backend/app/services/openclaw/event_wake_dedupe.py`
- Create: `backend/tests/test_event_wake_dedupe.py`

Mission Control should not fire one LLM run per row mutation if five related mutations happen within seconds.

**Implementation approach:** Use Redis `SET NX EX` (first-write-wins within TTL) for simplicity. No coalescing queue worker needed in the first pass.

**Specification:**
- Redis key format: `wake:dedup:{agent_id}:{kind}:{dedupe_key}`
- TTL: 30 seconds (coalesces rapid mutations within a heartbeat-scale window)
- High-priority events (`priority="high"`) bypass dedupe entirely (direct mentions, explicit rework requests).
- Normal/low priority events are deduplicated.
- If Redis is unavailable, **fail open** — fire the event without deduplication. Never silently drop events due to infrastructure failure.
- Use synchronous `redis.Redis` calls (matching the existing `queue.py` pattern). The wake service will call dedupe from async handlers via `asyncio.to_thread` or by keeping the Redis call synchronous (sub-millisecond operation).

Test cases:
- First write for a key passes through.
- Second write within TTL is suppressed.
- High-priority events bypass dedupe.
- Redis unavailable → event fires (fail-open).
- Different dedupe keys → both pass through.

### Task 3: Route existing event sources through the shared service

**Files:**
- Modify: `backend/app/api/tasks.py` (`_notify_agent_on_task_assign`, `_notify_lead_on_task_create`, `_notify_agent_on_task_rework`, `_notify_lead_on_task_unassigned`, `_notify_task_comment_targets`)
- Modify: `backend/app/api/approvals.py` (`_notify_lead_on_approval_resolution`)
- Modify: `backend/app/api/board_memory.py` (`_notify_chat_targets`)
- Modify: `backend/app/api/board_group_memory.py` (`_notify_group_memory_targets`)
- Modify: `backend/app/services/webhooks/dispatch.py` (`_notify_target_agent`)

Replace transport-specific notification logic with routing through `AgentWakeService`.

Initial mapping:

Worker-facing:
- Task assigned -> `direct_session_message` (deliver=True).
- Rework requested -> `direct_session_message` (deliver=True).
- Task comment mention -> `direct_session_message` (deliver=True, priority=high).
- Direct @-mention in board/group memory -> `direct_session_message` (deliver=True, priority=high).

Lead-facing:
- New task created -> `direct_session_message` (deliver=True).
- Task returned to inbox -> `direct_session_message` (deliver=True).
- Approval resolved -> `direct_session_message` (deliver=True).
- `@lead` mention in task comment / board memory -> `direct_session_message` (deliver=True, priority=high).

Webhook-facing:
- Board webhook payload -> `isolated_turn` for the selected target agent or lead on gateways with verified hook support.
- Board webhook payload -> existing `direct_session_message` path on gateways where hooks are unverified or unsupported.

Gateway-main / operator-facing:
- Explicit "check now" button or admin action -> `system_wake`.

The first pass preserves current message content while changing only the dispatch layer and adding `deliver=True` for immediate execution.

### Task 4: Add gateway hook client support

**Files:**
- Create: `backend/app/services/openclaw/hook_client.py`
- Create: `backend/tests/test_hook_client.py`

**Prerequisite:** Task 0 must confirm endpoint availability. If endpoints are unavailable, skip this task and keep webhook delivery on the existing `direct_session_message` path.

Mission Control already stores gateway URL, token, and TLS policy. Use that to build a hook client.

Requirements:
- Convert gateway URL from `ws://`/`wss://` to `http://`/`https://`.
- Authenticate with the gateway token using supported headers (verify format in Task 0).
- Support `/hooks/agent` and `/hooks/wake`.
- Respect `allow_insecure_tls` for HTTPS gateways.
- Treat `200` / `202` as success depending on endpoint.
- On failure, return a structured error (not raise) so the wake service can record it and the caller can explicitly choose whether to fall back to `direct_session_message` for degraded delivery.

Do not embed secrets or board ids in committed docs or test fixtures beyond synthetic values.

### Task 5: Retune heartbeat defaults for recovery mode

**Note:** If the heartbeat token optimization plan has already been executed, this task is partially complete. The `DEFAULT_HEARTBEAT_CONFIG` change and per-agent intervals would already be in place. This task adds the provisioning-side check for gateway compatibility.

**Files:**
- Modify: `backend/app/services/openclaw/constants.py`
- Modify: `backend/app/services/openclaw/provisioning.py`
- Create: `backend/tests/test_gateway_heartbeat_defaults.py`

Retune heartbeat defaults only in a way that stays consistent with Mission Control liveness.

Stage 1 baseline:

```python
DEFAULT_HEARTBEAT_CONFIG = {
    "every": "10m",
    "target": "last",
    "includeReasoning": False,
    "lightContext": True,
    "isolatedSession": True,
}
```

Notes:
- Mission Control currently computes offline status from `last_seen_at` with a 10 minute threshold, so moving heartbeat beyond that threshold would mark idle agents offline unless liveness is redesigned in parallel.
- If a target gateway version does not support `lightContext` / `isolatedSession`, omit those keys during patch generation instead of hard failing.
- Board-group APIs can still override cadence per group where tighter recovery loops are needed.
- Event-driven wakes may eventually lead to agent API activity that touches `last_seen_at`, but that happens only if the agent actually performs an authenticated Mission Control request after being woken. Wake enqueue/send events must not be treated as liveness by themselves.
- Keep the `10m` safety heartbeat until either: (a) a separate explicit check-in mechanism exists for wake-driven runs, or (b) production evidence shows the relevant wake paths reliably produce timely authenticated MC activity.

Future liveness follow-up:
- Add a separate plan to decouple liveness from heartbeat cadence, then revisit `30m+` defaults.

### Task 6: Add observability for wake efficacy

**Files:**
- Modify: `backend/app/services/activity_log.py`
- Modify: `backend/app/api/metrics.py`
- Create: `backend/tests/test_event_wake_metrics.py`

Track whether event-driven wake actually replaces polling.

Emit activity / metrics for:
- `agent.wake.enqueued`
- `agent.wake.sent`
- `agent.wake.skipped_deduped`
- `agent.wake.failed`
- `agent.hook.sent`
- `agent.hook.failed`

Success criteria:
- Number of worker heartbeats falls sharply.
- Time from task assignment to first agent action decreases.
- Missed-work incidents do not increase.

## Testing Strategy

### Unit tests
- Wake routing picks the expected transport for each intent kind.
- Dedupe suppresses duplicate low-value wakes within TTL.
- High-priority events bypass dedupe.
- Hook client normalizes gateway URL correctly.
- Heartbeat provisioning emits reduced-cost config.

### Integration tests
- Task assignment enqueues one assignee targeted dispatch with `deliver=True`.
- New task creation enqueues one lead targeted dispatch.
- Task comment mention enqueues one assignee dispatch with `priority=high`.
- Approval resolution enqueues one lead targeted dispatch.
- Webhook ingestion produces an isolated-turn dispatch on gateways with verified hook support.
- Webhook ingestion degrades to the current direct-session notification path on gateways without verified hook support.
- When dispatch fails, activity is recorded and the system does not mark the event handled silently.
- When Redis is unavailable for dedupe, events fire without deduplication (fail-open).
- When gateway is offline, wake is recorded as failed and not silently dropped.

### Manual validation
1. Provision a board with one lead and one worker.
2. Assign a task and confirm the worker is triggered without waiting for the next 10-minute heartbeat.
3. Move a task back to inbox and confirm the lead is triggered.
4. Post a board webhook payload and confirm the target agent receives an isolated run on hook-capable gateways, or the existing direct-session notification on gateways without hook support.
5. Lower heartbeat cadence and verify the board still recovers from a simulated dropped event.
6. Verify observability: check the activity log for `agent.wake.sent`, `agent.wake.skipped_deduped`, and `agent.wake.failed` events with correct metadata.

## Rollout

Phase 1:
- Add `AgentWakeService` and route webhook dispatch through it.
- Keep existing direct session message behavior for task / approval notifications.
- Treat webhook `isolated_turn` as opt-in per gateway until Task 0 verification is complete.

Phase 2:
- Standardize lead and worker event delivery on `direct_session_message` with `deliver=True`.
- Add coalescing and reduce duplicate notifications.
- **Gate:** Phase 2 observability metrics (`agent.wake.*` from Task 6) must be in place and monitored for at least 1 week before proceeding to Phase 3.

Phase 3:
- Convert webhook processing to `isolated_turn` by default on gateways with verified hook support.
- Add task dependency unblocking as a `direct_session_message` event.
- Add separate liveness redesign if slower heartbeat cadence is still desired.

Phase 4:
- Re-evaluate whether any worker boards can run with heartbeat disabled entirely after liveness decoupling.

## Design Decisions

**D1: Do not remove heartbeats on day one.** Event-driven systems fail differently than polling systems. Keep a slow safety heartbeat until wake delivery has metrics.

**D2: Targeted board-agent delivery should use session messages or isolated turns, not generic wake.** Reserve `system_wake` for gateway-main/default-session use cases unless OpenClaw later adds a targeted wake API.

**D2a: Use the webhook for isolated work, or do not claim isolation.** `/hooks/agent` is the only candidate surface in this integration that can plausibly provide a true isolated agent turn. If that hook is unavailable, degrade to existing direct-session messaging and keep calling it degraded delivery rather than manufacturing unsupported per-job session keys.

**D3: Reuse existing push paths first, then standardize.** Mission Control already has working dispatch for task, approval, memory, and webhook notifications. The first implementation should unify policy, not rewrite all message bodies.

**D4: Dedupe is mandatory.** Without coalescing, event-driven wake will merely trade token waste for event storms.

**D5: `deliver=True` is the default for event-driven wakes.** This is a deliberate behavioral change from the current `deliver=False` used by some notification paths. Without immediate delivery, agents still rely on heartbeat polling to discover queued messages, defeating the purpose of event-driven wake.

**D6: Fail open on infrastructure issues.** If Redis dedupe is unavailable, fire the event anyway. If the gateway is offline, record the failure. Never silently drop events.

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Work discovery | Polling heartbeat | Push on state change |
| Worker idle heartbeats | Every 10m | Rare safety-only |
| Lead backlog discovery | Polling + ad hoc messages | Push + compatibility heartbeat |
| Webhook triage | Message into main session | Isolated turn by default |
| Token burn | Dominated by polling | Dominated by real work |

## Non-Goals

- Do not redesign the board task model.
- Do not remove existing direct session messages in the first pass.
- Do not require OpenClaw changes for the initial rollout if Mission Control can already use existing gateway RPC + hooks.
