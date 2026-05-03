# mc-gateway-subscriber

Long-lived worker that opens a persistent WebSocket to the OpenClaw
gateway, sends the connect handshake, subscribes to event streams, and
dispatches incoming events to registered handlers.

Design rationale: see
`docs/plans/2026-05-02-gateway-event-subscriber-design.md`.

## What it does today (slice 4)

- Connects to gateway WS, completes handshake (`connect.challenge` →
  `connect` req → `res`) in control-UI mode.
- Sends configured subscription RPCs (default: `sessions.subscribe`).
- Persists every `sessions.changed` event into
  `gateway_session_state` (composite PK `(agent_id, session_label)`)
  via `DbSessionStateProjector`. Last-write-wins on `last_changed_at_ms`
  and field-equal diff guard skip the heartbeat-tick no-op writes.
- Reconnects with exponential backoff on drop; re-handshakes and
  re-subscribes.
- SIGTERM / SIGINT → clean shutdown.

Slice 5 wires the projected state into
`/api/v1/agent/boards/{id}/lead/next-action` so
`details.gateway_session` populates `inspect_stale_in_progress`
actions; the lead playbook (`lead-next-action-gate` skill) reads it
to distinguish "agent silent on the gateway" from "agent active but
task DB unmoved".

## Install

On the host that hosts MC backend (`.64` in current topology):

1. Env file: paste into `/etc/mc-gateway-subscriber/env` (mode 0600,
   owner `mcontrol:mcontrol`):

   ```
   OPENCLAW_GATEWAY_WS_URL=ws://192.168.2.60:18789/ws
   OPENCLAW_GATEWAY_TOKEN=<paired-operator-token>
   DATABASE_URL=postgresql://mcontrol:<pw>@192.168.2.66/mission_control
   ```

   That's the full set. The worker constructs its own DB engine from
   `DATABASE_URL` — it does NOT load `app.core.config.settings`, so
   `AUTH_MODE` / `LOCAL_AUTH_TOKEN` / `BASE_URL` (the HTTP-layer
   keys the API process needs) are not required and not consulted.
   Use the same `DATABASE_URL` the API process writes to so the
   projector lands in the production `gateway_session_state` table.

   The gateway token comes from a paired operator device. To mint one:
   ```
   ssh root@192.168.2.60 'openclaw node.pair.request --role operator --scopes operator.read'
   # operator approves on .60, copy the issued token
   ```

2. Log directory:
   ```
   sudo install -o mcontrol -g mcontrol -m 0750 -d /var/log/mc-gateway-subscriber
   ```

3. Install the systemd unit:
   ```
   sudo cp backend/app/services/mc_gateway_subscriber/mc-gateway-subscriber.service \
     /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now mc-gateway-subscriber.service
   ```

4. Verify:
   ```
   journalctl -u mc-gateway-subscriber.service -f
   # Expect: connect.challenge handshake → subscribe sent → quiet (no
   # events yet because slice 2 doesn't register any handlers).
   ```

## Operator commands

| Action | Command |
|---|---|
| Tail logs | `journalctl -u mc-gateway-subscriber.service -f` |
| Restart cleanly | `sudo systemctl restart mc-gateway-subscriber.service` |
| Stop | `sudo systemctl stop mc-gateway-subscriber.service` |
| Rotate token | edit `/etc/mc-gateway-subscriber/env`, then restart |

## Periodic cleanup

The projection table accumulates rows for hard-deleted owners across
all three projection namespaces (`mc-<uuid>` → `agents.id`,
`mc-gateway-<uuid>` → `gateways.id`, `lead-<uuid>` → `boards.id`). At
the current scale (~100 active sessions) this is a slow leak, but
running the cleanup periodically keeps the table bounded:

```python
# scripts/cleanup_gateway_session_state.py
import asyncio
import os
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.url import normalize_database_url
from app.services.mc_gateway_subscriber.session_state_repo import (
    cleanup_orphaned_session_states,
)

async def main() -> None:
    engine = create_async_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        deleted = await cleanup_orphaned_session_states(session)
        await session.commit()
        print(f"deleted {deleted} orphaned rows")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
```

Schedule via systemd timer (daily is fine):
```
[Unit]
Description=Purge gateway_session_state rows for hard-deleted agents
[Timer]
OnCalendar=daily
[Install]
WantedBy=timers.target
```

All three projection namespaces are tracked symmetrically:

| Prefix | Owning model | Cleaned when… |
|---|---|---|
| `mc-<uuid>` | `agents.id` | the agent is hard-deleted |
| `mc-gateway-<uuid>` | `gateways.id` | the gateway is hard-deleted |
| `lead-<uuid>` | `boards.id` | the board is hard-deleted |

Rows whose `agent_id` doesn't match one of these prefixes — or whose
tail isn't a parseable UUID — are left alone for manual operator
review.

## Module map

- `subscriber.py` — `Subscriber` class. Pure protocol; no env, no
  signal handling. Tested by `tests/test_mc_gateway_subscriber.py`.
- `session_state_projector.py` — in-memory projector + parser
  (`SessionState`, `parse_session_key`, `build_state_from_frame`).
  Test/dev scaffold. Tested by `tests/test_session_state_projector.py`.
- `session_state_repo.py` — read/write layer for `gateway_session_state`
  rows. Tested by `tests/test_gateway_session_state_repo.py`.
- `db_session_state_projector.py` — production projector. Persists
  via the `session_state_repo` functions with last-write-wins ts
  ordering. Tested by
  `tests/test_db_session_state_projector.py`.
- `__main__.py` — operator entry point (env resolution, signal
  handlers, projector wiring). Tested by
  `tests/test_mc_gateway_subscriber_main.py`.
- `mc-gateway-subscriber.service` — systemd unit.
