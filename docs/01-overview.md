# Mission Control

Mission Control is the **web UI + HTTP API** for operating OpenClaw.

It’s the place you go to coordinate work across people and agents, keep an evidence trail, and operate the system safely.

## What problem it solves

OpenClaw can run tools/skills and hold conversations across channels. What’s missing in practice is a control plane that makes this operational:

- **Coordination**: boards + tasks make it explicit what’s being worked on, by whom, and what’s blocked.
- **Evidence**: task comments capture commands run, links, outputs, and decisions.
- **Risk control**: approvals provide a structured “allow/deny” gate for sensitive actions.
- **Operations**: deployment, configuration, and troubleshooting live in one navigable docs spine.

## Core concepts

- **Board**: a workspace containing tasks, memory, and agents.
- **Task**: a unit of work with a status and evidence (comments).
- **Agent**: an automated worker that executes tasks and posts evidence.
- **Approval**: a review gate for risky steps.
- **Gateway** (optional integration): an OpenClaw runtime host Mission Control can coordinate with.
- **Heartbeat**: periodic agent loop for incremental work.
- **Cron**: scheduled execution (recurring or one-shot).

## What it is not

- A general-purpose project management tool.
- An observability suite (use your existing logs/metrics/tracing; Mission Control links and operationalizes them).
- A secrets manager (keep secrets in your secret store; don’t paste them into tasks/docs).

## How to navigate these docs

This repo keeps a small “reader journey” spine under `docs/`:

1. [Quickstart](02-quickstart.md) — run it locally/self-host.
2. [Development](03-development.md) — contributor workflow and CI parity.
3. [Configuration](06-configuration.md) — env vars, precedence, migrations, CORS.
4. [API reference](07-api-reference.md) — route groups + auth model.
5. [Ops / runbooks](09-ops-runbooks.md) — operational checklists.
6. [Troubleshooting](10-troubleshooting.md) — symptom → checks → fixes.

For deeper references, see `docs/architecture/`, `docs/deployment/`, `docs/production/`, `docs/testing/`, and `docs/troubleshooting/`.
