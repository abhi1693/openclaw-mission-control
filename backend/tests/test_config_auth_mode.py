# ruff: noqa: INP001
"""Settings validation tests for auth-mode configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.auth_mode import AuthMode
from app.core.config import Settings


def test_local_mode_requires_non_empty_token() -> None:
    with pytest.raises(
        ValidationError,
        match="LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.LOCAL,
            local_auth_token="",
        )


def test_local_mode_requires_minimum_length() -> None:
    with pytest.raises(
        ValidationError,
        match="LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.LOCAL,
            local_auth_token="x" * 49,
        )


def test_local_mode_rejects_placeholder_token() -> None:
    with pytest.raises(
        ValidationError,
        match="LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.LOCAL,
            local_auth_token="change-me",
        )


def test_local_mode_accepts_real_token() -> None:
    token = "a" * 50
    settings = Settings(
        _env_file=None,
        auth_mode=AuthMode.LOCAL,
        local_auth_token=token,
    )

    assert settings.auth_mode == AuthMode.LOCAL
    assert settings.local_auth_token == token


def test_clerk_mode_requires_secret_key() -> None:
    with pytest.raises(
        ValidationError,
        match="CLERK_SECRET_KEY must be set and non-empty when AUTH_MODE=clerk",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.CLERK,
            clerk_secret_key="",
        )
