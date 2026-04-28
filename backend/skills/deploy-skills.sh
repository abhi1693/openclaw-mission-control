#!/usr/bin/env bash
# Deploy MC-side skills to the gateway at .60.
#
# Skills live on the gateway at /root/.openclaw/skills/ and are auto-discovered
# by openclaw via load.watch:true (no allow-list, no Sync API call needed).
# Filesystem watch picks up changes within ~250ms of write.
#
# Usage:
#   ./deploy-skills.sh           # rsync local skills to .60 (no deletes)
#   ./deploy-skills.sh --prune   # also delete prod-only skills not in local
#   ./deploy-skills.sh --dry     # show what would change, do not write
#
# Source of truth: this directory. Anything under here syncs upward.
# Anything on .60 not under here is left alone unless --prune is passed.

set -euo pipefail

GATEWAY_HOST="${SKILLS_GATEWAY_HOST:-192.168.2.60}"
GATEWAY_USER="${SKILLS_GATEWAY_USER:-root}"
GATEWAY_DIR="${SKILLS_GATEWAY_DIR:-/root/.openclaw/skills/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RSYNC_FLAGS=(-av --include='*/' --include='SKILL.md' --include='references/***' --include='scripts/***' --exclude='*' --exclude='deploy-skills.sh' --exclude='README.md')

case "${1:-}" in
  --prune) RSYNC_FLAGS+=(--delete) ;;
  --dry)   RSYNC_FLAGS+=(--dry-run) ;;
  "")      ;;
  *) echo "Unknown flag: $1" >&2; exit 2 ;;
esac

echo "Deploying skills from ${SCRIPT_DIR} to ${GATEWAY_USER}@${GATEWAY_HOST}:${GATEWAY_DIR}"
rsync "${RSYNC_FLAGS[@]}" "${SCRIPT_DIR}/" "${GATEWAY_USER}@${GATEWAY_HOST}:${GATEWAY_DIR}"

echo
echo "Verifying deployed skills on gateway:"
ssh "${GATEWAY_USER}@${GATEWAY_HOST}" "ls -la ${GATEWAY_DIR}"

echo
echo "Done. Gateway picks up changes within ~250ms via load.watch:true."
echo "No Sync Templates API call required for skills."
