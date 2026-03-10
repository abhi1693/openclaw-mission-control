# syntax=docker/dockerfile:1
# Inherits the full backend image and overrides the entrypoint to run the RQ worker.
# Build context must be the repo root (same as backend).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

FROM base AS deps

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

FROM base AS runtime

COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/app ./app
COPY backend/templates ./templates

# Use shell form so $RQ_REDIS_URL is expanded at runtime
CMD rq worker --url ${RQ_REDIS_URL:-redis://localhost:6379/0}
