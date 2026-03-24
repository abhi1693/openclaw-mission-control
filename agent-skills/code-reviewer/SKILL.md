---
name: code-reviewer
description: Automated code review for PRs with security, quality, and performance analysis
---

# Code Reviewer

Automated code review agent that analyzes pull requests, identifies security issues, code quality problems, and performance concerns. Posts detailed review comments and creates follow-up tasks for critical issues.

## When to use

- When a task moves to `status=review` with tag `needs-code-review`
- When a task title starts with "Review PR:" or "Code Review:"
- When a PR is opened/updated (via webhook, if configured)
- On heartbeat: scan for review tasks that haven't been reviewed yet

## When NOT to use

- For design/architecture reviews (use manual review instead)
- For non-code changes (docs, config files only)
- When `gh` CLI is not authenticated or available
- For draft PRs (unless explicitly requested)

## Prerequisites

**Environment Variables:**
- `GITHUB_TOKEN` - GitHub personal access token (if not using gh auth)
- `GITHUB_REPO` (optional) - Repository in format `owner/repo`

**Tools Required:**
- `gh` - GitHub CLI (must be authenticated: `gh auth status`)
- `curl` - for API calls
- `jq` - for JSON parsing

**Mission Control Setup:**
- Task read/write access
- Task comment permissions
- Task creation permissions (for follow-ups)

## Workflow

### 1. Detect Review Tasks

```bash
# Get all review tasks with needs-code-review tag
REVIEW_TASKS=$(curl -s "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=review" \
  -H "Authorization: Bearer $AUTH_TOKEN" | jq -r '
    .tasks[] |
    select(.tags[]? == "needs-code-review") |
    @json
  ')

# Process each review task
echo "$REVIEW_TASKS" | while read -r task_json; do
  TASK_ID=$(echo "$task_json" | jq -r '.id')
  TASK_TITLE=$(echo "$task_json" | jq -r '.title')
  TASK_DESC=$(echo "$task_json" | jq -r '.description')

  # Extract PR number from title or description
  PR_NUMBER=$(echo "$TASK_TITLE $TASK_DESC" | grep -oP '#\K\d+' | head -1)

  if [ -n "$PR_NUMBER" ]; then
    echo "Reviewing PR #$PR_NUMBER for task $TASK_ID"
    # Proceed to step 2
  fi
done
```

### 2. Fetch PR Diff

```bash
# Get PR details and diff using gh CLI
PR_INFO=$(gh pr view $PR_NUMBER --json title,body,files,additions,deletions)

PR_TITLE=$(echo "$PR_INFO" | jq -r '.title')
PR_BODY=$(echo "$PR_INFO" | jq -r '.body')
FILES_CHANGED=$(echo "$PR_INFO" | jq -r '.files | length')
ADDITIONS=$(echo "$PR_INFO" | jq -r '.additions')
DELETIONS=$(echo "$PR_INFO" | jq -r '.deletions')

# Get full diff
PR_DIFF=$(gh pr diff $PR_NUMBER)

echo "PR #$PR_NUMBER: $PR_TITLE"
echo "Files changed: $FILES_CHANGED (+$ADDITIONS -$DELETIONS)"
```

### 3. Analyze Code (Security, Quality, Performance)

