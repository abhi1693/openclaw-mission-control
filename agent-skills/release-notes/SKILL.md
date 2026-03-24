---
name: release-notes
description: Generate release notes from completed tasks and optionally publish to GitHub
---

# Release Notes Generator

Automated release notes generator that scans completed tasks, groups them by category, and produces formatted release notes. Can optionally publish to GitHub Releases.

## When to use

- When explicitly requested via task: "Generate Release Notes for [version]"
- On heartbeat: when N done tasks exist since last release (configurable threshold)
- Before creating a new release/deployment
- When manually triggered by Lead agent

## When NOT to use

- For mid-sprint progress updates (use board summary instead)
- For internal-only changes (unless configured to include)
- When there are no completed tasks since last release

## Prerequisites

**Environment Variables:**
- `GITHUB_REPO` (optional) - Repository in format `owner/repo` for publishing to GitHub
- `GITHUB_TOKEN` (optional) - GitHub token for `gh` CLI if not already authenticated
- `RELEASE_THRESHOLD` (optional) - Minimum number of done tasks to trigger auto-generation (default: 10)

**Tools Required:**
- `curl` - for API calls
- `jq` - for JSON parsing
- `date` - for timestamp formatting
- `gh` - GitHub CLI (optional, for publishing releases)

**Mission Control Setup:**
- Board memory read/write access
- Task read access

## Workflow

### 1. Detect Release Trigger

```bash
# Check if explicitly triggered by task
RELEASE_TASKS=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '
    .tasks[] |
    select(.title | test("^Generate Release Notes"; "i")) |
    @json
  ')

if [ -n "$RELEASE_TASKS" ]; then
  TASK_ID=$(echo "$RELEASE_TASKS" | jq -r '.id')
  VERSION=$(echo "$RELEASE_TASKS" | jq -r '.title' | grep -oP 'for\s+\K[v\d.]+')
  echo "Explicit release notes request for version: $VERSION"
else
  # Check heartbeat threshold
  LAST_RELEASE_DATE=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=release_metadata" \
    -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.memories[0].content.last_release_date // "1970-01-01"')

  # Count done tasks since last release
  DONE_COUNT=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=done" \
    -H "Authorization: Bearer $AUTH_TOKEN" | jq -r --arg since "$LAST_RELEASE_DATE" '
      .tasks[] |
      select(.completed_at > $since) |
      .id
    ' | wc -l)

  THRESHOLD=${RELEASE_THRESHOLD:-10}

  if [ $DONE_COUNT -ge $THRESHOLD ]; then
    echo "Auto-generating release notes ($DONE_COUNT tasks completed since $LAST_RELEASE_DATE)"
    VERSION="v$(date +%Y.%m.%d)"
  else
    echo "Not enough tasks for release ($DONE_COUNT < $THRESHOLD)"
    exit 0
  fi
fi
```

### 2. Fetch Completed Tasks Since Last Release

```bash
# Get last release date from board memory
LAST_RELEASE_DATE=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=release_metadata" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.memories[0].content.last_release_date // "1970-01-01"')

echo "Fetching tasks completed since: $LAST_RELEASE_DATE"

# Get all done tasks since last release
DONE_TASKS=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=done" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r --arg since "$LAST_RELEASE_DATE" '
    .tasks[] |
    select(.completed_at > $since)
  ')

TASK_COUNT=$(echo "$DONE_TASKS" | jq -s 'length')
echo "Found $TASK_COUNT completed tasks"
```

### 3. Categorize Tasks

