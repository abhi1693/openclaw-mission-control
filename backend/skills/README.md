# Mission Control Skills

This directory mirrors `/root/.openclaw/skills/` on the gateway host (`.60`).
Skills are auto-discovered by openclaw via `skills.load.watch=true` (filesystem
watch, ~250ms debounce). No registry, no allow-list, no Sync API call.

## Source of truth

This directory is authoritative. Skills landed here propagate to the gateway
via `./deploy-skills.sh`. Any skill that exists on `.60` but not here is
considered drift; pass `--prune` to rsync to remove it.

## Layout

Each skill is a folder containing a `SKILL.md` with the standard openclaw
frontmatter:

```yaml
---
name: <skill-name>
description: <one-line trigger description>
---
```

The `name` field must match the folder name. The `description` field is what
agents read to decide whether to invoke the skill.

## Skill index

### Cross-role mechanics

- **acp-delegation** — Use when a board agent must delegate coding, review, or validation work through OpenClaw ACP `sessions_spawn` instead of doing it locally.
- **acp-post-review** — Use when an OpenClaw board agent has received an ACP child completion event and must verify the child result before posting evidence or routing the task.
- **mc-board-api** — Use when posting comments, recording pipeline events, or filing reviewer verdicts to MC instead of hand-rolling curl with the auth token (typed CLI at `/usr/local/bin/mc_client.py`).
- **structured-review-verdict** — Use when a board reviewer has posted a review verdict comment and the verdict must become visible to Mission Control review-readiness gates.
- **rework-resubmit** — Use when an OpenClaw board implementation task has been returned to rework after QA, Architect, Lead, or Supervisor rejection.
- **reviewer-recheck** — Use when a QA, Architect, or review-only verdict has been challenged, rejected, or returned for correction on the same task.
- **worker-parallel-scheduler** — Use when a worker agent (frontend or backend) operates in worktree-parallel mode and must select the next task across an active-child cap, create deterministic worktrees, and serialize merge-back into the main workspace.

### Lead playbook (board lead heartbeat)

- **lead-next-action-gate** — Use when a board lead heartbeat must check Mission Control's structured next lead action before memory intake, health scans, or manual task routing.
- **lead-memory-intake** — Use when a board lead must run the Memory Intake Gate after lead-next-action clears and before health scan, to verify recent operator-memory intake tasks.
- **lead-health-scan** — Use when a board lead has cleared next-action and memory-intake gates and must choose one closest-to-done board friction to route.
- **lead-inbox-routing** — Use when a board lead must route inbox work, decide whether decomposition is required, create planned subtasks, or assign new work to the right role.
- **lead-review-routing** — Use when a board lead must decide what to do with a task in `review` status — whether to mark done, request approval, route to the next reviewer, or push to rework based on reviewer verdicts and approval freshness.

### Reviewer-specific verdict packets

- **architect-review-verdict** — Use when an Architect or review-only board agent must review submitted work, decomposition, architecture, API, auth, or state-machine changes.
- **qa-validation-verdict** — Use when a QA board agent must validate a task in review status and post a PASS, FAIL, INCONCLUSIVE, or INFRA BLOCKED verdict.
- **qa-browser-oracle-alternation** — Use to pick between Playwright and Codex Computer Use as the browser-validation oracle; companions qa-validation-verdict for cross-validating UI behavior across two independent browser sensors.
- **devops-deploy-validation** — Use when a DevOps board agent must validate deployed state, classify infra/deploy drift, or diagnose a DevOps-owned review or rework failure.

## Deploy

```bash
./deploy-skills.sh           # rsync local → .60 (no deletes)
./deploy-skills.sh --dry     # preview changes
./deploy-skills.sh --prune   # also delete prod-only skills not in local
```

Override host via env vars:

```bash
SKILLS_GATEWAY_HOST=<host> SKILLS_GATEWAY_USER=<user> ./deploy-skills.sh
```

## Discovery on the gateway

The gateway loads skills from the path configured in `openclaw.json`:

```json
{
  "skills": {
    "load": {
      "watch": true,
      "watchDebounceMs": 250
    }
  }
}
```

No allow-list. Filesystem changes propagate to running agents within the
debounce window.

## Conventions

- One skill = one folder + one `SKILL.md`. Optional `references/` and
  `scripts/` subfolders sync; everything else is excluded by the rsync filter.
- Don't put deploy scripts, READMEs, or `.bak` files inside skill folders;
  the rsync filter excludes top-level `deploy-skills.sh` / `README.md` but
  not nested ones.
- Skills are role-conventional, not role-enforced. The frontmatter description
  scopes the audience; templates and SOUL.md cite skills by name to direct
  the right roles. Cross-host or cross-role policy lives in the skill prose.
