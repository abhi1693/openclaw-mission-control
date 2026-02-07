# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (keep minimal)
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install uv (https://github.com/astral-sh/uv)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# --- deps layer ---
FROM base AS deps

# Copy only dependency metadata first for better build caching
# NOTE: compose builds backend with repo-root context, so files live under /backend.
COPY backend/pyproject.toml backend/uv.lock ./

# Create venv and sync deps (including runtime)
RUN uv sync --frozen --no-dev

# --- runtime ---
FROM base AS runtime

# Copy virtual environment from deps stage
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

# Copy app source
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/app ./app

# Copy repo-level templates used by agent provisioning, etc.
# (backend code resolves these from repo root)
COPY templates ./templates

# Default API port
EXPOSE 8000

# Run the API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
