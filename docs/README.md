# Mission Control docs

This folder is the canonical documentation set for Mission Control.

## Start here (by role)

- **Contributor**: start with [Quickstart](../README.md#quick-start-self-host-with-docker-compose) → [Development](development.md) → [Contributing](contributing.md)
- **Maintainer**: start with [Architecture](05-architecture.md) → [Repo tour](04-repo-tour.md) → [API reference](07-api-reference.md)
- **Operator/SRE**: start with [Ops / runbooks](09-ops-runbooks.md) → [Troubleshooting](10-troubleshooting.md)

## Table of contents (IA)

- [Style guide](00-style-guide.md)


1. [Overview](01-overview.md)
2. [Quickstart](02-quickstart.md)
3. [Development](03-development.md)
4. [Repo tour](04-repo-tour.md)
5. [Architecture](05-architecture.md)
6. [Configuration](06-configuration.md)
7. [API reference](07-api-reference.md)
   - [Frontend API + auth modules](frontend-api-auth.md)
8. [Agents & skills](08-agents-and-skills.md)
9. [Ops / runbooks](09-ops-runbooks.md)
10. [Troubleshooting](10-troubleshooting.md)
11. [Contributing](11-contributing.md)

## IA guardrails (to prevent churn)

- **Single canonical nav**: this `docs/README.md`.
- **Stable spine**: keep `01-...` through `11-...` stable; avoid renumbering.
- **One primary owner page per subsystem**: link each subsystem from exactly one place in the TOC.
  - If a subsystem needs two pages (overview + reference), pick one **entrypoint** as the owner and cross-link the other as a deep dive.

## Linking rules (mini-spec)

- Link to `docs/README.md` when you want someone to **browse the map**.
  - Example: `[Docs](docs/README.md)`
- Link to a leaf page when you want someone to **do a specific thing**.
  - Example: `[Development workflow](03-development.md)`
- For deep dives, prefer linking the folder `README.md` as the stable entrypoint.
  - Example: `[Production notes](production/README.md)`
- Use relative links + anchors for precision:
  - Example: `[Auth model](07-api-reference.md#auth)`
- If files move: update the single TOC owner link here, and update cross-links in the involved pages.

## Copy/paste templates

### Module doc template

```md
# <Module name>

1–3 sentences: what this module is and who should read this.

## Start here
- If you’re trying to <common task>, start at <file/entrypoint>.

## Source of truth
- Code: `<dir-or-file-glob>`
- Primary owner page: `<link to the spine page that owns navigation>`

## Source map (code pointers)
- Entrypoint: `<file>`
- Primary router/controller: `<file>` (if applicable)
- Key service(s): `<file(s)>`
- Data model: `<models/schemas>`
- Config: `<config files / env var definitions>`
- Tests: `<test files / suites>`

## Responsibilities
- Owns:
  - …
- Does not own (boundaries):
  - …

## How it works
- <key flows + pointers>

## Configuration
- <env vars + footguns>

## Common workflows
- <copy/paste commands>

## Debug checklist
- Symptom → checks → causes → fixes

## Related docs
- <links>
```

### Runbook template

```md
# Runbook: <Incident / operation>

1–2 sentences: when to use this runbook.

## Triage (first 5 minutes)
- Confirm impact:
  - …
- Check health:
  - …
- Check recent changes:
  - …

## Mitigation
- Option A (safe): …
- Option B (invasive): …

## Diagnosis
- Logs to check:
  - …
- Common causes:
  - …

## Recovery / verification
- How to confirm resolved:
  - …

## Post-incident
- Follow-ups / prevention:
  - …

## References
- <links>
```

## Existing deep-dive docs

These deeper references already exist under `docs/` directories:
- [Architecture deep dive](architecture/README.md)
- [Deployment guide](deployment/README.md)
- [Production notes](production/README.md)
- [Testing guide](testing/README.md)
- [Troubleshooting](troubleshooting/README.md)
- [Gateway WebSocket protocol](openclaw_gateway_ws.md)
- [Gateway base config](openclaw_gateway_base_config.md)
