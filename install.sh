#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_DIR="$STATE_DIR/openclaw-mission-control-install"

LINUX_DISTRO=""
PKG_MANAGER=""
PKG_UPDATED=0
DOCKER_USE_SUDO=0
INTERACTIVE=0

FORCE_MODE=""
FORCE_BACKEND_PORT=""
FORCE_FRONTEND_PORT=""
FORCE_PUBLIC_HOST=""
FORCE_API_URL=""
FORCE_TOKEN_MODE=""
FORCE_LOCAL_AUTH_TOKEN=""
FORCE_DB_MODE=""
FORCE_DATABASE_URL=""
FORCE_START_SERVICES=""

if [[ -t 0 ]]; then
  INTERACTIVE=1
fi

info() {
  printf '[INFO] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

error() {
  printf '[ERROR] %s\n' "$*" >&2
}

die() {
  error "$*"
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options]

Options:
  --mode <docker|local>
  --backend-port <port>
  --frontend-port <port>
  --public-host <host>
  --api-url <url>
  --token-mode <generate|manual>
  --local-auth-token <token>      Required when --token-mode manual
  --db-mode <docker|external>     Local mode only
  --database-url <url>            Required when --db-mode external
  --start-services <yes|no>       Local mode only
  -h, --help

If an option is omitted, the script prompts in interactive mode and uses defaults in non-interactive mode.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --mode)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --mode"
        fi
        FORCE_MODE="$2"
        shift 2
        ;;
      --backend-port)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --backend-port"
        fi
        FORCE_BACKEND_PORT="$2"
        shift 2
        ;;
      --frontend-port)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --frontend-port"
        fi
        FORCE_FRONTEND_PORT="$2"
        shift 2
        ;;
      --public-host)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --public-host"
        fi
        FORCE_PUBLIC_HOST="$2"
        shift 2
        ;;
      --api-url)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --api-url"
        fi
        FORCE_API_URL="$2"
        shift 2
        ;;
      --token-mode)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --token-mode"
        fi
        FORCE_TOKEN_MODE="$2"
        shift 2
        ;;
      --local-auth-token)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --local-auth-token"
        fi
        FORCE_LOCAL_AUTH_TOKEN="$2"
        shift 2
        ;;
      --db-mode)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --db-mode"
        fi
        FORCE_DB_MODE="$2"
        shift 2
        ;;
      --database-url)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --database-url"
        fi
        FORCE_DATABASE_URL="$2"
        shift 2
        ;;
      --start-services)
        if [[ $# -lt 2 || -z ${2:-} ]]; then
          usage
          die "Missing value for --start-services"
        fi
        FORCE_START_SERVICES="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

is_one_of() {
  local value="$1"
  shift
  local option
  for option in "$@"; do
    if [[ "$value" == "$option" ]]; then
      return 0
    fi
  done
  return 1
}

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    if ! command_exists sudo; then
      die "sudo is required to install system packages."
    fi
    sudo "$@"
  fi
}

install_command_hint() {
  local manager="$1"
  shift
  local -a packages
  packages=("$@")

  case "$manager" in
    apt)
      printf 'sudo apt-get update && sudo apt-get install -y %s' "${packages[*]}"
      ;;
    dnf)
      printf 'sudo dnf install -y %s' "${packages[*]}"
      ;;
    yum)
      printf 'sudo yum install -y %s' "${packages[*]}"
      ;;
    zypper)
      printf 'sudo zypper install -y %s' "${packages[*]}"
      ;;
    pacman)
      printf 'sudo pacman -Sy --noconfirm %s' "${packages[*]}"
      ;;
    *)
      printf 'install packages manually: %s' "${packages[*]}"
      ;;
  esac
}

