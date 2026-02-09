"""User authentication helpers backed by Clerk JWT verification."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Literal

import jwt
from clerk_backend_api import Clerk
from clerk_backend_api.models.clerkerrors import ClerkErrors
from clerk_backend_api.models.sdkerror import SDKError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.db import crud
from app.db.session import get_session
from app.models.users import User

if TYPE_CHECKING:
    from clerk_backend_api.models.user import User as ClerkUser
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)
SECURITY_DEP = Depends(security)
SESSION_DEP = Depends(get_session)
_JWKS_CACHE_TTL_SECONDS = 300.0
_jwks_cache_payload: dict[str, object] | None = None
_jwks_cache_at_monotonic = 0.0


class ClerkTokenPayload(BaseModel):
    """JWT claims payload shape required from Clerk tokens."""

    sub: str


@dataclass
class AuthContext:
    """Authenticated user context resolved from inbound auth headers."""

    actor_type: Literal["user"]
    user: User | None = None


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


def _claim_debug_snapshot(claims: dict[str, object]) -> dict[str, object]:
    email_addresses = claims.get("email_addresses")
    email_samples: list[dict[str, str | None]] = []
    if isinstance(email_addresses, list):
        for item in email_addresses[:5]:
            if isinstance(item, dict):
                email_samples.append(
                    {
                        "id": _non_empty_str(item.get("id")),
                        "email": _normalize_email(
                            item.get("email_address") or item.get("email"),
                        ),
                    },
                )
            elif isinstance(item, str):
                email_samples.append({"id": None, "email": _normalize_email(item)})

    return {
        "keys": sorted(claims.keys()),
        "iss": _non_empty_str(claims.get("iss")),
        "sub": _non_empty_str(claims.get("sub")),
        "email": _normalize_email(claims.get("email")),
        "email_address": _normalize_email(claims.get("email_address")),
        "primary_email_address": _normalize_email(claims.get("primary_email_address")),
        "primary_email_address_id": _non_empty_str(claims.get("primary_email_address_id")),
        "email_addresses_count": len(email_addresses) if isinstance(email_addresses, list) else 0,
        "email_addresses_sample": email_samples,
        "name": _non_empty_str(claims.get("name")),
        "full_name": _non_empty_str(claims.get("full_name")),
        "given_name": _non_empty_str(claims.get("given_name"))
        or _non_empty_str(claims.get("first_name")),
        "family_name": _non_empty_str(claims.get("family_name"))
        or _non_empty_str(claims.get("last_name")),
    }


def _extract_clerk_profile(profile: ClerkUser | None) -> tuple[str | None, str | None]:
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


async def _fetch_clerk_jwks(*, force_refresh: bool = False) -> dict[str, object]:
    global _jwks_cache_payload
    global _jwks_cache_at_monotonic

    if (
        not force_refresh
        and _jwks_cache_payload is not None
        and monotonic() - _jwks_cache_at_monotonic < _JWKS_CACHE_TTL_SECONDS
    ):
        return _jwks_cache_payload

    secret = settings.clerk_secret_key.strip()
    server_url = _normalize_clerk_server_url(settings.clerk_api_url or "")
    async with Clerk(
        bearer_auth=secret,
        server_url=server_url,
        timeout_ms=5000,
    ) as clerk:
        jwks = await clerk.jwks.get_async()
    if jwks is None:
        raise RuntimeError("Clerk JWKS response was empty.")
    payload = jwks.model_dump()
    if not isinstance(payload, dict):
        raise RuntimeError("Clerk JWKS response had invalid shape.")
    _jwks_cache_payload = payload
    _jwks_cache_at_monotonic = monotonic()
    return payload


def _public_key_for_kid(jwks_payload: dict[str, object], kid: str) -> jwt.PyJWK | None:
    try:
        jwk_set = jwt.PyJWKSet.from_dict(jwks_payload)
    except jwt.PyJWTError:
        return None
    for key in jwk_set.keys:
        if key.key_id == kid:
            return key
    return None


async def _decode_clerk_token(token: str) -> dict[str, object]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc

    kid = _non_empty_str(header.get("kid"))
    if kid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    secret_kind = settings.clerk_secret_key.strip().split("_", maxsplit=1)[0]
    for attempt in (False, True):
        try:
            jwks_payload = await _fetch_clerk_jwks(force_refresh=attempt)
        except (ClerkErrors, SDKError, RuntimeError):
            logger.warning(
                "auth.clerk.jwks.fetch_failed attempt=%s secret_kind=%s",
                2 if attempt else 1,
                secret_kind,
                exc_info=True,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None

        key = _public_key_for_kid(jwks_payload, kid)
        if key is None:
            if attempt:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
            continue
        try:
            decoded = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                options={
                    "verify_aud": False,
                    "verify_iat": settings.clerk_verify_iat,
                },
                leeway=settings.clerk_leeway,
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
        if not isinstance(decoded, dict):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return {str(k): v for k, v in decoded.items()}

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


async def _fetch_clerk_profile(clerk_user_id: str) -> tuple[str | None, str | None]:
    secret = settings.clerk_secret_key.strip()
    secret_kind = secret.split("_", maxsplit=1)[0] if "_" in secret else "unknown"
    server_url = _normalize_clerk_server_url(settings.clerk_api_url or "")

    try:
        async with Clerk(
            bearer_auth=secret,
            server_url=server_url,
            timeout_ms=5000,
        ) as clerk:
            profile = await clerk.users.get_async(user_id=clerk_user_id)
        email, name = _extract_clerk_profile(profile)
        logger.info(
            "auth.clerk.profile.fetch clerk_user_id=%s email=%s name=%s",
            clerk_user_id,
            email,
            name,
        )
        return email, name
    except ClerkErrors as exc:
        errors_payload = str(exc)
        if len(errors_payload) > 300:
            errors_payload = f"{errors_payload[:300]}..."
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s reason=clerk_errors "
            "secret_kind=%s body=%s",
            clerk_user_id,
            secret_kind,
            errors_payload,
        )
    except SDKError as exc:
        response_body = exc.body.strip() or None
        if response_body and len(response_body) > 300:
            response_body = f"{response_body[:300]}..."
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s status=%s reason=sdk_error "
            "server_url=%s secret_kind=%s body=%s",
            clerk_user_id,
            exc.status_code,
            server_url,
            secret_kind,
            response_body,
        )
    except Exception:
        logger.warning(
            "auth.clerk.profile.fetch_failed clerk_user_id=%s reason=sdk_exception",
            clerk_user_id,
            exc_info=True,
        )
    return None, None


async def delete_clerk_user(clerk_user_id: str) -> None:
    """Delete a Clerk user via the official Clerk SDK."""
    secret = settings.clerk_secret_key.strip()
    secret_kind = secret.split("_", maxsplit=1)[0] if "_" in secret else "unknown"
    server_url = _normalize_clerk_server_url(settings.clerk_api_url or "")

    try:
        async with Clerk(
            bearer_auth=secret,
            server_url=server_url,
            timeout_ms=5000,
        ) as clerk:
            await clerk.users.delete_async(user_id=clerk_user_id)
        logger.info("auth.clerk.user.delete clerk_user_id=%s", clerk_user_id)
    except ClerkErrors as exc:
        errors_payload = str(exc)
        if len(errors_payload) > 300:
            errors_payload = f"{errors_payload[:300]}..."
        logger.warning(
            "auth.clerk.user.delete_failed clerk_user_id=%s reason=clerk_errors "
            "secret_kind=%s body=%s",
            clerk_user_id,
            secret_kind,
            errors_payload,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete account from Clerk",
        ) from exc
    except SDKError as exc:
        if exc.status_code == 404:
            logger.info("auth.clerk.user.delete_missing clerk_user_id=%s", clerk_user_id)
            return
        response_body = exc.body.strip() or None
        if response_body and len(response_body) > 300:
            response_body = f"{response_body[:300]}..."
        logger.warning(
            "auth.clerk.user.delete_failed clerk_user_id=%s status=%s reason=sdk_error "
            "server_url=%s secret_kind=%s body=%s",
            clerk_user_id,
            exc.status_code,
            server_url,
            secret_kind,
            response_body,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete account from Clerk",
        ) from exc
    except Exception as exc:
        logger.warning(
            "auth.clerk.user.delete_failed clerk_user_id=%s reason=sdk_exception",
            clerk_user_id,
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
    email, name = await _fetch_clerk_profile(clerk_user_id)
    logger.info(
        "auth.claims.parsed clerk_user_id=%s extracted_email=%s extracted_name=%s claims=%s",
        clerk_user_id,
        email,
        name,
        _claim_debug_snapshot(claims),
    )
    defaults: dict[str, object | None] = {
        "email": email,
        "name": name,
    }
    user, _created = await crud.get_or_create(
        session,
        User,
        clerk_user_id=clerk_user_id,
        defaults=defaults,
    )

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
        "auth.user.sync clerk_user_id=%s updated=%s claim_email=%s final_email=%s",
        clerk_user_id,
        changed,
        _normalize_email(defaults.get("email")),
        _normalize_email(user.email),
    )
    if not user.email:
        logger.warning(
            "auth.user.sync.missing_email clerk_user_id=%s claims=%s",
            clerk_user_id,
            _claim_debug_snapshot(claims),
        )
    return user


def _parse_subject(claims: dict[str, object]) -> str | None:
    payload = ClerkTokenPayload.model_validate(claims)
    return payload.sub


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = SECURITY_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AuthContext:
    """Resolve required authenticated user context from Clerk JWT headers."""
    # LOCAL BEARER: Simple token auth for self-hosted deployments
    if settings.auth_mode == "local_bearer" and settings.local_auth_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token == settings.local_auth_token:
                return AuthContext(actor_type="user", user=None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # DISABLED: No authentication for local development
    if settings.auth_mode == "disabled":
        return AuthContext(actor_type="user", user=None)

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    claims = await _decode_clerk_token(credentials.credentials)
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
    # Allow X-Agent-Token to pass through for agent-based auth
    if request.headers.get("X-Agent-Token"):
        return None

    # LOCAL BEARER: Simple token auth for self-hosted deployments
    # Only enforce if Authorization header is present (don't block X-Agent-Token)
    if settings.auth_mode == "local_bearer" and settings.local_auth_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token == settings.local_auth_token:
                return AuthContext(actor_type="user", user=None)
            # Invalid token - return None to let other auth methods try
            return None
        # No Authorization header - return None to let other auth methods try
        return None

    # DISABLED: No authentication for local development
    if settings.auth_mode == "disabled":
        return AuthContext(actor_type="user", user=None)

    if credentials is None:
        return None

    try:
        claims = await _decode_clerk_token(credentials.credentials)
    except HTTPException:
        return None

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
