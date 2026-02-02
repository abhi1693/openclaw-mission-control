#!/usr/bin/env bash
set -euo pipefail

DB_NAME=${DB_NAME:-openclaw_agency}
DB_USER=${DB_USER:-postgres}
DB_HOST=${DB_HOST:-127.0.0.1}
DB_PORT=${DB_PORT:-5432}
DB_PASSWORD=${DB_PASSWORD:-REDACTED}

cd "$(dirname "$0")/.."

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
