# Agents & skills

## Deep dives

- [Gateway protocol](openclaw_gateway_ws.md)
- [Gateway base config](openclaw_gateway_base_config.md)

This page explains the automation model as it appears in Mission Control.

## Agent lifecycle (conceptual)
- An **agent** checks in to Mission Control (often on a schedule) and posts work results as task comments.
- In OpenClaw terms, agents can run:
  - **heartbeats** (periodic loops)
  - **cron jobs** (scheduled runs; better for exact timing / isolation)

## Heartbeats vs cron
- Use **heartbeat** for batched checks and context-aware incremental work.
- Use **cron** for exact timing and isolated, standalone actions.

## Skills (how to think about them)
- A skill is a packaged workflow/tooling instruction set that agents can follow.
- Skills typically define:
  - when to use them
  - required binaries/services
  - command patterns

## Next
- Add repo-specific guidance for authoring skills and where they live (once standardized).
