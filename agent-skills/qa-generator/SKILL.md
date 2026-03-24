---
name: qa-generator
description: Automatically generate test plans and test cases for features moving to review
---

# QA Generator

Automated test case generator that creates comprehensive test plans when features move to review. Generates unit test cases, integration scenarios, edge cases, and optionally creates test file stubs using AI assistance.

## When to use

- When a task moves to `status=review` (triggered by Lead agent)
- When a task has tag `needs-tests`
- When explicitly requested via task title "Generate tests for: [feature]"
- On heartbeat: scan for review tasks without test plans

## When NOT to use

- For tasks that are non-code changes (docs, config)
- When tests already exist (check for test file updates in PR)
- For trivial fixes (typo corrections, formatting)

## Prerequisites

**Environment Variables:**
- `ANTHROPIC_API_KEY` (optional) - For Claude API to generate test stubs
- `REPO_PATH` (optional) - Path to code repository for test file generation

**Tools Required:**
- `curl` - for API calls
- `jq` - for JSON parsing
- `claude` CLI (optional) - for AI-powered test generation

**Mission Control Setup:**
- Task read/write access
- Task comment permissions
- Task creation permissions

## Workflow

### 1. Detect Review Tasks Needing Tests

```bash
# Get all review tasks
REVIEW_TASKS=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=review" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '.tasks[]')

# Filter tasks that don't have test plans yet
# (check if task has comment containing "Test Plan" or tag "qa-complete")
echo "$REVIEW_TASKS" | jq -c 'select((.tags[]? == "qa-complete") | not)' | while read -r task; do
  TASK_ID=$(echo "$task" | jq -r '.id')
  TASK_TITLE=$(echo "$task" | jq -r '.title')
  TASK_DESC=$(echo "$task" | jq -r '.description')

  echo "Generating test plan for: $TASK_TITLE"
  # Proceed to step 2
done
```

### 2. Analyze Task to Understand Feature

```bash
# Extract key information from task
FEATURE_NAME=$(echo "$TASK_TITLE" | sed 's/^[^:]*:\s*//')
FEATURE_DESC=$(echo "$TASK_DESC")

# Check if task has repo_path custom field (path to modified files)
REPO_PATH=$(echo "$task" | jq -r '.custom_fields.repo_path // ""')

# If PR number is mentioned, fetch changed files
PR_NUMBER=$(echo "$TASK_DESC" | grep -oP '#\K\d+' | head -1)

if [ -n "$PR_NUMBER" ] && command -v gh &> /dev/null; then
  CHANGED_FILES=$(gh pr view $PR_NUMBER --json files | jq -r '.files[].path')
  echo "Changed files: $CHANGED_FILES"
fi
```

### 3. Generate Test Cases

```bash
# Generate comprehensive test plan based on feature description
generate_test_plan() {
  local feature="$1"
  local description="$2"

  cat <<EOF
# Test Plan: $feature

**Status:** Draft
**Generated:** $(date +%Y-%m-%d)

## Unit Test Cases

### Happy Path
- [ ] Test basic functionality works as expected
- [ ] Test function returns correct output for valid input
- [ ] Test state updates correctly after operation

### Edge Cases
- [ ] Test with empty/null input
- [ ] Test with invalid input types
- [ ] Test with boundary values (min/max)
- [ ] Test with special characters in strings

### Error Handling
- [ ] Test error thrown for invalid input
- [ ] Test graceful degradation on failure
- [ ] Test error messages are descriptive

## Integration Test Scenarios

### API/Service Integration
- [ ] Test API endpoint returns expected response
- [ ] Test authentication/authorization works
- [ ] Test rate limiting is enforced
- [ ] Test error responses match API spec

### Database Integration
- [ ] Test data is persisted correctly
- [ ] Test transactions rollback on error
- [ ] Test concurrent access handling
- [ ] Test data validation constraints

### UI Integration
- [ ] Test user workflow end-to-end
- [ ] Test form validation and submission
- [ ] Test error messages displayed to user
- [ ] Test loading states and async operations

## Performance Tests
- [ ] Test response time under normal load
- [ ] Test behavior with large datasets
- [ ] Test memory usage stays within bounds

## Security Tests
- [ ] Test input sanitization prevents XSS/injection
- [ ] Test authentication required for protected operations
- [ ] Test authorization enforces correct permissions
- [ ] Test sensitive data is not exposed in logs/errors

## Browser/Platform Compatibility
- [ ] Test in Chrome
- [ ] Test in Firefox
- [ ] Test in Safari
- [ ] Test on mobile devices

## Accessibility Tests
- [ ] Test keyboard navigation works
- [ ] Test screen reader compatibility
- [ ] Test color contrast meets WCAG standards

---

**Next Steps:**
1. Review and prioritize test cases
2. Implement high-priority tests first
3. Generate test file stubs (see below)
4. Run tests and verify coverage
EOF
}

TEST_PLAN=$(generate_test_plan "$FEATURE_NAME" "$FEATURE_DESC")
```

### 4. Generate Test File Stubs (Optional)

