---
name: feature-researcher
description: Research competitor features and generate structured implementation tasks
---

# Feature Researcher

Automated feature research agent that searches for competitor features, product updates, and industry trends. Generates structured research notes and actionable implementation tasks for the Mission Control board.

## When to use

- When assigned a task titled "Research: [topic]" or "Competitor analysis: [company]"
- When board memory contains a research topic (tag: `research_queue`)
- When planning new features and need market context
- For periodic competitive analysis (scheduled via heartbeat)

## When NOT to use

- For internal code/documentation research (use code search instead)
- When research topic is too vague (ask for clarification first)
- For proprietary/confidential competitor information (ethical boundaries)

## Prerequisites

**Environment Variables:**
- `BRAVE_API_KEY` - Brave Search API key (for web_search tool)
- `OPENAI_API_KEY` (optional) - For AI-powered synthesis, if available

**Tools Required:**
- `curl` - for API calls
- `jq` - for JSON parsing
- Web search capability (Brave API or similar)

**Mission Control Setup:**
- Board memory write access
- Task creation permissions

## Workflow

### 1. Extract Research Topic

```bash
# From task description
TASK=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.task')

TOPIC=$(echo "$TASK" | jq -r '.description' | grep -oP 'Research:\s*\K.*' | head -1)

# Or from board memory
if [ -z "$TOPIC" ]; then
  TOPIC=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=research_queue" \
    -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.memories[0].content.topic')
fi

echo "Research topic: $TOPIC"
```

### 2. Collect Raw Data (Web Search)

```bash
# Search for features, changelogs, and product news
search_web() {
  local query="$1"

  curl -s "https://api.search.brave.com/res/v1/web/search?q=$(echo "$query" | jq -sRr @uri)" \
    -H "Accept: application/json" \
    -H "X-Subscription-Token: $BRAVE_API_KEY" | jq -r '.web.results'
}

# Multiple search queries for comprehensive coverage
FEATURES=$(search_web "$TOPIC features")
CHANGELOG=$(search_web "$TOPIC changelog updates")
REVIEWS=$(search_web "$TOPIC product review")
DOCS=$(search_web "$TOPIC documentation")

# Combine results
RAW_DATA=$(jq -n \
  --argjson features "$FEATURES" \
  --argjson changelog "$CHANGELOG" \
  --argjson reviews "$REVIEWS" \
  --argjson docs "$DOCS" \
  '{features: $features, changelog: $changelog, reviews: $reviews, docs: $docs}')
```

### 3. Synthesize Insights

```bash
# Extract key features from search results
FEATURE_LIST=$(echo "$RAW_DATA" | jq -r '
  .features[] |
  select(.title and .description) |
  "- \(.title): \(.description)"
' | head -20)

# Extract recent updates
UPDATES=$(echo "$RAW_DATA" | jq -r '
  .changelog[] |
  select(.title and .description) |
  "- \(.title) (\(.url))"
' | head -10)

# Generate structured research note
RESEARCH_NOTE=$(cat <<EOF
# Feature Research: $TOPIC

**Date:** $(date +%Y-%m-%d)
**Status:** Complete

## Key Features Found

$FEATURE_LIST

## Recent Updates

$UPDATES

## Sources

$(echo "$RAW_DATA" | jq -r '.features[0:5][] | "- \(.title): \(.url)"')

## Synthesis

Based on the research, here are the standout capabilities:

1. **Feature Category 1** - Multiple competitors offer [pattern]
2. **Feature Category 2** - Emerging trend around [capability]
3. **Feature Category 3** - Standard table stakes include [baseline]

## Gaps & Opportunities

- Opportunity 1: Competitors lack [differentiation]
- Opportunity 2: Market moving toward [trend]
- Gap 1: We are missing [feature]
EOF
)
```

### 4. Check for Duplicate Tasks (Deduplication)

```bash
# Search existing tasks to avoid creating duplicates
check_duplicate() {
  local feature_name="$1"

  EXISTING=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
    -H "Authorization: Bearer $AUTH_TOKEN" | jq -r --arg fname "$feature_name" '
      .tasks[] |
      select(.title | contains($fname)) |
      .id
    ')

  if [ -n "$EXISTING" ]; then
    echo "duplicate:$EXISTING"
  else
    echo "new"
  fi
}
```

### 5. Map to Implementation Tasks

