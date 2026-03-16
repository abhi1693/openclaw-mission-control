"""Access control helpers for actor-type checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.core.auth import AuthContext


def require_user_actor(auth: AuthContext) -> None:
    """Raise HTTP 403 unless the authenticated actor is a human user (not an agent).

    NOTE: This is an actor-type check, NOT a privilege/role check.
    For admin privilege enforcement, use ``require_org_admin`` (organization-level)
    or check ``user.is_super_admin`` (global-level).
    """
    if auth.actor_type != "user" or auth.user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
