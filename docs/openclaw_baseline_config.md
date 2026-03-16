# OpenClaw Baseline Configuration (Getting Started)

This guide turns the provided baseline into a practical starting point for local OpenClaw setup and Mission Control integration.

For OpenClaw CLI installs, the default config path is:

- `~/.openclaw/openclaw.json`

## Baseline Config (Normalized JSON)

The config below is your provided baseline, normalized into valid JSON.

```json
{
  "env": {
    "shellEnv": {
      "enabled": true
    }
  },
  "update": {
    "channel": "stable"
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "",
        "fallbacks": []
      },
      "models": {
        "": {}
      },
      "workspace": "/home/asaharan/.openclaw/workspace",
      "contextPruning": {
        "mode": "cache-ttl",
        "ttl": "45m",
        "keepLastAssistants": 2,
        "minPrunableToolChars": 12000,
        "tools": {
          "deny": [
            "browser",
            "canvas"
          ]
        },
        "softTrim": {
          "maxChars": 2500,
          "headChars": 900,
          "tailChars": 900
        },
        "hardClear": {
          "enabled": true,
          "placeholder": "[Old tool output cleared]"
        }
      },
      "compaction": {
        "mode": "safeguard",
        "reserveTokensFloor": 12000,
        "memoryFlush": {
          "enabled": true,
          "softThresholdTokens": 5000,
          "prompt": "Write any lasting notes to memory/YYYY-MM-DD.md; reply with NO_REPLY if nothing to store.",
          "systemPrompt": "Session nearing compaction. Store durable memories now."
        }
      },
      "thinkingDefault": "medium",
      "maxConcurrent": 5,
      "subagents": {
        "maxConcurrent": 5
      }
    },
    "list": [
      {
        "id": "main"
      }
    ]
  },
  "messages": {
    "ackReactionScope": "group-mentions"
  },
  "commands": {
    "native": "auto",
    "nativeSkills": "auto"
  },
  "hooks": {
    "internal": {
      "enabled": true,
      "entries": {
        "boot-md": {
          "enabled": true
        },
        "command-logger": {
          "enabled": true
        },
        "session-memory": {
          "enabled": true
        },
        "bootstrap-extra-files": {
          "enabled": true
        }
      }
    }
  },
  "channels": {
    "defaults": {
      "heartbeat": {
        "showOk": true,
        "showAlerts": true,
        "useIndicator": true
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
    "auth": {
      "mode": "token"
    },
    "trustedProxies": [
      "127.0.0.1",
      "::1"
    ],
    "tailscale": {
      "mode": "off",
      "resetOnExit": false
    },
    "reload": {
      "mode": "hot",
      "debounceMs": 750
    },
    "nodes": {
      "denyCommands": [
        "camera.snap",
        "camera.clip",
        "screen.record",
        "calendar.add",
        "contacts.add",
        "reminders.add"
      ]
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
        "maxResults": 3,
        "maxSnippetChars": 450,
        "maxInjectedChars": 1800,
        "timeoutMs": 8000
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

## Section-by-Section Reference

This is what each section controls and why you would tune it.

### `env`

Controls runtime environment behavior.

- `env.shellEnv.enabled`: when `true`, OpenClaw can resolve environment from shell context, which helps tools and model/provider discovery behave consistently with your shell session.

Operational note:

- If shell startup is heavy or slow, consider also setting `env.shellEnv.timeoutMs` (optional key supported by schema) to cap lookup time.

### `update`

Controls update policy for npm/git installs.

- `update.channel`: release track (`stable`, `beta`, `dev`).

Recommended baseline:

- `stable` for production-ish use.
- Use `beta`/`dev` only when you actively want pre-release behavior.

### `agents`

Defines default agent runtime behavior plus agent list.

#### `agents.defaults.model`

Model routing defaults.

- `primary`: main model id for agent turns.
- `fallbacks`: ordered backup model ids used when primary fails.

Important:

- Empty `primary` means no explicit default model is selected.
- Set this before first real use.

#### `agents.defaults.models`

Per-model override map keyed by full model id.

- In your baseline, key is `""`; replace this with a real model id.
- Value object can hold per-model params in supported versions.

#### `agents.defaults.workspace`

Filesystem root for agent state/workspaces.

- Must exist and be writable by the runtime.
- Align this with Mission Control gateway `workspace_root` for consistency.

#### `agents.defaults.contextPruning`

Controls prompt-history tool-output pruning to keep context size healthy.

- `mode: "cache-ttl"`: enables pruning extension with TTL-aware behavior.
- `ttl`: minimum time before pruning runs again (example `45m`).
- `keepLastAssistants`: protects recent assistant turns from pruning cutoff.
- `minPrunableToolChars`: only hard-clear when prunable tool output is large enough.
- `tools.deny`: tool names excluded from pruning.
- `softTrim`: partial shortening of tool output.
- `hardClear`: full replacement with placeholder when limits are exceeded.

Practical effect:

- `softTrim` keeps beginning/end context for long outputs.
- `hardClear` prevents repeated old tool dumps from consuming context.

#### `agents.defaults.compaction`

Controls how conversation history is compacted and protected against token overflow.

- `mode: "safeguard"`: conservative compaction strategy.
- `reserveTokensFloor`: hard reserve to avoid running context to exhaustion.
- `memoryFlush`: pre-compaction memory checkpoint behavior.

`memoryFlush` keys:

- `enabled`: turn memory flush on/off.
- `softThresholdTokens`: triggers flush before compaction line is crossed.
- `prompt`: user-prompt text for flush turn.
- `systemPrompt`: system instruction for flush turn.

What this protects:

- Avoids losing durable context when sessions approach compaction.

#### `agents.defaults.thinkingDefault`

Default reasoning intensity for turns.

- Your baseline uses `medium` as a quality/speed balance.

#### Concurrency Controls

- `agents.defaults.maxConcurrent`: max parallel top-level runs.
- `agents.defaults.subagents.maxConcurrent`: max parallel subagent runs.

Use these to control throughput versus host/API pressure.

#### `agents.list`

Defines configured agents.

- `[{ "id": "main" }]` creates the primary default agent identity.

### `messages`

Inbound/outbound messaging behavior.

- `messages.ackReactionScope`: where ack reactions are emitted.

Allowed values:

- `group-mentions`, `group-all`, `direct`, `all`

Baseline intent:

- `group-mentions` avoids noisy acks in busy group channels.

### `commands`

Native command registration behavior for supported channels.

- `commands.native`: command registration mode (`true`/`false`/`auto`).
- `commands.nativeSkills`: skill command registration mode (`true`/`false`/`auto`).

Baseline intent:

- `auto` lets OpenClaw decide based on channel/provider capabilities.

### `hooks`

Internal hook system settings.

- `hooks.internal.enabled`: turns internal hooks system on/off.
- `hooks.internal.entries`: per-hook enable/config map.

Your baseline entries:

- `boot-md`: runs BOOT.md startup checklist hook.
- `command-logger`: writes command audit logs.
- `session-memory`: stores context when `/new` is used.
- `bootstrap-extra-files`: custom/optional hook id.

Important:

- Hook IDs not installed on the runtime are ignored or reported missing.
- Verify available hooks with `openclaw hooks list`.

### `channels`

Cross-channel defaults.

#### `channels.defaults.heartbeat`

Controls heartbeat visibility behavior (global default layer).

- `showOk`: emit explicit OK heartbeat messages.
- `showAlerts`: emit non-OK/alert heartbeat content.
- `useIndicator`: emit indicator events alongside heartbeat behavior.

Baseline intent:

- Everything on (`true`) gives explicit operational visibility.

### `gateway`

Core gateway server behavior.

#### Network & Mode

- `port`: gateway WebSocket port.
- `mode`: `local` or `remote` behavior mode.
- `bind`: exposure strategy (`loopback`, `lan`, `tailnet`, `auto`, `custom`).

Baseline choice:

- `bind: "lan"` makes gateway reachable on local network interfaces.

#### Control UI Security

- `controlUi.allowInsecureAuth: true` allows token-only auth over insecure HTTP.

Security implication:

- Good for local development convenience.
- Not recommended for exposed environments.

#### Auth

- `gateway.auth.mode`: `token` or `password`.
- With `token` mode, set `gateway.auth.token` (or provide via env/CLI override) before non-local usage.

#### Reverse Proxy Awareness

- `gateway.trustedProxies`: proxy IP allowlist used for client IP/local detection behind reverse proxies.

Why it matters:

- Prevents false local-trust behavior when proxied traffic is present.

#### Tailscale

- `gateway.tailscale.mode`: `off`, `serve`, or `funnel`.
- `resetOnExit`: whether to revert serve/funnel wiring on shutdown.

#### Config Reload

- `gateway.reload.mode`: reload strategy (`off`, `restart`, `hot`, `hybrid`).
- `gateway.reload.debounceMs`: debounce before applying config changes.

#### Node Command Policy

- `gateway.nodes.denyCommands`: hard denylist for node-exposed commands.

Baseline intent:

- Blocks risky device/system actions from remote node invocations.

### `memory`

`memory` in your baseline appears to be plugin-style configuration (for `qmd`).

Compatibility warning:

- In OpenClaw `2026.1.30` core schema, top-level `memory` is not a built-in key.
- Without a plugin that extends schema for this section, config validation reports:
  `Unrecognized key: "memory"`.

What to do:

1. If you use a plugin that defines this block, keep it and validate with your plugin set.
2. If not, remove this block and use core `agents.defaults.memorySearch` + plugin slots/entries for memory behavior.

### `skills`

Skill install/runtime behavior.

- `skills.install.nodeManager`: package manager used for skill installation workflows.

Allowed values:

- `npm`, `pnpm`, `yarn`, `bun`

Baseline choice:

- `npm` for highest compatibility.

## Validation Before Use

Do a schema check before running production workloads:

```bash
openclaw config get gateway.port
```

If invalid, OpenClaw reports exact keys/paths and remediation.

## Required Edits Before First Run

These fields should be set before using this in production-like workflows:

1. `agents.defaults.model.primary`
   Set a concrete model id, for example `openai-codex/gpt-5.2`.
2. `agents.defaults.models`
   Replace the empty key (`""`) with your model id so per-model config is mapped correctly.
3. `gateway.auth`
   If token auth is enabled, provide the token value (for example `gateway.auth.token`) via your preferred secret handling approach.
4. `memory` (top-level)
   Keep only if your runtime/plugin set supports it. Otherwise remove to pass core schema validation.

## Quick Start

1. Create the config file:

```bash
mkdir -p ~/.openclaw
```

2. Save the JSON above to:

- `~/.openclaw/openclaw.json`

3. Start the gateway:

```bash
openclaw gateway
```

4. Verify health:

```bash
openclaw health
```

5. Open the control UI:

```bash
openclaw dashboard
```

## Mission Control Connection (This Repo)

When adding a gateway in Mission Control:

- URL: `ws://127.0.0.1:18789` (or your host/IP with explicit port)
- Token: provide only if your gateway requires token auth
- Device pairing: enabled by default and recommended
  - Keep pairing enabled for normal operation.
  - Optional bypass: enable `Disable device pairing` per gateway only when the gateway is explicitly configured for control UI auth bypass (for example `gateway.controlUi.dangerouslyDisableDeviceAuth: true` plus appropriate `gateway.controlUi.allowedOrigins`).
- Workspace root (in Mission Control gateway config): align with `agents.defaults.workspace` when possible

## Security Notes

- `gateway.bind: "lan"` exposes the gateway on your local network.
- `controlUi.allowInsecureAuth: true` is development-friendly and not recommended for exposed environments.
- Use a strong token if `gateway.auth.mode` is `token`.

## Why This Baseline Works

- Sensible concurrency defaults for both primary and subagents.
- Context-pruning + compaction settings tuned to reduce context bloat.
- Memory flush before compaction to preserve durable notes.
- Conservative command deny-list for risky node capabilities.
- Stable update channel and predictable local gateway behavior.
