"""User authentication helpers for local-token auth mode.

This module resolves an authenticated *user* from inbound HTTP requests
using a single shared bearer token (LOCAL_AUTH_TOKEN).
"""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from typing import TYPE_CHECKING, Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import get_logger
from app.db import crud
from app.db.session import get_session
from app.models.users import User

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)
SECURITY_DEP = Depends(security)
SESSION_DEP = Depends(get_session)
LOCAL_AUTH_USER_ID = "local-auth-user"
LOCAL_AUTH_EMAIL = "admin@home.local"
LOCAL_AUTH_NAME = "Local User"


@dataclass
class AuthContext:
    """Authenticated user context resolved from inbound auth headers."""

    actor_type: Literal["user"]
    user: User | None = None


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract the bearer token from an `Authorization` header."""
    if not authorization:
        return None
    value = authorization.strip()
    if not value:
        return None
    if not value.lower().startswith("bearer "):
        return None
    token = value.split(" ", maxsplit=1)[1].strip()
    return token or None


async def _get_or_create_local_user(session: AsyncSession) -> User:
    defaults: dict[str, object] = {
        "email": LOCAL_AUTH_EMAIL,
        "name": LOCAL_AUTH_NAME,
    }
    user, _created = await crud.get_or_create(
        session,
        User,
        clerk_user_id=LOCAL_AUTH_USER_ID,
        defaults=defaults,
    )
    changed = False
    if not user.email:
        user.email = LOCAL_AUTH_EMAIL
        changed = True
    if not user.name:
        user.name = LOCAL_AUTH_NAME
        changed = True
    if changed:
        session.add(user)
        await session.commit()
        await session.refresh(user)

    from app.services.organizations import ensure_member_for_user

    await ensure_member_for_user(session, user)
    return user


async def _resolve_local_auth_context(
    *,
    request: Request,
    session: AsyncSession,
    required: bool,
) -> AuthContext | None:
    token = _extract_bearer_token(request.headers.get("Authorization"))
    if token is None:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return None
    expected = settings.local_auth_token.strip()
    if not expected or not compare_digest(token, expected):
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return None
    user = await _get_or_create_local_user(session)
    return AuthContext(actor_type="user", user=user)


async def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = SECURITY_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AuthContext:
    """Resolve required authenticated user context."""
    local_auth = await _resolve_local_auth_context(
        request=request,
        session=session,
        required=True,
    )
    if local_auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return local_auth


async def get_auth_context_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = SECURITY_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AuthContext | None:
    """Resolve user context if available, otherwise return `None`."""
    if request.headers.get("X-Agent-Token"):
        return None
    return await _resolve_local_auth_context(
        request=request,
        session=session,
        required=False,
    )