```bash
# Categorize tasks by type (inferred from title/tags)
categorize_task() {
  local title="$1"
  local tags="$2"
  local description="$3"

  # Check for breaking changes
  if echo "$title $description" | grep -qiE '\bbreaking\b|\bBREAKING CHANGE\b'; then
    echo "breaking"
    return
  fi

  # Check tags first
  if echo "$tags" | jq -e '.[] | select(. == "bug" or . == "bugfix")' &> /dev/null; then
    echo "bugfix"
    return
  fi

  if echo "$tags" | jq -e '.[] | select(. == "feature" or . == "enhancement")' &> /dev/null; then
    echo "feature"
    return
  fi

  # Check title patterns
  if echo "$title" | grep -qiE '^(fix|fixed|bugfix)'; then
    echo "bugfix"
  elif echo "$title" | grep -qiE '^(feat|feature|add|added|new)'; then
    echo "feature"
  elif echo "$title" | grep -qiE '^(improve|improved|enhance|update|updated)'; then
    echo "improvement"
  elif echo "$title" | grep -qiE '^(refactor|refactored|cleanup)'; then
    echo "refactor"
  elif echo "$title" | grep -qiE '^(docs?|documentation)'; then
    echo "documentation"
  else
    echo "other"
  fi
}

# Group tasks by category
declare -A CATEGORIES

echo "$DONE_TASKS" | jq -c '.' | while read -r task; do
  TITLE=$(echo "$task" | jq -r '.title')
  TAGS=$(echo "$task" | jq -r '.tags // []')
  DESC=$(echo "$task" | jq -r '.description // ""')
  TASK_ID=$(echo "$task" | jq -r '.id')

  CATEGORY=$(categorize_task "$TITLE" "$TAGS" "$DESC")

  # Store in temporary files (bash arrays don't work well in subshells)
  echo "- $TITLE (#$TASK_ID)" >> "/tmp/release_${CATEGORY}.txt"
done

# Read categorized tasks
FEATURES=$([ -f /tmp/release_feature.txt ] && cat /tmp/release_feature.txt || echo "")
BUGFIXES=$([ -f /tmp/release_bugfix.txt ] && cat /tmp/release_bugfix.txt || echo "")
IMPROVEMENTS=$([ -f /tmp/release_improvement.txt ] && cat /tmp/release_improvement.txt || echo "")
BREAKING=$([ -f /tmp/release_breaking.txt ] && cat /tmp/release_breaking.txt || echo "")
REFACTORS=$([ -f /tmp/release_refactor.txt ] && cat /tmp/release_refactor.txt || echo "")
DOCS=$([ -f /tmp/release_documentation.txt ] && cat /tmp/release_documentation.txt || echo "")
OTHER=$([ -f /tmp/release_other.txt ] && cat /tmp/release_other.txt || echo "")

# Cleanup temp files
rm -f /tmp/release_*.txt
```

### 4. Generate Release Notes

```bash
# Generate formatted release notes in markdown
RELEASE_NOTES=$(cat <<EOF
# Release Notes - $VERSION

**Release Date:** $(date +%Y-%m-%d)
**Tasks Completed:** $TASK_COUNT

## 🚨 Breaking Changes

${BREAKING:-No breaking changes in this release.}

## ✨ New Features

${FEATURES:-No new features in this release.}

## 🐛 Bug Fixes

${BUGFIXES:-No bug fixes in this release.}

## 🔧 Improvements

${IMPROVEMENTS:-No improvements in this release.}

## 📚 Documentation

${DOCS:-No documentation updates in this release.}

## 🔨 Refactoring

${REFACTORS:-No refactoring in this release.}

## 📦 Other Changes

${OTHER}

---

**Full Changelog:** [View all tasks](${BASE_URL}/boards/${BOARD_ID})

**Contributors:** Mission Control Team
**Previous Release:** $LAST_RELEASE_DATE

EOF
)

echo "$RELEASE_NOTES"
```

### 5. Save Release Notes to Board Memory

```bash
# Store release notes in board memory
CURRENT_DATE=$(date +%Y-%m-%d)

curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg notes "$RELEASE_NOTES" \
    --arg version "$VERSION" \
    --arg date "$CURRENT_DATE" \
    '{
      content: {
        version: $version,
        release_notes: $notes,
        generated_at: $date,
        task_count: '$TASK_COUNT'
      },
      tags: ["release_notes"]
    }')"

echo "✅ Release notes saved to board memory"
```

### 6. Create Review Task

```bash
# Create task for reviewing and publishing release notes
REVIEW_TASK_DESC=$(cat <<EOF
Review the generated release notes for **$VERSION** before publishing.

## Release Notes Preview

$RELEASE_NOTES

## Next Steps

1. **Review** the categorization and content above
2. **Edit** if necessary (update board memory entry)
3. **Publish** to GitHub Releases (if GITHUB_REPO is configured)
4. **Announce** the release to the team

## Publish Commands

If approved, publish to GitHub:

\`\`\`bash
# Publish release to GitHub
gh release create $VERSION \\
  --title "Release $VERSION" \\
  --notes "\$(cat <<'NOTES'
$RELEASE_NOTES
NOTES
)"
\`\`\`

Or update this task status to 'done' to mark as published.

---
*Auto-generated by Release Notes Generator*
EOF
)

REVIEW_TASK=$(curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg title "Review and publish release notes for $VERSION" \
    --arg desc "$REVIEW_TASK_DESC" \
    '{
      title: $title,
      description: $desc,
      status: "review",
      tags: ["release", "release-notes"]
    }')")

REVIEW_TASK_ID=$(echo "$REVIEW_TASK" | jq -r '.task.id')
echo "✅ Review task created: #$REVIEW_TASK_ID"
```

### 7. Optionally Publish to GitHub

