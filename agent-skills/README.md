# Agent Skills

This directory contains specialized skills for Mission Control AI agents. Each skill is a self-contained capability that agents can use to automate workflows, integrate with external services, and perform complex operations.

## Available Skills

| Skill | Description | Trigger | Prerequisites |
|-------|-------------|---------|---------------|
| [clickup-sync](./clickup-sync/SKILL.md) | Bidirectional sync between ClickUp tasks and Mission Control boards | Watchdog (every 15 min) | `CLICKUP_TOKEN`, `CLICKUP_TEAM_ID` |
| [feature-researcher](./feature-researcher/SKILL.md) | Research competitor features and generate structured implementation tasks | Task: "Research: [topic]" | `BRAVE_API_KEY` |
| [code-reviewer](./code-reviewer/SKILL.md) | Automated code review for PRs with security, quality, and performance analysis | Task with `needs-code-review` tag | `gh` CLI (authenticated) |
| [qa-generator](./qa-generator/SKILL.md) | Automatically generate test plans and test cases for features moving to review | Task moves to `status=review` | `curl`, `jq`, optional: `claude` CLI |
| [release-notes](./release-notes/SKILL.md) | Generate release notes from completed tasks and optionally publish to GitHub | Task: "Generate Release Notes" or threshold trigger | Optional: `GITHUB_REPO`, `gh` CLI |

## How Skills Work

### Skill Structure

Each skill directory contains a `SKILL.md` file with the following sections:

1. **Frontmatter** - Metadata (name, description)
2. **When to use** - Triggering conditions
3. **When NOT to use** - Exclusions
4. **Prerequisites** - Required environment variables and tools
5. **Workflow** - Step-by-step implementation with bash scripts
6. **API Reference** - Mission Control and external API examples
7. **Watchdog / Continuity** - How the skill maintains state across restarts

### Skill Execution

Agents read skill files and execute them when:
- A task matches the skill description
- A watchdog timer triggers (periodic execution)
- Explicitly invoked by a Lead agent

### State Management

Skills use **Mission Control board memory** to persist state:
- **Fingerprints** - Deduplicate external records (e.g., ClickUp task IDs)
- **Timestamps** - Track last execution for watchdog patterns
- **Configuration** - Store skill-specific settings
- **Errors** - Log failures for debugging

## Skill Categories

### 🔄 Integration Skills
- **clickup-sync** - Keep external task trackers in sync

### 🔍 Research & Analysis Skills
- **feature-researcher** - Competitive intelligence and feature discovery
- **code-reviewer** - Automated code quality and security analysis

### 🧪 Quality Assurance Skills
- **qa-generator** - Test plan and test case generation

### 📦 Release Management Skills
- **release-notes** - Automated release documentation

## Adding New Skills

To create a new skill:

1. Create a directory under `agent-skills/`
2. Add a `SKILL.md` file with the standard structure
3. Include practical bash scripts using Mission Control API
4. Document prerequisites and error handling
5. Add watchdog/continuity pattern if needed
6. Update this README with the new skill

### Skill Template

```markdown
---
name: skill-name
description: One-line description
---

# Skill Name

Brief description.

## When to use
- Condition 1
- Condition 2

## When NOT to use
- Exclusion 1

## Prerequisites
- ENV_VAR_1
- tool1, tool2

## Workflow

Step-by-step with bash examples...

## API Reference (Mission Control)

curl examples...

## Watchdog / Continuity

How state is maintained...
```

## Mission Control API Quick Reference

### Authentication
All API calls require the agent's `AUTH_TOKEN`:
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Common Endpoints

#### Tasks
```bash
# List tasks
GET /api/v1/agent/boards/{board_id}/tasks?status=inbox

# Create task
POST /api/v1/agent/boards/{board_id}/tasks
Body: {"title": "...", "description": "...", "status": "inbox", "tags": [...]}

# Update task
PATCH /api/v1/agent/boards/{board_id}/tasks/{task_id}
Body: {"status": "done"}

# Add comment
POST /api/v1/agent/boards/{board_id}/tasks/{task_id}/comments
Body: {"text": "..."}
```

#### Board Memory
```bash
# Read memory
GET /api/v1/agent/boards/{board_id}/memory?tag=my_tag

# Write memory
POST /api/v1/agent/boards/{board_id}/memory
Body: {"content": {...}, "tags": ["my_tag"]}
```

## Best Practices

### 1. Error Handling
- Always check command exit codes
- Log errors to board memory
- Gracefully degrade when external services are unavailable

### 2. Deduplication
- Use board memory to track processed items
- Check for existing tasks before creating new ones
- Use fingerprinting for external records

### 3. Idempotency
- Skills should be safe to run multiple times
- Use tags to track completion status
- Store timestamps for watchdog patterns

### 4. Security
- Never hardcode credentials
- Use environment variables for secrets
- Validate external input before processing

### 5. Performance
- Use jq for efficient JSON parsing
- Batch API calls when possible
- Implement rate limiting for external APIs

## Troubleshooting

### Skill Not Triggering
- Check task status and tags match skill conditions
- Verify watchdog timestamp in board memory
- Ensure prerequisites are met (env vars, tools)

### API Errors
- Verify `AUTH_TOKEN` and `BASE_URL` are set
- Check network connectivity
- Review error logs in board memory

### External Service Failures
- Check service-specific credentials
- Verify tool installation (gh, jq, curl)
- Test API endpoints manually

## Contributing

When contributing new skills:
1. Follow the standard skill structure
2. Include comprehensive error handling
3. Add practical bash examples
4. Document all prerequisites
5. Test watchdog/continuity patterns
6. Update this README

## License

These skills are part of the Mission Control project and inherit the project's license.

## Support

For issues or questions:
- Create an issue in the Mission Control repository
- Tag with `agent-skills` label
- Include skill name and error logs
