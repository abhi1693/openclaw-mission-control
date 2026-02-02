#!/usr/bin/env bash
set -euo pipefail

DB_NAME=${DB_NAME:-openclaw_agency}
DB_USER=${DB_USER:-postgres}
DB_HOST=${DB_HOST:-127.0.0.1}
DB_PORT=${DB_PORT:-5432}

# Never hardcode passwords in git. Prefer:
#   - DB_PASSWORD env var, or
#   - infer from backend/.env DATABASE_URL
DB_PASSWORD=${DB_PASSWORD:-}

cd "$(dirname "$0")/.."

if [[ -z "${DB_PASSWORD}" ]] && [[ -f .env ]]; then
  DB_PASSWORD=$(python3 - <<'PY'
import os
from pathlib import Path
from urllib.parse import urlparse

def parse_database_url(url: str) -> str:
    # supports postgresql+psycopg://user:pass@host:port/db
    u = urlparse(url)
    return u.password or ""

for line in Path('.env').read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        print(parse_database_url(line.split('=',1)[1].strip()))
        break
PY
)
fi

if [[ -z "${DB_PASSWORD}" ]]; then
  echo "ERROR: DB_PASSWORD not set and could not infer it from backend/.env DATABASE_URL" >&2
  echo "Set DB_PASSWORD=... or create backend/.env with DATABASE_URL" >&2
  exit 2
fi

export PGPASSWORD="$DB_PASSWORD"

# 1) wipe schema
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

# 2) migrate
. .venv/bin/activate
alembic upgrade head

# 3) seed
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
  -f scripts/seed_data.sql

echo "Reset complete: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
