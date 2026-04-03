# MC-Driven Heartbeat Monitor

## Problem

The gateway's internal heartbeat timer is unreliable — it dies after restarts, activeHours pauses, and OpenClaw updates. When the Supervisor's timer dies, the whole agent team goes idle because nobody nudges workers. Manual intervention is required every time.

## Solution

MC periodically sweeps for stale agents and triggers recovery via the gateway RPC. This uses existing MC infrastructure (RQ, lifecycle reconcile, gateway RPC) rather than building a parallel system.

## Architecture

```
┌─────────────────────────────────────────────┐
│ MC Backend (.64)                             │
│                                              │
│  RQ scheduled sweep (every 5min)             │
│    1. Query: agents WHERE                    │
│       checkin_deadline_at <= now              │
│       AND wake_attempts < 3                  │
│    2. For each stale agent:                  │
│       - Attempt 1: nudge via gateway RPC     │
│       - Attempt 2+: wake via gateway RPC     │
│    3. Enqueue reconcile task (existing flow) │
│    4. Log + increment wake_attempts          │
│                                              │
│  Uses existing:                              │
│    - lifecycle_queue.py (RQ)                 │
│    - lifecycle_reconcile.py (per-agent)      │
│    - gateway_rpc.py (WebSocket RPC)          │
│    - coordination_service.py (nudge/wake)    │
└──────────────┬──────────────────────────────┘
               │ WebSocket RPC
┌──────────────▼──────────────────────────────┐
│ Gateway (.60)                                │
│  nudge → sends message without session reset │
│  wake → resets session + sends wakeup        │
│  Agent runs heartbeat → posts to MC          │
└─────────────────────────────────────────────┘
```

## Which Agents Are Monitored

All agents with `heartbeat_config.every != "0m"` (and not disabled/null). Currently only the Supervisor (`every: "5m"`). If more agents get heartbeats enabled in the future, they're automatically included.

## Stale Detection

Use `checkin_deadline_at` from the database — NOT `last_seen_at`. The `last_seen_at` field is updated by any authenticated request (not just heartbeats), which would mask heartbeat failures. The `checkin_deadline_at` field is set by the lifecycle orchestrator after each real heartbeat or wake.

Query: `SELECT * FROM agents WHERE checkin_deadline_at <= now() AND wake_attempts < 3 AND heartbeat_config->>'every' NOT IN ('0', '0m', 'off', 'none', 'disabled')`

## Recovery Ladder

| Attempt | Action | Disruption |
|---------|--------|------------|
| 1st stale detection | **Nudge** via gateway RPC | None — sends message to existing session |
| 2nd (still stale after next sweep) | **Wake** via gateway RPC | Resets session, sends wakeup message |
| 3rd | **Mark offline**, alert @Miguel via board memory | Agent stops being woken |

The existing `wake_attempts` cap (3, from `constants.py`) is used. Backoff between attempts is handled by the 5-minute sweep interval (minimum 5 min between attempts).

## Implementation

### New file: `backend/app/services/openclaw/heartbeat_monitor.py`

```python
async def check_and_wake_stale_agents(session: AsyncSession):
    """Sweep for agents with expired checkin_deadline_at and trigger recovery."""
    
    # 1. Query stale agents
    stale = await get_stale_agents(session)  # checkin_deadline_at <= now, wake_attempts < 3
    
    for agent in stale:
        if agent.wake_attempts == 0:
            # First attempt: nudge (non-disruptive)
            await nudge_agent_via_rpc(agent)
        elif agent.wake_attempts < 3:
            # Subsequent: wake (session reset)
            await wake_agent_via_rpc(agent)
        
        agent.wake_attempts += 1
        agent.last_wake_sent_at = utcnow()
        
        # Enqueue reconcile task (existing flow)
        defer_lifecycle_reconcile(agent)
    
    if agent.wake_attempts >= 3:
        # Escalate — mark offline, alert user
        await escalate_offline_agent(agent)
```

### RQ job registration

Add to existing RQ setup:

```python
# In lifecycle_queue.py or new heartbeat_queue.py
def schedule_heartbeat_sweep():
    """Schedule periodic heartbeat monitor sweep."""
    queue.enqueue_in(
        timedelta(minutes=5),
        check_and_wake_stale_agents,
        job_id="heartbeat-sweep",
        at_front=False,
    )
```

### FastAPI startup hook

```python
# In app startup
@app.on_event("startup")
async def start_heartbeat_monitor():
    schedule_heartbeat_sweep()  # Enqueue first RQ sweep
```

## What NOT to Do

- **Don't use `last_seen_at`** for stale detection — it's updated by any API call
- **Don't fake heartbeats** — `heartbeat` is an event, not an RPC method
- **Don't add a FastAPI asyncio loop** — risky with multiple workers/replicas
- **Don't use subprocess `openclaw agent` from MC** — MC is on .64, gateway is on .60
- **Don't wake agents mid-turn without nudging first** — wake resets the session

## Dependencies

- Existing: `lifecycle_queue.py`, `lifecycle_reconcile.py`, `gateway_rpc.py`, `coordination_service.py`
- No new dependencies required
- Uses existing RQ + Redis infrastructure (`mc-rq-worker`)

## Testing

1. Disable Supervisor heartbeat timer (simulate gateway restart)
2. Wait 10+ minutes (2x interval)
3. Verify MC sweep detects stale `checkin_deadline_at`
4. Verify nudge fires on first detection
5. Verify wake fires on second detection
6. Verify wake_attempts caps at 3
7. Verify agent comes back online after nudge/wake

## Migration

No database changes required — uses existing `checkin_deadline_at`, `wake_attempts`, `last_wake_sent_at` columns.
