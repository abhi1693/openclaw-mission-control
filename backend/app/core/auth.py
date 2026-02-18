"""User authentication helpers for Clerk and local-token auth modes.

This module resolves an authenticated *user* from inbound HTTP requests.

Auth modes:
- `local`: a single shared bearer token (`LOCAL_AUTH_TOKEN`) for self-hosted
  deployments.
- `clerk`: Clerk JWT authentication for multi-user deployments.

The public surface area is the `get_auth_context*` dependencies, which return an
`AuthContext` used across API routers.

Notes:
- This file documents *why* some choices exist (e.g. claim extraction fallbacks)
  so maintainers can safely modify auth behavior later.
"""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from typing import TYPE_CHECKING, Literal

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.models.clerkerrors import ClerkErrors
from clerk_backend_api.models.sdkerror import SDKError
from clerk_backend_api.security.types import AuthenticateRequestOptions, AuthStatus, RequestState
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.auth_mode import AuthMode
from app.core.config import settings
from app.core.logging import get_logger
from app.db import crud
from app.db.session import get_session
from app.models.users import User

if TYPE_CHECKING:
    from clerk_backend_api.models.user import User as ClerkUser
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)
SECURITY_DEP = Depends(security)
SESSION_DEP = Depends(get_session)
LOCAL_AUTH_USER_ID = "local-auth-user"
LOCAL_AUTH_EMAIL = "admin@home.local"
LOCAL_AUTH_NAME = "Local User"


class ClerkTokenPayload(BaseModel):
    """JWT claims payload shape required from Clerk tokens."""

    sub: str