```bash
# Security checks
check_security() {
  local diff="$1"
  local issues=""

  # Check for hardcoded secrets
  if echo "$diff" | grep -qiE '(password|api[_-]?key|secret|token)\s*=\s*["\047][^"\047]+["\047]'; then
    issues+="- **Security**: Possible hardcoded credentials detected\n"
  fi

  # Check for SQL injection risks
  if echo "$diff" | grep -qE 'execute\(.*\+.*\)|query\(.*\+.*\)'; then
    issues+="- **Security**: Potential SQL injection (string concatenation in queries)\n"
  fi

  # Check for eval/exec
  if echo "$diff" | grep -qE '\beval\(|\bexec\('; then
    issues+="- **Security**: Dangerous eval/exec usage detected\n"
  fi

  # Check for XSS risks (innerHTML, dangerouslySetInnerHTML)
  if echo "$diff" | grep -qE 'innerHTML|dangerouslySetInnerHTML'; then
    issues+="- **Security**: XSS risk - innerHTML or dangerouslySetInnerHTML used\n"
  fi

  echo -e "$issues"
}

# Code quality checks
check_quality() {
  local diff="$1"
  local issues=""

  # Check for console.log (should use proper logging)
  if echo "$diff" | grep -qE '^\+.*console\.(log|debug|info)'; then
    issues+="- **Quality**: console.log statements should be removed or use proper logger\n"
  fi

  # Check for TODO/FIXME without issue tracking
  if echo "$diff" | grep -qE '^\+.*(TODO|FIXME)' | grep -qvE '#\d+'; then
    issues+="- **Quality**: TODO/FIXME comments should reference issue numbers\n"
  fi

  # Check for large functions (>50 lines added in single function)
  # (simplified check - count consecutive + lines)
  if echo "$diff" | awk '/^\+.*function|^\+.*def / {count=0} /^\+/ {count++} count>50 {print; exit}' | grep -q .; then
    issues+="- **Quality**: Large function detected (consider breaking into smaller functions)\n"
  fi

  echo -e "$issues"
}

# Performance checks
check_performance() {
  local diff="$1"
  local issues=""

  # Check for N+1 query patterns
  if echo "$diff" | grep -qE '^\+.*\.map\(.*\.(find|findOne|query)'; then
    issues+="- **Performance**: Possible N+1 query pattern in map function\n"
  fi

  # Check for missing indexes (simplified - look for queries without where/index)
  if echo "$diff" | grep -qE '^\+.*\.find\(\{[^}]*\}\)' | grep -qvE 'where|index'; then
    issues+="- **Performance**: Query without explicit index (may need optimization)\n"
  fi

  # Check for synchronous file operations
  if echo "$diff" | grep -qE '\b(readFileSync|writeFileSync|existsSync)\b'; then
    issues+="- **Performance**: Synchronous file operation (consider async alternative)\n"
  fi

  echo -e "$issues"
}

# Test coverage check
check_tests() {
  local diff="$1"
  local issues=""

  # Check if code changes but no test changes
  CODE_FILES=$(echo "$PR_INFO" | jq -r '.files[] | select(.path | test("\\.(js|ts|py|go|java)$")) | .path')
  TEST_FILES=$(echo "$PR_INFO" | jq -r '.files[] | select(.path | test("(test|spec|_test)\\.(js|ts|py|go|java)$")) | .path')

  if [ -n "$CODE_FILES" ] && [ -z "$TEST_FILES" ]; then
    issues+="- **Testing**: Code changes without corresponding test updates\n"
  fi

  echo -e "$issues"
}

# Run all checks
SECURITY_ISSUES=$(check_security "$PR_DIFF")
QUALITY_ISSUES=$(check_quality "$PR_DIFF")
PERFORMANCE_ISSUES=$(check_performance "$PR_DIFF")
TEST_ISSUES=$(check_tests "$PR_DIFF")

# Determine verdict
CRITICAL_COUNT=$(echo -e "$SECURITY_ISSUES$QUALITY_ISSUES$PERFORMANCE_ISSUES$TEST_ISSUES" | grep -c "Security\|Performance.*N+1")

if [ $CRITICAL_COUNT -gt 0 ]; then
  VERDICT="request-changes"
else
  VERDICT="approve"
fi
```

### 4. Post Review Comment

```bash
# Generate review comment
REVIEW_COMMENT=$(cat <<EOF
## Code Review for PR #$PR_NUMBER

**Files Changed:** $FILES_CHANGED (+$ADDITIONS -$DELETIONS)

### Summary

Automated code review completed. Found **$CRITICAL_COUNT critical issue(s)**.

### Issues Found

${SECURITY_ISSUES:-No security issues detected.}

${QUALITY_ISSUES:-No quality issues detected.}

${PERFORMANCE_ISSUES:-No performance issues detected.}

${TEST_ISSUES:-Test coverage looks good.}

### Suggestions

1. Review flagged security concerns before merging
2. Add tests for uncovered code paths
3. Consider performance implications of identified patterns

### Verdict

**$(echo "$VERDICT" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1')**

$(if [ "$VERDICT" == "approve" ]; then
  echo "✅ No critical issues found. Safe to merge after human review."
else
  echo "⚠️  Critical issues detected. Please address before merging."
fi)

---
*Automated review by Code Reviewer agent*
EOF
)

# Post comment to MC task
curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg text "$REVIEW_COMMENT" '{text: $text}')"
```

