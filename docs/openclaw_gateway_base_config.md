# OpenClaw Gateway Base Config (Local)

This document explains a "base" OpenClaw Gateway config intended for local development and LAN use, and how to connect it to Mission Control.

Related:
- Gateway WebSocket protocol: [Gateway WebSocket protocol](openclaw_gateway_ws.md) (default URL `ws://127.0.0.1:18789`)
- Mission Control architecture (gateway integration): [Architecture deep dive](architecture/README.md)

## Who This Is For

Use this config if you want:
- A gateway listening locally (and optionally on your LAN)
- A predictable workspace location for agents/sessions
- A small, readable starting point you can extend

## Base Config (Template)

Start from this template and change the values in **Required edits**.

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai-codex/gpt-5.2"
      },
      "models": {
        "openai-codex/gpt-5.2": {}
      },
      "workspace": "~/.openclaw/workspace",
      "compaction": {
        "mode": "safeguard"
      },
      "thinkingDefault": "minimal",
      "maxConcurrent": 4,
      "subagents": {
        "maxConcurrent": 8
      }
    }
  },
  "gateway": {
    "port": 18789,
    "mode": "local",
    "bind": "lan",
    "controlUi": {
      "allowInsecureAuth": true
    },
    "tailscale": {
      "mode": "off",
      "resetOnExit": false
    },
    "reload": {
      "mode": "hot",
      "debounceMs": 750
    }
  },
  "memory": {
    "backend": "qmd",
    "citations": "auto",
    "qmd": {
      "includeDefaultMemory": true,
      "update": {
        "interval": "15m",
        "debounceMs": 15000,
        "onBoot": true
      },
      "limits": {
        "maxResults": 6,
        "maxSnippetChars": 900,
        "maxInjectedChars": 4500,
        "timeoutMs": 4000
      }
    }
  },
  "skills": {
    "install": {
      "nodeManager": "npm"
    }
  }
}
```

### Required Edits

1. `agents.defaults.workspace`
   - Set a directory the gateway can read/write.
   - Recommended default is `~/.openclaw/workspace` (Mission Control defaults the "workspace root" UI to `~/.openclaw`).

### Optional Edits (Common)

- `gateway.bind`
  - `"lan"` is convenient for reaching the gateway from another machine on your network.
  - If you want local-only access, configure your gateway to bind only to localhost/loopback (exact values depend on the gateway build) and/or firewall the port.
- `gateway.port`
  - Change if `18789` is already in use.
  - Mission Control requires the URL to include an explicit port (example: `ws://127.0.0.1:18789`).
- `agents.defaults.model.primary`
  - Set your preferred default model identifier.
- `memory.qmd.limits`
  - Tune memory query/injection sizes if you see timeouts or overly-large prompts.

## What Each Top-Level Section Does

### `agents.defaults`

Default runtime behavior for agents created/managed by the gateway:
- `model.primary`: default model identifier
- `models`: per-model overrides (empty means "use provider defaults")
- `workspace`: where agent state/files live on disk
- `compaction.mode: "safeguard"`: enables conservative compaction behavior
- `thinkingDefault: "minimal"`: default "thinking" level
- `maxConcurrent`: max concurrent top-level runs
- `subagents.maxConcurrent`: max concurrent subagent runs

### `gateway`

Network/runtime settings for the gateway service itself:
- `port`: TCP port for the WebSocket server (protocol doc defaults to `18789`)
- `mode: "local"`: local mode (vs remote-managed)
- `bind: "lan"`: binds in a way that's reachable from your LAN (treat as "network exposed")
- `controlUi.allowInsecureAuth: true`: convenience for local dev; do not use as-is for production
- `tailscale.mode: "off"`: disables Tailscale integration by default
- `reload.mode: "hot"` + `reload.debounceMs`: enables hot reload of config with a debounce window

### `memory`

Configures the gateway's memory subsystem.
- `backend: "qmd"`: use the QMD backend
- `citations: "auto"`: automatically include citations when supported
- `qmd.includeDefaultMemory`: includes default memory sources
- `qmd.update`: periodic update settings
- `qmd.limits`: bounds for query size/latency and injected context

### `skills.install.nodeManager`

Controls which Node package manager is used for skill installation.
- `"npm"` is the most compatible baseline.

## Connecting Mission Control To The Gateway

Mission Control connects over WebSockets and supports passing a token.

What Mission Control expects:
- Gateway URL must be `ws://...` or `wss://...` and must include an explicit port.
- Token is optional. Empty/whitespace tokens are treated as "no token" by the Mission Control API.

In the Mission Control UI:
1. Go to "Gateways" and add a new gateway.
2. Set URL to something like `ws://127.0.0.1:18789` (or your LAN host/IP + port).
3. If your gateway is configured to require a token, paste it here. Otherwise leave blank.
4. Use the "Check connection" action to confirm reachability.

Implementation note (how Mission Control sends tokens):
- If you provide a token, Mission Control's backend will include it when connecting to the gateway (it attaches it to the URL query string and also sends it in the `connect` params). See `backend/app/services/openclaw/gateway_rpc.py`.

### Workspace Root (Mission Control) vs Workspace (Gateway)

Mission Control stores a `workspace_root` value per gateway (configured in the UI). This is used when generating agent context/templates (for example, to compute a per-agent `workspace_path`). See `backend/app/services/openclaw/provisioning.py`.

The gateway config's `agents.defaults.workspace` is a separate setting that controls where the gateway runtime actually reads/writes agent state on disk.

For the smoothest onboarding, set these so the paths you show agents match what exists on the gateway host.

## Security Notes (Read This If You Expose The Gateway)

- Treat `gateway.bind: "lan"` as "this is reachable by other devices on your network".
- `controlUi.allowInsecureAuth: true` is for convenience in local dev. If you run this beyond your laptop, tighten this setting and prefer TLS (`wss://`) and network-level protections.
