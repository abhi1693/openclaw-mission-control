# Backend Templates (Product Documentation)

This folder contains the Markdown templates Mission Control syncs into OpenClaw agent workspaces.

- Location in repo: `backend/templates/`
- Runtime location in backend container: `/app/templates`
- Render engine: Jinja2

## What this is for

Use these templates to control what an agent sees in workspace files like:

- `AGENTS.md`
- `HEARTBEAT.md`
- `TOOLS.md`
- `IDENTITY.md`
- `USER.md`
- `MEMORY.md`
- `LEAD_PLAYBOOK.md` (supplemental lead examples/reference)

When a gateway template sync runs, these templates are rendered with agent/board context and written into each workspace.

## How rendering works

### Rendering configuration

Defined in `backend/app/services/openclaw/provisioning.py` (`_template_env()`):

- `StrictUndefined` enabled (missing variables fail fast)
- `autoescape=False` (Markdown output)
- `keep_trailing_newline=True`

### Context builders

- Board agent context: `_build_context()`
- Main agent context: `_build_main_context()`
- User mapping: `_user_context()`
- Identity mapping: `_identity_context()`

## Sync entry points

### API

`POST /api/v1/gateways/{gateway_id}/templates/sync`

- Router: `backend/app/api/gateways.py` (`sync_gateway_templates`)
- Service: `backend/app/services/openclaw/provisioning_db.py`

### Script

`backend/scripts/sync_gateway_templates.py`

Example:

```bash
python backend/scripts/sync_gateway_templates.py --gateway-id <uuid>
```

## Files included in sync

Default synced files are defined in:

- `backend/app/services/openclaw/constants.py` (`DEFAULT_GATEWAY_FILES`)

Main-agent template mapping is defined in:

- `backend/app/services/openclaw/constants.py` (`MAIN_TEMPLATE_MAP`)

## HEARTBEAT.md selection logic

`HEARTBEAT.md` is selected dynamically:

- Board lead -> `HEARTBEAT_LEAD.md`
- Non-lead agent -> `HEARTBEAT_AGENT.md`

See:

- `HEARTBEAT_LEAD_TEMPLATE`, `HEARTBEAT_AGENT_TEMPLATE` in constants
- `_heartbeat_template_name()` in provisioning

## Template variables reference

### Core keys (all templates)

- `agent_name`, `agent_id`, `session_key`
- `base_url`, `auth_token`, `main_session_key`
- `workspace_root`

### User keys

- `user_name`, `user_preferred_name`, `user_pronouns`, `user_timezone`
- `user_notes`, `user_context`

### Identity keys

- `identity_role`, `identity_communication_style`, `identity_emoji`
- `identity_autonomy_level`, `identity_verbosity`, `identity_output_format`, `identity_update_cadence`
- `identity_purpose`, `identity_personality`, `identity_custom_instructions`

### Board-agent-only keys

- `board_id`, `board_name`, `board_type`
- `board_objective`, `board_success_metrics`, `board_target_date`
- `board_goal_confirmed`, `is_board_lead`
- `workspace_path`

## OpenAPI role tags for agents

Agent-facing endpoints expose role tags in OpenAPI so heartbeat files can filter
operations without path regex hacks:

- `agent-lead`: board lead workflows (delegation/review/coordination)
- `agent-worker`: non-lead board execution workflows
- `agent-main`: gateway main / cross-board control-plane workflows

Example filter:

```bash
curl -s "$BASE_URL/openapi.json" \
  | jq -r '.paths | to_entries[] | .key as $path
    | .value | to_entries[]
    | select((.value.tags // []) | index("agent-lead"))
    | "\(.key|ascii_upcase)\t\($path)\t\(.value.operationId // "-")"'
```

## Safe change checklist

Before merging template changes:

1. Do not introduce new `{{ var }}` placeholders unless context builders provide them.
2. Keep changes additive where possible.
3. Review both board-agent and `MAIN_*` templates when changing shared behavior.
4. Preserve agent-editable files behavior (`PRESERVE_AGENT_EDITABLE_FILES`).
5. Run docs quality checks and CI.
6. Keep heartbeat templates under injected-context size limits (20,000 chars each).

## Local validation

### Fast check

Run CI-relevant docs checks locally:

```bash
make docs-check
```

### Full validation

- Push branch
- Confirm PR checks are green
- Optionally run template sync on a dev gateway and inspect generated workspace files

## FAQ

### Why did rendering fail after adding a variable?

Because `StrictUndefined` is enabled. Add that key to `_build_context()` / `_build_main_context()` (and related mappers) before using it in templates.

### Why didn’t my edit appear in an agent workspace?

Template sync may not have run yet, or the target file is preserved as agent-editable. Check sync status and preservation rules in constants.