```bash
# Define implementation tasks based on findings
# Each feature becomes a task (if not duplicate)

IMPLEMENTATION_TASKS='[
  {
    "title": "Implement feature: Real-time collaboration",
    "description": "Based on competitor research, add real-time editing similar to [Competitor].\n\nReferences:\n- [URL]\n- [URL]",
    "tags": ["research-derived", "feature-request"]
  },
  {
    "title": "Improve feature: Mobile responsiveness",
    "description": "Competitors have superior mobile UX. Focus on:\n- Touch gestures\n- Responsive layout\n- Offline support",
    "tags": ["research-derived", "enhancement"]
  }
]'

# Create tasks (with deduplication check)
echo "$IMPLEMENTATION_TASKS" | jq -c '.[]' | while read -r task; do
  TITLE=$(echo "$task" | jq -r '.title')
  DESC=$(echo "$task" | jq -r '.description')
  TAGS=$(echo "$task" | jq -r '.tags')

  # Check for duplicate
  DUP_CHECK=$(check_duplicate "$TITLE")

  if [[ "$DUP_CHECK" == "new" ]]; then
    echo "Creating task: $TITLE"

    curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
      -H "Authorization: Bearer $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(jq -n \
        --arg title "$TITLE" \
        --arg desc "$DESC" \
        --argjson tags "$TAGS" \
        '{title: $title, description: $desc, status: "inbox", tags: $tags}')"
  else
    EXISTING_ID=$(echo "$DUP_CHECK" | cut -d: -f2)
    echo "Skipping duplicate task (exists as #$EXISTING_ID): $TITLE"
  fi
done
```

### 6. Post Research to Board Memory

```bash
# Store research note with tag 'research'
curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg note "$RESEARCH_NOTE" \
    --arg topic "$TOPIC" \
    '{
      content: {
        topic: $topic,
        research_note: $note,
        timestamp: now | tostring
      },
      tags: ["research"]
    }')"

echo "Research saved to board memory"
```

### 7. Create Summary Task

```bash
# Create a summary task with findings
SUMMARY_TASK_DESC=$(cat <<EOF
Research on "$TOPIC" is complete. Key findings:

$FEATURE_LIST

---

**Implementation tasks created:**
- See tasks tagged with 'research-derived'

**Full research note:**
- Stored in board memory (tag: research)

**Next steps:**
1. Review generated tasks
2. Prioritize features
3. Begin implementation
EOF
)

curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg title "Research summary: $TOPIC" \
    --arg desc "$SUMMARY_TASK_DESC" \
    '{
      title: $title,
      description: $desc,
      status: "review",
      tags: ["research-summary"]
    }')"
```

### 8. Update Original Task

```bash
# Mark research task as done
curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'

# Add comment with summary
curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg text "Research complete. Created summary task and implementation tasks. See board memory for full report." \
    '{text: $text}')"
```

## Research Workflow Summary

1. **Collect raw data** - Multiple web searches for comprehensive coverage
2. **Synthesize insights** - Extract patterns, trends, and key features
3. **Map to implementation tasks** - Convert findings into actionable work items
4. **Post to board** - Store research notes and create tasks with deduplication

## API Reference (Mission Control)

### List Tasks
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Create Task
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Task title",
    "description": "Description",
    "status": "inbox",
    "tags": ["research-derived"]
  }'
```

### Write Board Memory
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": {"research_note": "..."},
    "tags": ["research"]
  }'
```

### Add Task Comment
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Comment text"}'
```

## Brave Search API Reference

### Web Search
```bash
curl "https://api.search.brave.com/res/v1/web/search?q=your+query" \
  -H "Accept: application/json" \
  -H "X-Subscription-Token: $BRAVE_API_KEY"
```

Response structure:
```json
{
  "web": {
    "results": [
      {
        "title": "Page title",
        "url": "https://...",
        "description": "Snippet..."
      }
    ]
  }
}
```

## Watchdog / Continuity

This skill is **task-driven** rather than watchdog-based:

- Triggered by explicit research tasks (title starts with "Research:")
- Can also poll board memory tag `research_queue` on heartbeat
- Research state persisted in board memory, can resume if interrupted
- Deduplication ensures same research doesn't create duplicate implementation tasks

**Continuity Pattern:**
- Store partial research in board memory with tag `research_in_progress`
- If skill restarts mid-research, check for in-progress research and resume
- Mark research as complete by moving tag from `research_in_progress` to `research`