```bash
# If repo_path is available and claude CLI is installed, generate test stubs
if [ -n "$REPO_PATH" ] && command -v claude &> /dev/null; then
  echo "Generating test file stubs..."

  # Determine test file path based on source file
  # Example: src/feature.js -> tests/feature.test.js
  TEST_FILE_PATH=$(echo "$REPO_PATH" | sed 's|^src/|tests/|; s|\.\([^.]*\)$|.test.\1|')

  # Generate test stub using Claude
  TEST_STUB=$(claude --print <<EOF
Generate a test file stub for the following feature:

**File:** $REPO_PATH
**Feature:** $FEATURE_NAME
**Description:** $FEATURE_DESC

Create a comprehensive test suite with:
1. Import statements for testing framework (Jest/Mocha/PyTest as appropriate)
2. Test cases for happy path scenarios
3. Test cases for edge cases and error handling
4. Mock setup if external dependencies are needed

Use best practices for the language/framework detected from the file extension.
Output ONLY the test code, no explanations.
EOF
)

  # Save test stub to file (if REPO_PATH is accessible)
  if [ -d "$(dirname "$TEST_FILE_PATH")" ]; then
    echo "$TEST_STUB" > "$TEST_FILE_PATH"
    echo "✅ Test stub created: $TEST_FILE_PATH"
  else
    # Otherwise, include in test plan
    TEST_PLAN+=$(cat <<EOF

## Generated Test File Stub

**Path:** \`$TEST_FILE_PATH\`

\`\`\`
$TEST_STUB
\`\`\`
EOF
)
  fi
fi
```

### 5. Post Test Plan as Task Comment

```bash
# Post test plan to task
curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg text "$TEST_PLAN" '{text: $text}')"

echo "✅ Test plan posted to task #$TASK_ID"
```

### 6. Create Follow-up Implementation Task

```bash
# Create task for implementing the tests
FOLLOWUP_DESC=$(cat <<EOF
Implement automated tests for: **$FEATURE_NAME**

## Test Plan
See parent task #$TASK_ID for full test plan.

## Priority Test Cases
1. Happy path unit tests
2. Error handling tests
3. Integration tests for critical workflows

## Test File
$(if [ -n "$TEST_FILE_PATH" ]; then
  echo "Test stub generated at: \`$TEST_FILE_PATH\`"
else
  echo "Create test file following project conventions"
fi)

## Acceptance Criteria
- [ ] All priority test cases implemented
- [ ] Tests pass in CI/CD
- [ ] Code coverage increased by at least 10%

---
*Auto-generated by QA Generator*
EOF
)

FOLLOWUP_TASK=$(curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg title "Implement tests for: $FEATURE_NAME" \
    --arg desc "$FOLLOWUP_DESC" \
    '{
      title: $title,
      description: $desc,
      status: "inbox",
      tags: ["auto-qa", "testing"]
    }')")

FOLLOWUP_ID=$(echo "$FOLLOWUP_TASK" | jq -r '.task.id')
echo "✅ Follow-up task created: #$FOLLOWUP_ID"
```

### 7. Mark Original Task as QA-Complete

```bash
# Update original task with qa-complete tag
EXISTING_TAGS=$(echo "$task" | jq -r '.tags // []')
NEW_TAGS=$(echo "$EXISTING_TAGS" | jq '. + ["qa-complete"]')

curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --argjson tags "$NEW_TAGS" '{tags: $tags}')"

# Add reference to follow-up task in comment
curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg text "✅ QA test plan generated. Implementation task created: #$FOLLOWUP_ID" \
    '{text: $text}')"
```

## Test Plan Template Structure

Generated test plans follow this structure:

1. **Unit Test Cases**
   - Happy path scenarios
   - Edge cases (null, empty, boundary values)
   - Error handling

2. **Integration Test Scenarios**
   - API/Service integration
   - Database integration
   - UI workflows

3. **Performance Tests**
   - Load testing
   - Response time
   - Resource usage

4. **Security Tests**
   - Input validation
   - Authentication/Authorization
   - Data exposure

5. **Compatibility Tests**
   - Browser testing
   - Platform testing
   - Accessibility

## API Reference (Mission Control)

### Get Review Tasks
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=review" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Post Test Plan Comment
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "# Test Plan\n..."}'
```

### Create Follow-up Task
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Implement tests for: Feature X",
    "description": "...",
    "status": "inbox",
    "tags": ["auto-qa", "testing"]
  }'
```

### Update Task Tags
```bash
curl -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tags": ["existing-tag", "qa-complete"]}'
```

## Claude CLI Reference (Optional)

### Generate Test Code
```bash
claude --print <<EOF
Generate test cases for:
[feature description]
EOF
```

## GitHub CLI Reference (Optional)

### Get PR Changed Files
```bash
gh pr view $PR_NUMBER --json files | jq -r '.files[].path'
```

## Watchdog / Continuity

This skill runs on **task status change trigger** and **heartbeat**:

1. **Primary Trigger:** When Lead agent moves task to `status=review`
2. **Heartbeat Scan:** Check for review tasks missing `qa-complete` tag
3. **State Tracking:** Use `qa-complete` tag to avoid re-generating test plans
4. **Persistence:** Test plans stored as task comments (permanent record)

**Error Handling:**
- If test generation fails, post error comment and tag task with `qa-failed`
- If Claude CLI not available, generate markdown test plan only (no stubs)
- Retry failed generations on next heartbeat

**Continuity Pattern:**
```bash
# On heartbeat, find review tasks without QA
NEEDS_QA=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=review" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '
    .tasks[] |
    select((.tags[]? == "qa-complete") | not) |
    .id
  ')

# Generate test plans for each
```

## Customization

Adjust test plan templates based on project type:

- **Frontend:** Focus on UI tests, accessibility, browser compatibility
- **Backend:** Focus on API tests, database integration, performance
- **Mobile:** Focus on device compatibility, offline behavior, gestures
- **Data Science:** Focus on data validation, model accuracy, edge cases