detect_platform() {
  local uname_s
  uname_s="$(uname -s)"
  if [[ "$uname_s" != "Linux" ]]; then
    die "Unsupported platform: $uname_s. Linux is required."
  fi

  if [[ ! -r /etc/os-release ]]; then
    die "Cannot detect Linux distribution (/etc/os-release missing)."
  fi

  # shellcheck disable=SC1091
  . /etc/os-release
  LINUX_DISTRO="${ID:-unknown}"
  # ID_LIKE is available via /etc/os-release when we need it for future detection heuristics.

  if command_exists apt-get; then
    PKG_MANAGER="apt"
  elif command_exists dnf; then
    PKG_MANAGER="dnf"
  elif command_exists yum; then
    PKG_MANAGER="yum"
  elif command_exists zypper; then
    PKG_MANAGER="zypper"
  elif command_exists pacman; then
    PKG_MANAGER="pacman"
  else
    die "Unsupported Linux distribution: $LINUX_DISTRO. No supported package manager detected (expected apt/dnf/yum/zypper/pacman)."
  fi

  if [[ "$PKG_MANAGER" != "apt" ]]; then
    warn "Detected distro '$LINUX_DISTRO' with package manager '$PKG_MANAGER'. This installer currently provides Debian/Ubuntu as stable path; other distros are scaffolded with actionable guidance."
  fi

  info "Detected Linux distro: $LINUX_DISTRO (package manager: $PKG_MANAGER)"
}

install_packages() {
  local -a packages
  packages=("$@")

  if [[ "${#packages[@]}" -eq 0 ]]; then
    return 0
  fi

  case "$PKG_MANAGER" in
    apt)
      if [[ "$PKG_UPDATED" -eq 0 ]]; then
        as_root apt-get update
        PKG_UPDATED=1
      fi
      as_root apt-get install -y "${packages[@]}"
      ;;
    dnf|yum|zypper|pacman)
      die "Automatic package install is not implemented yet for '$PKG_MANAGER'. Run: $(install_command_hint "$PKG_MANAGER" "${packages[@]}")"
      ;;
    *)
      die "Unknown package manager '$PKG_MANAGER'. Install manually: ${packages[*]}"
      ;;
  esac
}

prompt_with_default() {
  local prompt="$1"
  local default_value="$2"
  local input=""

  if [[ "$INTERACTIVE" -eq 0 ]]; then
    printf '%s\n' "$default_value"
    return
  fi

  read -r -p "$prompt [$default_value]: " input
  input="${input:-$default_value}"
  printf '%s\n' "$input"
}

prompt_choice() {
  local prompt="$1"
  local default_value="$2"
  shift 2
  local -a options
  local input=""
  local option=""
  options=("$@")

  if [[ "$INTERACTIVE" -eq 0 ]]; then
    printf '%s\n' "$default_value"
    return
  fi

  while true; do
    read -r -p "$prompt [$(IFS='/'; echo "${options[*]}")] (default: $default_value): " input
    input="${input:-$default_value}"
    for option in "${options[@]}"; do
      if [[ "$input" == "$option" ]]; then
        printf '%s\n' "$input"
        return
      fi
    done
    warn "Invalid choice: $input"
  done
}

prompt_secret() {
  local prompt="$1"
  local input=""

  if [[ "$INTERACTIVE" -eq 0 ]]; then
    printf '\n'
    return
  fi

  read -r -s -p "$prompt: " input
  printf '\n' >&2
  printf '%s\n' "$input"
}

confirm() {
  local prompt="$1"
  local default="${2:-y}"
  local input=""

  if [[ "$INTERACTIVE" -eq 0 ]]; then
    [[ "$default" == "y" ]]
    return
  fi

  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n]: " input
    input="${input:-y}"
  else
    read -r -p "$prompt [y/N]: " input
    input="${input:-n}"
  fi

  case "${input,,}" in
    y|yes)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_valid_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  ((value >= 1 && value <= 65535))
}

generate_token() {
  if command_exists openssl; then
    openssl rand -hex 32
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64
    printf '\n'
  fi
}