### 5. Create Follow-up Tasks for Critical Issues

```bash
# Create follow-up tasks for each critical issue
if [ -n "$SECURITY_ISSUES" ]; then
  echo "$SECURITY_ISSUES" | grep -E "^\- \*\*Security\*\*" | while read -r issue; do
    ISSUE_DESC=$(echo "$issue" | sed 's/^- \*\*Security\*\*: //')

    curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
      -H "Authorization: Bearer $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(jq -n \
        --arg title "Security fix needed: PR #$PR_NUMBER" \
        --arg desc "Issue: $ISSUE_DESC\n\nFound in PR #$PR_NUMBER\n\nPriority: HIGH" \
        '{
          title: $title,
          description: $desc,
          status: "inbox",
          tags: ["security", "auto-review", "critical"]
        }')"
  done
fi

# Similar for critical performance issues
if echo "$PERFORMANCE_ISSUES" | grep -q "N+1"; then
  curl -s -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(jq -n \
      --arg title "Performance fix: N+1 query in PR #$PR_NUMBER" \
      --arg desc "N+1 query pattern detected in PR #$PR_NUMBER. Optimize database queries." \
      '{
        title: $title,
        description: $desc,
        status: "inbox",
        tags: ["performance", "auto-review"]
      }')"
fi
```

### 6. Update Task Status

```bash
# Update original review task based on verdict
if [ "$VERDICT" == "approve" ]; then
  # Move to done
  curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"status": "done"}'

  echo "✅ Review approved - task marked as done"
else
  # Move back to in_progress with comment
  curl -s -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"status": "in_progress"}'

  echo "⚠️  Review requires changes - task moved back to in_progress"
fi
```

## Review Checklist

The code reviewer checks for:

### Security
- [ ] Hardcoded credentials (passwords, API keys, tokens)
- [ ] SQL injection vulnerabilities
- [ ] XSS risks (innerHTML, dangerouslySetInnerHTML)
- [ ] Dangerous functions (eval, exec)
- [ ] Insecure dependencies

### Code Quality
- [ ] Debug statements (console.log)
- [ ] Untracked TODOs/FIXMEs
- [ ] Large functions (>50 lines)
- [ ] Code duplication
- [ ] Proper error handling

### Performance
- [ ] N+1 query patterns
- [ ] Missing database indexes
- [ ] Synchronous blocking operations
- [ ] Inefficient algorithms

### Testing
- [ ] Test coverage for new code
- [ ] Test updates for modified code
- [ ] Edge case handling

## API Reference (Mission Control)

### Get Review Tasks
```bash
curl "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks?status=review" \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Post Task Comment
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/comments" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Review comment"}'
```

### Update Task Status
```bash
curl -X PATCH "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'
```

### Create Follow-up Task
```bash
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Fix security issue",
    "description": "Details...",
    "status": "inbox",
    "tags": ["security", "critical"]
  }'
```

## GitHub CLI Reference

### View PR
```bash
gh pr view $PR_NUMBER --json title,body,files,additions,deletions
```

### Get PR Diff
```bash
gh pr diff $PR_NUMBER
```

### Check Auth Status
```bash
gh auth status
```

## Watchdog / Continuity

This skill runs on **heartbeat** to ensure all review tasks are processed:

1. **On each heartbeat**, scan for tasks with `status=review` and tag `needs-code-review`
2. **Check board memory** (tag: `reviewed_tasks`) to avoid re-reviewing the same task
3. **After review**, store task ID in board memory to mark as reviewed
4. **If review fails** (gh CLI error, network issue), task remains in review queue for retry

**Error Handling:**
- If `gh` is not authenticated, post comment to task asking for manual review
- If PR number cannot be extracted, request clarification via task comment
- Log review errors to board memory (tag: `review_errors`)

**State Tracking:**
```bash
# Mark task as reviewed
curl -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/memory" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"content\": {\"reviewed_tasks\": [\"$TASK_ID\"]},
    \"tags\": [\"reviewed_tasks\"]
  }"
```
