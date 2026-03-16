# ruff: noqa: INP001
"""Settings validation tests for auth-mode configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.auth_mode import AuthMode
from app.core.config import Settings

BASE_URL = "http://localhost:8000"


def test_local_mode_requires_non_empty_token() -> None:
    with pytest.raises(
        ValidationError,
        match="LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.LOCAL,
            local_auth_token="",
            base_url=BASE_URL,
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
            base_url=BASE_URL,
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
            base_url=BASE_URL,
        )


def test_local_mode_accepts_real_token() -> None:
    token = "a" * 50
    settings = Settings(
        _env_file=None,
        auth_mode=AuthMode.LOCAL,
        local_auth_token=token,
        base_url=BASE_URL,
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
            base_url=BASE_URL,
        )


def test_base_url_required() -> None:
    with pytest.raises(
        ValidationError,
        match="BASE_URL must be set and non-empty",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.CLERK,
            clerk_secret_key="sk_test",
            base_url="  ",
        )


def test_base_url_field_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            auth_mode=AuthMode.CLERK,
            clerk_secret_key="sk_test",
        )

    text = str(exc_info.value)
    assert "BASE_URL must be set and non-empty" in text


@pytest.mark.parametrize(
    "base_url",
    [
        "localhost:8000",
        "ws://localhost:8000",
    ],
)
def test_base_url_requires_absolute_http_url(base_url: str) -> None:
    with pytest.raises(
        ValidationError,
        match="BASE_URL must be an absolute http\\(s\\) URL",
    ):
        Settings(
            _env_file=None,
            auth_mode=AuthMode.CLERK,
            clerk_secret_key="sk_test",
            base_url=base_url,
        )


def test_base_url_is_normalized_without_trailing_slash() -> None:
    token = "a" * 50
    settings = Settings(
        _env_file=None,
        auth_mode=AuthMode.LOCAL,
        local_auth_token=token,
        base_url="http://localhost:8000/ ",
    )

    assert settings.base_url == BASE_URL