ensure_file_from_example() {
  local target_file="$1"
  local example_file="$2"

  if [[ -f "$target_file" ]]; then
    return
  fi

  if [[ ! -f "$example_file" ]]; then
    die "Missing example file: $example_file"
  fi

  cp "$example_file" "$target_file"
  info "Created $(realpath --relative-to="$REPO_ROOT" "$target_file" 2>/dev/null || printf '%s' "$target_file")"
}

upsert_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp_file

  tmp_file="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { done = 0 }
    $0 ~ ("^" k "=") {
      print k "=" v
      done = 1
      next
    }
    { print }
    END {
      if (!done) {
        print k "=" v
      }
    }
  ' "$file" >"$tmp_file"
  mv "$tmp_file" "$file"
}

ensure_command_with_packages() {
  local cmd="$1"
  shift
  local -a packages
  packages=("$@")

  if command_exists "$cmd"; then
    return
  fi

  info "Command '$cmd' is missing."
  if ! confirm "Install required package(s) for '$cmd' now?" "y"; then
    die "Cannot continue without '$cmd'."
  fi

  install_packages "${packages[@]}"

  if ! command_exists "$cmd"; then
    die "Failed to install '$cmd'."
  fi
}

ensure_uv() {
  if command_exists uv; then
    return
  fi

  info "uv is not installed."
  if ! confirm "Install uv using the official installer?" "y"; then
    die "Cannot continue without uv for local deployment."
  fi

  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"

  if ! command_exists uv; then
    die "uv was installed but is not available in PATH."
  fi
}

ensure_nodejs() {
  local node_major="0"
  local node_version=""

  if command_exists node; then
    node_version="$(node -v || true)"
    node_major="${node_version#v}"
    node_major="${node_major%%.*}"
    if [[ "$node_major" =~ ^[0-9]+$ ]] && ((node_major >= 22)) && command_exists npm; then
      return
    fi
  fi

  info "Node.js >= 22 is required for local deployment."
  if ! confirm "Install or upgrade Node.js now?" "y"; then
    die "Cannot continue without Node.js >= 22."
  fi

  if [[ "$PKG_MANAGER" != "apt" ]]; then
    die "Node.js auto-install is currently implemented for apt-based distros only. Install Node.js >= 22 manually, then rerun installer. Suggested command: $(install_command_hint "$PKG_MANAGER" nodejs npm)"
  fi

  install_packages ca-certificates curl gnupg
  curl -fsSL https://deb.nodesource.com/setup_22.x | as_root bash -
  install_packages nodejs

  if ! command_exists node || ! command_exists npm; then
    die "Node.js/npm installation failed."
  fi

  # Refresh command lookup + PATH after install (CI runners often have an older Node in PATH).
  hash -r || true
  if [[ -x /usr/bin/node ]]; then
    export PATH="/usr/bin:$PATH"
  fi

  node_version="$(node -v || true)"
  node_major="${node_version#v}"
  node_major="${node_major%%.*}"
  if [[ ! "$node_major" =~ ^[0-9]+$ ]] || ((node_major < 22)); then
    die "Detected Node.js $node_version. Node.js >= 22 is required."
  fi
}

ensure_docker() {
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    return
  fi

  info "Docker and Docker Compose v2 are required."
  if ! confirm "Install Docker tooling now?" "y"; then
    die "Cannot continue without Docker."
  fi

  install_packages docker.io
  if ! install_packages docker-compose-plugin; then
    warn "docker-compose-plugin unavailable; trying docker-compose package."
    install_packages docker-compose
  fi

  if command_exists systemctl; then
    as_root systemctl enable --now docker || warn "Could not enable/start docker service automatically."
  fi

  if ! command_exists docker; then
    die "Docker installation failed."
  fi

  if ! docker compose version >/dev/null 2>&1; then
    die "Docker Compose v2 is unavailable ('docker compose')."
  fi
}