```bash
# If GITHUB_REPO is set and task is marked for auto-publish, create GitHub release
if [ -n "$GITHUB_REPO" ] && [ "$AUTO_PUBLISH" == "true" ]; then
  echo "Publishing release to GitHub: $GITHUB_REPO"

  # Create GitHub release using gh CLI
  gh release create "$VERSION" \
    --repo "$GITHUB_REPO" \
    --title "Release $VERSION" \
    --notes "$RELEASE_NOTES"

  if [ $? -eq 0 ]; then
    echo "✅ Published to GitHub Releases: https://github.com/$GITHUB_REPO/releases/tag/$VERSION"

    # Add comment to review task
    curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$REVIEW_TASK_ID/comments" \
      -H "Authorization: Bearer $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(jq -n \
        --arg text "✅ Published to GitHub Releases: https://github.com/$GITHUB_REPO/releases/tag/$VERSION" \
        '{text: $text}')"
  else
    echo "❌ Failed to publish to GitHub"
  fi
else
  echo "ℹ️  Manual publication required (GITHUB_REPO not set or AUTO_PUBLISH=false)"
fi
```

### 8. Update Release Metadata

```bash
# Update last_release_date in board memory
CURRENT_DATE=$(date +%Y-%m-%d)

curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg date "$CURRENT_DATE" \
    --arg version "$VERSION" \
    '{
      content: {
        last_release_date: $date,
        last_version: $version
      },
      tags: ["release_metadata"]
    }')"

echo "✅ Release metadata updated (last_release_date: $CURRENT_DATE)"
```

### 9. Mark Trigger Task as Done

```bash
# If triggered by explicit task, mark it as done
if [ -n "$TASK_ID" ]; then
  curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"status": "done"}'

  curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(jq -n \
      --arg text "✅ Release notes generated. Review task: #$REVIEW_TASK_ID" \
      '{text: $text}')"
fi
```

## Release Notes Format

Generated release notes follow this structure:

1. **Header** - Version, date, task count
2. **Breaking Changes** (🚨) - Highest priority, listed first
3. **New Features** (✨) - Major additions
4. **Bug Fixes** (🐛) - Issues resolved
5. **Improvements** (🔧) - Enhancements to existing features
6. **Documentation** (📚) - Docs updates
7. **Refactoring** (🔨) - Internal improvements
8. **Other Changes** (📦) - Miscellaneous

## API Reference (Mission Control)

### Get Done Tasks Since Date
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=done" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq --arg since "2024-01-01" '
    .tasks[] |
    select(.completed_at > $since)
  '
```

### Read Release Metadata
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=release_metadata" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Write Release Notes
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": {
      "version": "v1.0.0",
      "release_notes": "...",
      "generated_at": "2024-03-24"
    },
    "tags": ["release_notes"]
  }'
```

### Create Review Task
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Review release notes",
    "description": "...",
    "status": "review",
    "tags": ["release"]
  }'
```

## GitHub CLI Reference

### Create Release
```bash
gh release create v1.0.0 \
  --repo owner/repo \
  --title "Release v1.0.0" \
  --notes "Release notes content"
```

### List Releases
```bash
gh release list --repo owner/repo
```

### Upload Assets
```bash
gh release upload v1.0.0 dist/app.zip --repo owner/repo
```

## Configuration

Control release generation behavior via board memory (tag: `release_config`):

```json
{
  "release_threshold": 10,
  "auto_publish": false,
  "version_scheme": "semver",
  "include_categories": ["feature", "bugfix", "improvement", "breaking"],
  "exclude_tags": ["internal", "wip"]
}
```

## Versioning Strategies

### Semantic Versioning (SemVer)
```bash
# Determine version bump based on changes
if [ -n "$BREAKING" ]; then
  VERSION_TYPE="major"
elif [ -n "$FEATURES" ]; then
  VERSION_TYPE="minor"
else
  VERSION_TYPE="patch"
fi

# Increment version
LAST_VERSION=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory?tag=release_metadata" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.memories[0].content.last_version // "v0.0.0"')

NEW_VERSION=$(semver bump $VERSION_TYPE $LAST_VERSION)
```

### Date-based Versioning
```bash
VERSION="v$(date +%Y.%m.%d)"
```

### Custom Versioning
```bash
# Extract from task title or board memory
VERSION=$(echo "$TASK_TITLE" | grep -oP 'v\d+\.\d+\.\d+')
```

## Watchdog / Continuity

This skill uses a **threshold-based watchdog** pattern:

1. **On heartbeat**, check number of done tasks since `last_release_date`
2. **If count ≥ threshold** (default: 10), auto-generate release notes
3. **Store state** in board memory (tag: `release_metadata`)
4. **Create review task** for manual approval before publishing

**Manual Override:**
- Create task with title "Generate Release Notes for [version]"
- Skill will immediately generate notes regardless of threshold

**Error Handling:**
- If release generation fails, log error to board memory (tag: `release_errors`)
- Retry on next heartbeat or manual trigger
- If GitHub publishing fails, task remains in review for manual retry

**Continuity:**
- Release metadata persists across agent restarts
- Generated release notes stored in board memory for historical reference
- Can re-generate release notes for any date range by adjusting `last_release_date`
