"""Shared auth-mode enum values."""

from __future__ import annotations

from enum import Enum


class AuthMode(str, Enum):
    """Supported authentication mode for backend."""

    LOCAL = "local"
