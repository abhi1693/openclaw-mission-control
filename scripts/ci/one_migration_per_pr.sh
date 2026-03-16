#!/usr/bin/env bash
set -euo pipefail

# Enforce: if a PR adds migration files under backend/migrations/versions/, it must add <= 1.
# Rationale: keeps review/rollback straightforward and avoids surprise multiple-head merges.

if [ "${GITHUB_EVENT_NAME:-}" != "pull_request" ]; then
  echo "Not a pull_request event; skipping one-migration-per-PR gate."
  exit 0
fi

BASE_SHA="${GITHUB_BASE_SHA:-${GITHUB_EVENT_PULL_REQUEST_BASE_SHA:-}}"
HEAD_SHA="${GITHUB_SHA:-}"

if [ -z "$BASE_SHA" ] || [ -z "$HEAD_SHA" ]; then
  echo "Missing BASE_SHA/HEAD_SHA (BASE_SHA='$BASE_SHA', HEAD_SHA='$HEAD_SHA')"
  exit 2
fi

# Ensure base is present in shallow clones.
# NOTE: fetch may fail due to fetch-depth/ref settings; validate the commit exists after fetch.
git fetch --no-tags --depth=1 origin "$BASE_SHA" || true
if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "Base commit '$BASE_SHA' not found locally even after fetch. Check checkout fetch-depth / ref configuration."
  exit 2
fi

# Only count *newly added* migration files. Modified/deleted migrations should not trip this gate.
# See review thread: https://github.com/abhi1693/openclaw-mission-control/pull/136#discussion_r2807812935
ADDED_FILES=$(git diff --name-only --diff-filter=A "$BASE_SHA" "$HEAD_SHA" || true)
if [ -z "$ADDED_FILES" ]; then
  echo "No added files detected."
  exit 0
fi

# Be slightly strict: avoid counting non-migration python files (e.g. __init__.py).
# Alembic versions typically look like: <hex_revision>_<slug>.py
MIGRATIONS=$(echo "$ADDED_FILES" | grep -E '^backend/migrations/versions/[0-9a-f]+_.*\.py$' || true)
COUNT=$(echo "$MIGRATIONS" | sed '/^$/d' | wc -l | tr -d ' ')

if [ "$COUNT" -le 1 ]; then
  echo "Migration gate OK (migrations_added=$COUNT)."
  exit 0
fi

echo "Migration gate FAILED: this PR adds $COUNT migration files; policy allows at most 1."
echo

echo "Migrations detected:"
echo "$MIGRATIONS"
echo

echo "How to fix:"
echo "- Consolidate schema changes into a single migration file (squash)."
echo "- If you have multiple Alembic heads, create ONE merge migration instead of several."
echo "- If you truly need multiple migrations, split into multiple PRs."

exit 1
