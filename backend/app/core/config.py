"""Application settings and environment configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.auth_mode import AuthMode

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
LOCAL_AUTH_TOKEN_MIN_LENGTH = 50
LOCAL_AUTH_TOKEN_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "changeme",
        "replace-me",
        "replace-with-strong-random-token",
    },
)


class Settings(BaseSettings):
    """Typed runtime configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        # Load `backend/.env` regardless of current working directory.
        # (Important when running uvicorn from repo root or via a process manager.)
        env_file=[DEFAULT_ENV_FILE, ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/openclaw_agency"

    # Auth mode: "clerk" for Clerk JWT auth, "local" for shared bearer token auth.
    auth_mode: AuthMode
    local_auth_token: str = ""

    # Clerk auth (auth only; roles stored in DB)
    clerk_secret_key: str = ""
    clerk_api_url: str = "https://api.clerk.com"
    clerk_verify_iat: bool = True
    clerk_leeway: float = 10.0

    cors_origins: str = ""
    base_url: str = ""

    # GitHub integration
    # Token used for GitHub REST API calls (checks/status updates). Supports GH_TOKEN or GITHUB_TOKEN.
    github_token: str = Field(
        default="",
        validation_alias=AliasChoices("GH_TOKEN", "GITHUB_TOKEN"),
    )

    # Periodic reconciliation safety net for mission-control/approval checks.
    github_approval_check_schedule_id: str = "mission-control-approval-check-reconcile"
    github_approval_check_schedule_interval_seconds: int = 900

    # Database lifecycle
    db_auto_migrate: bool = False

    # Webhook queueing / dispatch
    webhook_redis_url: str = "redis://localhost:6379/0"
    webhook_queue_name: str = "webhook-dispatch"
    webhook_dispatch_schedule_id: str = "webhook-dispatch-batch"
    webhook_dispatch_throttle_seconds: float = 2.0
    webhook_dispatch_schedule_interval_seconds: int = 900
    webhook_dispatch_max_retries: int = 3

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"
    log_use_utc: bool = False
    request_log_slow_ms: int = Field(default=1000, ge=0)
    request_log_include_health: bool = False

    @model_validator(mode="after")
    def _defaults(self) -> Self:
        if self.auth_mode == AuthMode.CLERK:
            if not self.clerk_secret_key.strip():
                raise ValueError(
                    "CLERK_SECRET_KEY must be set and non-empty when AUTH_MODE=clerk.",
                )
        elif self.auth_mode == AuthMode.LOCAL:
            token = self.local_auth_token.strip()
            if (
                not token
                or len(token) < LOCAL_AUTH_TOKEN_MIN_LENGTH
                or token.lower() in LOCAL_AUTH_TOKEN_PLACEHOLDERS
            ):
                raise ValueError(
                    "LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local.",
                )
        # In dev, default to applying Alembic migrations at startup to avoid
        # schema drift (e.g. missing newly-added columns).
        if "db_auto_migrate" not in self.model_fields_set and self.environment == "dev":
            self.db_auto_migrate = True
        return self


settings = Settings()
