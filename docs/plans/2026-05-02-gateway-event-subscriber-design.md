# Gateway Event Subscriber — Design

**Date:** 2026-05-02
**Branch:** `feature/gateway-event-subscriber`
**Status:** kickoff design, awaiting key decisions

## Goal

MC backend opens a persistent WebSocket connection to the OpenClaw
gateway (4.29+), subscribes to lifecycle event streams, and projects
those events into MC's data model so the lead next-action,
review-readiness, and parent-cascade gates can react in real time
instead of polling.

## Why now

Today MC is fully poll-driven. The lead's `/agent/next-action` runs
every heartbeat (1-5 minutes), reads the MC DB, picks the next action.
The gateway already has push-style event streams MC isn't using:

| Today (poll) | With subscription (push) |
|---|---|
| Lead polls `/agent/next-action` every heartbeat | Lead reacts to `sessions.subscribe` events as they fire |
| MC infers ACP child completion from session jsonl mtimes / agent comments | `node.event` / `agent.wait` deliver completion events directly |
| Approval state polled per task | `exec.approval.requested` / `resolve` events stream live |
| Stuck-session reasons (4.29 feature) only in `journalctl` | Gateway broadcasts can be ingested into a queryable MC table |

Concrete user-visible improvement: the lead reacts to a worker
finishing within seconds, not minutes. Stuck-session reasons surface
in next-action signals.

## Out of scope (this design)

- Replacing existing poll paths. The subscription augments next-action;
  it does not delete the heartbeat-driven poll.
- Acting on every gateway event. Initial scope is narrow.
- Multi-gateway support. One gateway → one MC backend.

## Key decisions (need operator input)

These shape everything. Numbered for reply ergonomics.

### Decision 1: process model — WHERE does the WS client live?

| Option | Pros | Cons |
|---|---|---|
| **A. Background `asyncio.Task` inside FastAPI process** | Smallest deploy delta. Reuses MC's session, settings, logger. | FastAPI workers get restarted (uvicorn `--reload`, deploy script). Long-lived task fights the workers' lifecycle. Single-worker MC only. |
| **B. Separate `mc-gateway-subscriber` systemd worker (or container)** | Clean separation. Survives MC API restart. Can crash independently without taking MC down. | New deploy unit. New ops surface. Must coordinate restarts when MC schema changes. |
| **C. Sidecar in same docker-compose service group** | Middle ground. Same deploy artifact, separate process. | Only works if MC is containerized (it currently is). Healthcheck/orchestration touch. |

**Recommendation: B.** MC's heartbeat-driven supervisor pattern is
already a "long-running orchestrator" model; adding a second
long-running process for gateway events fits cleanly. The subscriber
crashes don't take down MC's HTTP API.

### Decision 2: event projection target — where do events LAND?

| Option | Pros | Cons |
|---|---|---|
| **A. Direct DB writes** (subscriber writes to MC tables) | Simple. Read path unchanged. | Subscriber needs to know MC schema. Schema migrations risk. |
| **B. Append-only `gateway_events` table + projector job** | Capture-everything; can replay if projection is wrong. Subscriber doesn't need MC's domain model. | Two-step: write event, then projector mutates state. More moving parts. |
| **C. Pub/sub (Redis Streams)** | Decouples. Multiple consumers. | New infra dependency. |

**Recommendation: A** for the first slice. Subscriber writes a small
set of fields directly to existing MC tables (e.g., set
`Task.last_session_event_at`, `Task.runtime_status`). When we have
real operational experience, revisit (B) for replay capability.

### Decision 3: initial subscription scope — which streams FIRST?

Multiple choice (pick one or more for the v1 ship):

- **(i)** `node.event` — ACP child session completion / abort. Smallest concrete value: MC stops inferring ACP completion from session jsonl mtimes.
- **(ii)** `sessions.subscribe` — full session lifecycle (state changes, message arrivals).
- **(iii)** `exec.approval.requested` / `exec.approval.resolved` — approval gating signals.
- **(iv)** `presence` — connected operator/node device state.

**Recommendation: (i) only for v1.** Smallest blast radius, most
operator-visible win. Add (ii) and (iii) once subscriber is proven
stable for two weeks.

### Decision 4: auth + token rotation

Gateway uses scoped bearer tokens issued at device pairing. MC
backend needs one.

- Generate via `openclaw node.pair.*` flow on `.60`, scope to
  operator-read.
- Store in MC's secret pattern: `/etc/mc-gateway-subscriber/env`
  (mode 0600, parallel to `/etc/mc-hooks/env`).
- Rotation: SIGUSR1 to subscriber process re-reads token from file.

No major decision; just confirming this matches your secret-management
preferences.

## Architecture sketch (assuming B + A + (i))

```
                        ┌────────────────────────────┐
                        │  mc-gateway-subscriber     │
                        │  (systemd, on .64 or .60)  │
                        │                            │
        WS ws://.60:18789 ─▶  websockets/aiohttp    │
                        │     │                       │
                        │     ▼                       │
                        │  EventDispatcher            │
                        │     │                       │
                        │     ▼                       │
                        │  NodeEventProjector         │
                        │  (matches Phase V cascade   │
                        │   semantics; writes Task    │
                        │   + ActivityEvent rows)     │
                        └────────────┬───────────────┘
                                     │
                                     ▼
                          ┌─────────────────┐
                          │  MC Postgres    │
                          │  (.66:5432)     │
                          └─────────────────┘
                                     ▲
                                     │
                          ┌──────────┴──────────┐
                          │  MC FastAPI (.64)   │
                          │  /agent/next-action │
                          │  reads fresh state  │
                          └─────────────────────┘
```

## Failure modes & mitigations

| Mode | Mitigation |
|---|---|
| WS drops mid-flight | Exponential backoff reconnect; persist `last_event_id` to file; resume from there if gateway supports it |
| Gateway down for hours | Subscriber stays alive, retries with backoff, reports unhealthy via systemd notify |
| Schema drift on event payload | Defensive parsing: log + skip, never crash. Memory: `feedback_validate_before_approve` style |
| MC DB down | Subscriber buffers in memory up to N events, then drops with WARN; backpressure via short circuit |
| Subscriber bug crashes process | systemd `Restart=on-failure`, RestartSec=5s, RestartPreventExitStatus=78 (config error) |

## Effort estimate

- Decisions 1–4: 30 min discussion
- Subscriber skeleton (connect, auth, ping, reconnect): 1-2 days
- Event dispatcher + first projector (`node.event` → `Task.runtime_status`): 1-2 days
- Tests (TDD per `feedback_tdd_discipline`): 1 day
- Operator runbook + systemd unit: 0.5 day
- Soak window observation: 2-3 days passive

**Total: ~1 week of focused work + soak.**

## Open questions for the operator

**The blocking question:** Decision 1 (process model). I recommend
**B (separate systemd worker)**. If you agree, I'll scaffold the
worker and write the failing tests for connection lifecycle. If you
prefer A or C, the rest of the design changes meaningfully and I'd
revise this doc before scaffolding.

Decisions 2-4 can be deferred to the implementation phase, but if
you have strong preferences now (especially on Decision 3 — what
events to subscribe to first) it shapes test scaffolding.
