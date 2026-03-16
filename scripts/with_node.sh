#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  with_node.sh [--check] [--cwd DIR] [--] <command> [args...]

Ensures node/npm/npx are available (optionally via nvm) before running a command.

Options:
  --check       Only verify node/npm/npx are available (no command required).
  --cwd DIR     Change to DIR before running.
  -h, --help    Show help.
EOF
}

CHECK_ONLY="false"
CWD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ONLY="true"
      shift
      ;;
    --cwd)
      CWD="${2:-}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ -n "$CWD" ]]; then
  : # handled after we resolve repo root from this script's location
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

if [[ -n "$CWD" ]]; then
  cd "$CWD"
fi

read_nvmrc() {
  local path="$1"
  if [[ -f "$path" ]]; then
    command tr -d ' \t\r\n' <"$path" || true
  fi
}

version_greater() {
  # Returns 0 (true) if $1 > $2 for simple semver-ish values like "v22.21.1".
  local v1="${1#v}"
  local v2="${2#v}"
  local a1 b1 c1 a2 b2 c2
  IFS=. read -r a1 b1 c1 <<<"$v1"
  IFS=. read -r a2 b2 c2 <<<"$v2"
  a1="${a1:-0}"; b1="${b1:-0}"; c1="${c1:-0}"
  a2="${a2:-0}"; b2="${b2:-0}"; c2="${c2:-0}"
  if ((a1 != a2)); then ((a1 > a2)); return; fi
  if ((b1 != b2)); then ((b1 > b2)); return; fi
  ((c1 > c2))
}

bootstrap_nvm_if_needed() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && command -v npx >/dev/null 2>&1; then
    return 0
  fi

  local nvm_dir="${NVM_DIR:-$HOME/.nvm}"
  if [[ ! -s "$nvm_dir/nvm.sh" ]]; then
    return 0
  fi

  # nvm is not guaranteed to be safe under `set -u`.
  set +u
  # shellcheck disable=SC1090
  . "$nvm_dir/nvm.sh"

  local version=""
  version="$(read_nvmrc "$REPO_ROOT/.nvmrc")"
  if [[ -z "$version" ]]; then
    version="$(read_nvmrc "$REPO_ROOT/frontend/.nvmrc")"
  fi

  if [[ -n "$version" ]]; then
    nvm use --silent "$version" >/dev/null 2>&1 || true
  else
    # Prefer a user-defined nvm default, otherwise pick the newest installed version.
    nvm use --silent default >/dev/null 2>&1 || true
    if ! command -v node >/dev/null 2>&1; then
      local versions_dir="$nvm_dir/versions/node"
      if [[ -d "$versions_dir" ]]; then
        local latest=""
        local candidate=""
        for candidate in "$versions_dir"/*; do
          [[ -d "$candidate" ]] || continue
          candidate="$(basename "$candidate")"
          [[ "$candidate" =~ ^v?[0-9]+(\\.[0-9]+){0,2}$ ]] || continue
          if [[ -z "$latest" ]] || version_greater "$candidate" "$latest"; then
            latest="$candidate"
          fi
        done
        [[ -n "$latest" ]] && nvm use --silent "$latest" >/dev/null 2>&1 || true
      fi
    fi
  fi

  set -u
}

bootstrap_nvm_if_needed

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node is required to run frontend targets." >&2
  echo "Install Node.js or make it available via nvm (set NVM_DIR and ensure \$NVM_DIR/nvm.sh exists)." >&2
  echo "Tip: add a project .nvmrc or set an nvm default alias (e.g. 'nvm alias default <version>')." >&2
  exit 127
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is required to run frontend targets." >&2
  echo "Install Node.js (includes npm/npx) or ensure your nvm-selected Node provides npm." >&2
  exit 127
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: npx is required to run frontend targets (usually installed with npm)." >&2
  echo "Install Node.js (includes npm/npx) or ensure your npm install includes npx." >&2
  exit 127
fi

if [[ "$CHECK_ONLY" == "true" ]]; then
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

exec "$@"