@dataclass
class AuthContext:
    """Authenticated user context resolved from inbound auth headers."""

    actor_type: Literal["user"]
    user: User | None = None


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract the bearer token from an `Authorization` header.

    Returns `None` for missing/empty headers or non-bearer schemes.

    Note: we do *not* validate the token here; this helper is only responsible for parsing.
    """

    if not authorization:
        return None
    value = authorization.strip()
    if not value:
        return None
    if not value.lower().startswith("bearer "):
        return None
    token = value.split(" ", maxsplit=1)[1].strip()
    return token or None


def _non_empty_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_email(value: object) -> str | None:
    text = _non_empty_str(value)
    if text is None:
        return None
    return text.lower()


def _extract_claim_email(claims: dict[str, object]) -> str | None:
    """Best-effort extraction of an email address from Clerk/JWT-like claims.

    Clerk payloads vary depending on token type and SDK version. We try common flat keys first,
    then fall back to an `email_addresses` list (either strings or dict-like entries).

    Returns a normalized lowercase email or `None`.
    """

    for key in ("email", "email_address", "primary_email_address"):
        email = _normalize_email(claims.get(key))
        if email:
            return email

    primary_email_id = _non_empty_str(claims.get("primary_email_address_id"))
    email_addresses = claims.get("email_addresses")
    if not isinstance(email_addresses, list):
        return None

    fallback_email: str | None = None
    for item in email_addresses:
        if isinstance(item, str):
            normalized = _normalize_email(item)
            if normalized and fallback_email is None:
                fallback_email = normalized
            continue
        if not isinstance(item, dict):
            continue
        candidate = _normalize_email(item.get("email_address") or item.get("email"))
        if not candidate:
            continue
        candidate_id = _non_empty_str(item.get("id"))
        if primary_email_id and candidate_id == primary_email_id:
            return candidate
        if fallback_email is None:
            fallback_email = candidate

    return fallback_email


def _extract_claim_name(claims: dict[str, object]) -> str | None:
    """Best-effort extraction of a display name from Clerk/JWT-like claims."""

    for key in ("name", "full_name"):
        text = _non_empty_str(claims.get(key))
        if text:
            return text

    first = _non_empty_str(claims.get("given_name")) or _non_empty_str(claims.get("first_name"))
    last = _non_empty_str(claims.get("family_name")) or _non_empty_str(claims.get("last_name"))
    parts = [part for part in (first, last) if part]
    if not parts:
        return None
    return " ".join(parts)


def _extract_clerk_profile(profile: ClerkUser | None) -> tuple[str | None, str | None]:
    """Extract `(email, name)` from a Clerk user profile.

    The Clerk SDK surface is not perfectly consistent across environments:
    - some fields may be absent,
    - email addresses may be represented as strings or objects,
    - the "primary" email may be identified by id.

    This helper implements a defensive, best-effort extraction strategy and returns `(None, None)`
    when the profile is unavailable.
    """

    if profile is None:
        return None, None

    profile_email = _normalize_email(getattr(profile, "email_address", None))
    primary_email_id = _non_empty_str(getattr(profile, "primary_email_address_id", None))
    emails = getattr(profile, "email_addresses", None)
    if not profile_email and isinstance(emails, list):
        fallback_email: str | None = None
        for item in emails:
            candidate = _normalize_email(
                getattr(item, "email_address", None),
            )
            if not candidate:
                continue
            candidate_id = _non_empty_str(getattr(item, "id", None))
            if primary_email_id and candidate_id == primary_email_id:
                profile_email = candidate
                break
            if fallback_email is None:
                fallback_email = candidate
        if profile_email is None:
            profile_email = fallback_email

    profile_name = (
        _non_empty_str(getattr(profile, "full_name", None))
        or _non_empty_str(getattr(profile, "name", None))
        or _non_empty_str(getattr(profile, "first_name", None))
        or _non_empty_str(getattr(profile, "username", None))
    )
    if not profile_name:
        first = _non_empty_str(getattr(profile, "first_name", None))
        last = _non_empty_str(getattr(profile, "last_name", None))
        parts = [part for part in (first, last) if part]
        if parts:
            profile_name = " ".join(parts)

    return profile_email, profile_name


def _normalize_clerk_server_url(raw: str) -> str | None:
    server_url = raw.strip().rstrip("/")
    if not server_url:
        return None
    if not server_url.endswith("/v1"):
        server_url = f"{server_url}/v1"
    return server_url


def _make_authenticate_request_options() -> AuthenticateRequestOptions:
    # Follow the clerk-backend-api documented flow: authenticate_request() with a secret key.
    return AuthenticateRequestOptions(
        secret_key=settings.clerk_secret_key.strip(),
        clock_skew_in_ms=int(settings.clerk_leeway * 1000),
        accepts_token=["session_token"],
    )


async def _authenticate_clerk_request(request: Request) -> RequestState:
    # The SDK docs use httpx.Request as the request object; build one from the ASGI request.
    httpx_request = httpx.Request(
        request.method,
        str(request.url),
        headers=dict(request.headers),
    )
    options = _make_authenticate_request_options()
    sdk = Clerk(bearer_auth=options.secret_key or "")
    return await run_in_threadpool(sdk.authenticate_request, httpx_request, options)


async def _fetch_clerk_profile(clerk_user_id: str) -> tuple[str | None, str | None]:
    secret = settings.clerk_secret_key.strip()
    secret_kind = secret.split("_", maxsplit=1)[0] if "_" in secret else "unknown"
    server_url = _normalize_clerk_server_url(settings.clerk_api_url or "")
    clerk_user_id_log = clerk_user_id[-6:] if clerk_user_id else ""

    try:
        async with Clerk(
            bearer_auth=secret,
            server_url=server_url,
            timeout_ms=5000,
        ) as clerk:
            profile = await clerk.users.get_async(user_id=clerk_user_id)
        email, name = _extract_clerk_profile(profile)
        return email, name
    except ClerkErrors as exc:
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s reason=clerk_errors "
            "secret_kind=%s error_type=%s",
            clerk_user_id_log,
            secret_kind,
            exc.__class__.__name__,
        )
    except SDKError as exc:
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s status=%s reason=sdk_error "
            "server_url=%s secret_kind=%s",
            clerk_user_id_log,
            exc.status_code,
            server_url,
            secret_kind,
        )
    except httpx.TimeoutException as exc:
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s reason=timeout "
            "server_url=%s secret_kind=%s error=%s",
            clerk_user_id_log,
            server_url,
            secret_kind,
            str(exc) or exc.__class__.__name__,
        )
    except Exception as exc:
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s reason=sdk_exception "
            "error_type=%s error=%s",
            clerk_user_id_log,
            exc.__class__.__name__,
            str(exc)[:300],
        )
    return None, None


async def delete_clerk_user(clerk_user_id: str) -> None:
    """Delete a Clerk user via the official Clerk SDK."""
    if settings.auth_mode != AuthMode.CLERK:
        return

    secret = settings.clerk_secret_key.strip()
    secret_kind = secret.split("_", maxsplit=1)[0] if "_" in secret else "unknown"
    server_url = _normalize_clerk_server_url(settings.clerk_api_url or "")
    clerk_user_id_log = clerk_user_id[-6:] if clerk_user_id else ""

    try:
        async with Clerk(
            bearer_auth=secret,
            server_url=server_url,
            timeout_ms=5000,
        ) as clerk:
            await clerk.users.delete_async(user_id=clerk_user_id)
        logger.info("auth.clerk.user.delete clerk_user_id=%s", clerk_user_id_log)
    except ClerkErrors as exc:
        logger.warning(
            "auth.clerk.user.delete_failed clerk_user_id=%s reason=clerk_errors "
            "secret_kind=%s error_type=%s",
            clerk_user_id_log,
            secret_kind,
            exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete account from Clerk",
        ) from exc
    except SDKError as exc:
        if exc.status_code == 404:
            logger.info("auth.clerk.user.delete_missing clerk_user_id=%s", clerk_user_id_log)
            return
        logger.warning(
            "auth.clerk.user.delete_failed clerk_user_id=%s status=%s reason=sdk_error "
            "server_url=%s secret_kind=%s",
            clerk_user_id_log,
            exc.status_code,
            server_url,
            secret_kind,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete account from Clerk",
        ) from exc
    except Exception as exc:
        logger.warning(
            "auth.clerk.user.delete_failed clerk_user_id=%s reason=sdk_exception",
            clerk_user_id_log,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete account from Clerk",
        ) from exc


async def _get_or_sync_user(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    claims: dict[str, object],
) -> User:
    clerk_user_id_log = clerk_user_id[-6:] if clerk_user_id else ""
    claim_email = _extract_claim_email(claims)
    claim_name = _extract_claim_name(claims)
    defaults: dict[str, object | None] = {
        "email": claim_email,
        "name": claim_name,
    }
    user, created = await crud.get_or_create(
        session,
        User,
        clerk_user_id=clerk_user_id,
        defaults=defaults,
    )

    profile_email: str | None = None
    profile_name: str | None = None
    # Avoid a network roundtrip to Clerk on every request once core profile
    # fields are present in our DB.
    should_fetch_profile = created or not user.email or not user.name
    if should_fetch_profile:
        profile_email, profile_name = await _fetch_clerk_profile(clerk_user_id)

    email = profile_email or claim_email
    name = profile_name or claim_name

    changed = False
    if email and user.email != email:
        user.email = email
        changed = True
    if not user.name and name:
        user.name = name
        changed = True
    if changed:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info(
            "auth.user.sync clerk_user_id=%s updated=%s fetched_profile=%s",
            clerk_user_id_log,
            changed,
            should_fetch_profile,
        )
    else:
        logger.debug(
            "auth.user.sync.noop clerk_user_id=%s fetched_profile=%s",
            clerk_user_id_log,
            should_fetch_profile,
        )
    if not user.email:
        logger.warning(
            "auth.user.sync.missing_email clerk_user_id=%s",
            clerk_user_id_log,
        )
    return user


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


def _parse_subject(claims: dict[str, object]) -> str | None:
    payload = ClerkTokenPayload.model_validate(claims)
    return payload.sub


async def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = SECURITY_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AuthContext:
    """Resolve required authenticated user context for the configured auth mode."""
    if settings.auth_mode == AuthMode.LOCAL:
        local_auth = await _resolve_local_auth_context(
            request=request,
            session=session,
            required=True,
        )
        if local_auth is None:  # pragma: no cover
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return local_auth

    request_state = await _authenticate_clerk_request(request)
    if request_state.status != AuthStatus.SIGNED_IN or not isinstance(request_state.payload, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    claims: dict[str, object] = {str(k): v for k, v in request_state.payload.items()}
    try:
        clerk_user_id = _parse_subject(claims)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc

    if not clerk_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = await _get_or_sync_user(
        session,
        clerk_user_id=clerk_user_id,
        claims=claims,
    )
    from app.services.organizations import ensure_member_for_user

    await ensure_member_for_user(session, user)

    return AuthContext(
        actor_type="user",
        user=user,
    )


async def get_auth_context_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = SECURITY_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AuthContext | None:
    """Resolve user context if available, otherwise return `None`."""
    if request.headers.get("X-Agent-Token"):
        return None
    if settings.auth_mode == AuthMode.LOCAL:
        return await _resolve_local_auth_context(
            request=request,
            session=session,
            required=False,
        )

    request_state = await _authenticate_clerk_request(request)
    if request_state.status != AuthStatus.SIGNED_IN or not isinstance(request_state.payload, dict):
        return None
    claims: dict[str, object] = {str(k): v for k, v in request_state.payload.items()}

    try:
        clerk_user_id = _parse_subject(claims)
    except ValidationError:
        return None

    if not clerk_user_id:
        return None
    user = await _get_or_sync_user(
        session,
        clerk_user_id=clerk_user_id,
        claims=claims,
    )
    from app.services.organizations import ensure_member_for_user

    await ensure_member_for_user(session, user)

    return AuthContext(
        actor_type="user",
        user=user,
    )