docker_compose() {
  local tmp_file
  local rc=0

  if [[ "$DOCKER_USE_SUDO" -eq 1 ]]; then
    as_root docker compose "$@"
    return
  fi

  tmp_file="$(mktemp)"
  if docker compose "$@" 2> >(tee "$tmp_file" >&2); then
    rm -f "$tmp_file"
    return
  fi
  rc=$?

  if [[ "$(id -u)" -ne 0 ]] && command_exists sudo; then
    if grep -Eqi 'permission denied|docker.sock|cannot connect to the docker daemon' "$tmp_file"; then
      warn "Docker permission issue detected, retrying with sudo."
      DOCKER_USE_SUDO=1
      rm -f "$tmp_file"
      as_root docker compose "$@"
      return
    fi
  fi

  rm -f "$tmp_file"
  return "$rc"
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local timeout_seconds="${3:-120}"
  local i

  for ((i = 1; i <= timeout_seconds; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      info "$label is reachable at $url"
      return 0
    fi
    sleep 1
  done

  warn "Timed out waiting for $label at $url"
  return 1
}

start_local_services() {
  local backend_port="$1"
  local frontend_port="$2"

  mkdir -p "$LOG_DIR"

  info "Starting backend in background..."
  (
    cd "$REPO_ROOT/backend"
    nohup uv run uvicorn app.main:app --host 0.0.0.0 --port "$backend_port" >"$LOG_DIR/backend.log" 2>&1 &
    echo $! >"$LOG_DIR/backend.pid"
  )

  info "Starting frontend in background..."
  (
    cd "$REPO_ROOT/frontend"
    nohup npm run start -- --hostname 0.0.0.0 --port "$frontend_port" >"$LOG_DIR/frontend.log" 2>&1 &
    echo $! >"$LOG_DIR/frontend.pid"
  )
}

ensure_repo_layout() {
  [[ -f "$REPO_ROOT/Makefile" ]] || die "Run $SCRIPT_NAME from repository root."
  [[ -f "$REPO_ROOT/compose.yml" ]] || die "Missing compose.yml in repository root."
}

main() {
  local deployment_mode
  local public_host
  local backend_port
  local frontend_port
  local next_public_api_url
  local token_mode
  local local_auth_token
  local db_mode="docker"
  local database_url=""
  local start_services="yes"

  cd "$REPO_ROOT"
  ensure_repo_layout
  parse_args "$@"

  detect_platform
  info "Platform detected: linux ($LINUX_DISTRO)"

  if [[ -n "$FORCE_MODE" ]]; then
    deployment_mode="$FORCE_MODE"
  else
    deployment_mode="$(prompt_choice "Deployment mode" "docker" "docker" "local")"
  fi
  if ! is_one_of "$deployment_mode" "docker" "local"; then
    die "Invalid deployment mode: $deployment_mode (expected docker|local)"
  fi

  while true; do
    if [[ -n "$FORCE_BACKEND_PORT" ]]; then
      backend_port="$FORCE_BACKEND_PORT"
    else
      backend_port="$(prompt_with_default "Backend port" "8000")"
    fi
    is_valid_port "$backend_port" && break
    warn "Invalid backend port: $backend_port"
    FORCE_BACKEND_PORT=""
  done

  while true; do
    if [[ -n "$FORCE_FRONTEND_PORT" ]]; then
      frontend_port="$FORCE_FRONTEND_PORT"
    else
      frontend_port="$(prompt_with_default "Frontend port" "3000")"
    fi
    is_valid_port "$frontend_port" && break
    warn "Invalid frontend port: $frontend_port"
    FORCE_FRONTEND_PORT=""
  done

  if [[ -n "$FORCE_PUBLIC_HOST" ]]; then
    public_host="$FORCE_PUBLIC_HOST"
  else
    public_host="$(prompt_with_default "Public host/IP for browser access" "localhost")"
  fi
  if [[ -n "$FORCE_API_URL" ]]; then
    next_public_api_url="$FORCE_API_URL"
  else
    next_public_api_url="$(prompt_with_default "Public API URL used by frontend" "http://$public_host:$backend_port")"
  fi

  if [[ -n "$FORCE_TOKEN_MODE" ]]; then
    token_mode="$FORCE_TOKEN_MODE"
  else
    token_mode="$(prompt_choice "LOCAL_AUTH_TOKEN" "generate" "generate" "manual")"
  fi
  if ! is_one_of "$token_mode" "generate" "manual"; then
    die "Invalid token mode: $token_mode (expected generate|manual)"
  fi
  if [[ "$token_mode" == "manual" ]]; then
    if [[ -n "$FORCE_LOCAL_AUTH_TOKEN" ]]; then
      local_auth_token="$FORCE_LOCAL_AUTH_TOKEN"
    else
      local_auth_token="$(prompt_secret "Enter LOCAL_AUTH_TOKEN (min 50 chars)")"
    fi
    if [[ "${#local_auth_token}" -lt 50 ]]; then
      die "LOCAL_AUTH_TOKEN must be at least 50 characters."
    fi
  else
    local_auth_token="$(generate_token)"
    info "Generated LOCAL_AUTH_TOKEN."
  fi

  if [[ "$deployment_mode" == "local" ]]; then
    if [[ -n "$FORCE_DB_MODE" ]]; then
      db_mode="$FORCE_DB_MODE"
    else
      db_mode="$(prompt_choice "Database source for local deployment" "docker" "docker" "external")"
    fi
    if ! is_one_of "$db_mode" "docker" "external"; then
      die "Invalid db mode: $db_mode (expected docker|external)"
    fi
    if [[ "$db_mode" == "external" ]]; then
      if [[ -n "$FORCE_DATABASE_URL" ]]; then
        database_url="$FORCE_DATABASE_URL"
      else
        database_url="$(prompt_with_default "External DATABASE_URL" "postgresql+psycopg://postgres:postgres@localhost:5432/mission_control")"
      fi
    fi
    if [[ -n "$FORCE_START_SERVICES" ]]; then
      start_services="$FORCE_START_SERVICES"
    else
      start_services="$(prompt_choice "Start backend/frontend processes automatically after bootstrap" "yes" "yes" "no")"
    fi
    if ! is_one_of "$start_services" "yes" "no"; then
      die "Invalid start-services value: $start_services (expected yes|no)"
    fi
  fi

  ensure_command_with_packages curl curl
  ensure_command_with_packages git git
  ensure_command_with_packages make make
  ensure_command_with_packages openssl openssl

  if [[ "$deployment_mode" == "docker" || "$db_mode" == "docker" ]]; then
    ensure_docker
  fi

  if [[ "$deployment_mode" == "local" ]]; then
    ensure_uv
    ensure_nodejs
    info "Ensuring Python 3.12 is available through uv..."
    uv python install 3.12
  fi

  ensure_file_from_example "$REPO_ROOT/.env" "$REPO_ROOT/.env.example"
  upsert_env_value "$REPO_ROOT/.env" "BACKEND_PORT" "$backend_port"
  upsert_env_value "$REPO_ROOT/.env" "FRONTEND_PORT" "$frontend_port"
  upsert_env_value "$REPO_ROOT/.env" "AUTH_MODE" "local"
  upsert_env_value "$REPO_ROOT/.env" "LOCAL_AUTH_TOKEN" "$local_auth_token"
  upsert_env_value "$REPO_ROOT/.env" "NEXT_PUBLIC_API_URL" "$next_public_api_url"
  upsert_env_value "$REPO_ROOT/.env" "CORS_ORIGINS" "http://$public_host:$frontend_port"

  if [[ "$deployment_mode" == "docker" ]]; then
    upsert_env_value "$REPO_ROOT/.env" "DB_AUTO_MIGRATE" "true"

    info "Starting production-like Docker stack..."
    docker_compose -f compose.yml --env-file .env up -d --build

    wait_for_http "http://127.0.0.1:$backend_port/healthz" "Backend" 180 || true
    wait_for_http "http://127.0.0.1:$frontend_port" "Frontend" 180 || true

    cat <<SUMMARY

Bootstrap complete (Docker mode).

Access URLs:
- Frontend: http://$public_host:$frontend_port
- Backend:  http://$public_host:$backend_port/healthz

Auth:
- AUTH_MODE=local
- LOCAL_AUTH_TOKEN=$local_auth_token

Stop stack:
  docker compose -f compose.yml --env-file .env down
SUMMARY
    return
  fi

  ensure_file_from_example "$REPO_ROOT/backend/.env" "$REPO_ROOT/backend/.env.example"
  ensure_file_from_example "$REPO_ROOT/frontend/.env" "$REPO_ROOT/frontend/.env.example"

  if [[ "$db_mode" == "docker" ]]; then
    upsert_env_value "$REPO_ROOT/.env" "POSTGRES_DB" "mission_control"
    upsert_env_value "$REPO_ROOT/.env" "POSTGRES_USER" "postgres"
    upsert_env_value "$REPO_ROOT/.env" "POSTGRES_PASSWORD" "postgres"
    upsert_env_value "$REPO_ROOT/.env" "POSTGRES_PORT" "5432"

    database_url="postgresql+psycopg://postgres:postgres@localhost:5432/mission_control"

    info "Starting PostgreSQL via Docker..."
    docker_compose -f compose.yml --env-file .env up -d db
  fi

  upsert_env_value "$REPO_ROOT/backend/.env" "ENVIRONMENT" "prod"
  upsert_env_value "$REPO_ROOT/backend/.env" "DATABASE_URL" "$database_url"
  upsert_env_value "$REPO_ROOT/backend/.env" "AUTH_MODE" "local"
  upsert_env_value "$REPO_ROOT/backend/.env" "LOCAL_AUTH_TOKEN" "$local_auth_token"
  upsert_env_value "$REPO_ROOT/backend/.env" "CORS_ORIGINS" "http://$public_host:$frontend_port"
  upsert_env_value "$REPO_ROOT/backend/.env" "BASE_URL" "http://$public_host:$backend_port"
  upsert_env_value "$REPO_ROOT/backend/.env" "DB_AUTO_MIGRATE" "false"

  upsert_env_value "$REPO_ROOT/frontend/.env" "NEXT_PUBLIC_API_URL" "$next_public_api_url"
  upsert_env_value "$REPO_ROOT/frontend/.env" "NEXT_PUBLIC_AUTH_MODE" "local"

  info "Installing backend/frontend dependencies..."
  make setup

  info "Applying database migrations..."
  make backend-migrate

  info "Building frontend production bundle..."
  make frontend-build

  if [[ "$start_services" == "yes" ]]; then
    start_local_services "$backend_port" "$frontend_port"
    wait_for_http "http://127.0.0.1:$backend_port/healthz" "Backend" 120 || true
    wait_for_http "http://127.0.0.1:$frontend_port" "Frontend" 120 || true
  fi

  cat <<SUMMARY

Bootstrap complete (Local mode).

Access URLs:
- Frontend: http://$public_host:$frontend_port
- Backend:  http://$public_host:$backend_port/healthz

Auth:
- AUTH_MODE=local
- LOCAL_AUTH_TOKEN=$local_auth_token

If services were started by this script, logs are under:
- $LOG_DIR/backend.log
- $LOG_DIR/frontend.log

Stop local background services:
  kill "\$(cat $LOG_DIR/backend.pid)" "\$(cat $LOG_DIR/frontend.pid)"
SUMMARY
}

main "$@"