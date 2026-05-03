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

What it does NOT do yet:
- No `/agent/next-action` integration — slice 5 surfaces the projected
  state in lead signals.

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

## Module map

- `subscriber.py` — `Subscriber` class. Pure protocol; no env, no
  signal handling. Tested by `tests/test_mc_gateway_subscriber.py`.
- `session_state_projector.py` — in-memory projector + parser
  (`SessionState`, `parse_session_key`, `build_state_from_frame`).
  Test/dev scaffold. Tested by `tests/test_session_state_projector.py`.
- `session_state_repo.py` — read/write layer for `gateway_session_state`
  rows. Tested by `tests/test_gateway_session_state_repo.py`.
- `db_session_state_projector.py` — production projector. Persists
  via `SessionStateRepo` with last-write-wins ts ordering and a
  field-equal diff guard. Tested by
  `tests/test_db_session_state_projector.py`.
- `__main__.py` — operator entry point (env resolution, signal
  handlers, projector wiring). Tested by
  `tests/test_mc_gateway_subscriber_main.py`.
- `mc-gateway-subscriber.service` — systemd unit.

## Slices remaining

- Slice 5: surface the projected state in `/agent/next-action` lead
  signals so the lead can distinguish "agent is working" from "agent
  is wedged" without polling the gateway directly. Adds a thin read
  endpoint over `SessionStateRepo.list_for_agent`.
