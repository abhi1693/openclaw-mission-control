# mc-gateway-subscriber

Long-lived worker that opens a persistent WebSocket to the OpenClaw
gateway, sends the connect handshake, subscribes to event streams, and
dispatches incoming events to registered handlers.

Design rationale: see
`docs/plans/2026-05-02-gateway-event-subscriber-design.md`.

## What it does today (slice 2 of N)

Operational scaffold only:
- Connects to gateway WS, completes handshake (`connect.challenge` →
  `connect` req → `res`)
- Sends configured subscription RPCs (default: `sessions.subscribe`)
- Logs every dispatched event to the systemd journal at INFO
- Reconnects with exponential backoff on drop; re-handshakes and
  re-subscribes
- SIGTERM / SIGINT → clean shutdown

What it does NOT do yet:
- No real handler. Events are received and skipped (no registered
  handler) until slice 3 wires the projector.
- No DB writes. The Task table is unaffected.

This slice exists so the deploy + operations surface (systemd unit,
env file, log path) is in place before we add behaviors that mutate
MC state.

## Install

On the host that hosts MC backend (`.64` in current topology):

1. Token: paste into `/etc/mc-gateway-subscriber/env` (mode 0600,
   owner `mcontrol:mcontrol`):

   ```
   OPENCLAW_GATEWAY_WS_URL=ws://192.168.2.60:18789/ws
   OPENCLAW_GATEWAY_TOKEN=<paired-operator-token>
   ```

   The token comes from a paired operator device. To mint one:
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
- `__main__.py` — operator entry point (env resolution, signal
  handlers). Tested by `tests/test_mc_gateway_subscriber_main.py`.
- `mc-gateway-subscriber.service` — systemd unit.

## Slices remaining

- Slice 3: register first real handler (likely `sessions.changed` →
  update `Task.runtime_status` field). Needs concrete event payload
  shape from a live probe against the gateway.
- Slice 4: surface the projected state in
  `/agent/next-action` lead signals so the lead can distinguish
  "agent is working" from "agent is wedged."

Both slices land as separate commits with TDD-driven tests.
