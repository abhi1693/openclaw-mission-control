"""Authentication bootstrap endpoints for the Mission Control API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.errors import LLMErrorResponse
from app.schemas.users import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
AUTH_CONTEXT_DEP = Depends(get_auth_context)


@router.post(
    "/bootstrap",
    response_model=UserRead,
    summary="Bootstrap Authenticated User Context",
    description=(
        "Resolve caller identity from auth headers and return the canonical user profile. "
        "This endpoint does not accept a request body."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Authenticated user profile resolved from token claims.",
            "content": {
                "application/json": {
                    "example": {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "clerk_user_id": "user_2abcXYZ",
                        "email": "alex@example.com",
                        "name": "Alex Chen",
                        "preferred_name": "Alex",
                        "pronouns": "they/them",
                        "timezone": "America/Los_Angeles",
                        "notes": "Primary operator for board triage.",
                        "context": "Handles incident coordination and escalation.",
                        "is_super_admin": False,
                    }
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": LLMErrorResponse,
            "description": "Caller is not authenticated as a user actor.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {"code": "unauthorized", "message": "Not authenticated"},
                        "code": "unauthorized",
                        "retryable": False,
                    }
                }
            },
        },
    },
)
async def bootstrap_user(auth: AuthContext = AUTH_CONTEXT_DEP) -> UserRead:
    """Return the authenticated user profile from token claims."""
    if auth.actor_type != "user" or auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return UserRead.model_validate(auth.user)
