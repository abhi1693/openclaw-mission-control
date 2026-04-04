"""FastAPI router for gateway-level model profile defaults.

Endpoints:
  GET   /api/v1/gateways/{gateway_id}/model-profile-defaults
  PATCH /api/v1/gateways/{gateway_id}/model-profile-defaults

Auth: require_user_or_agent (dual-auth — admin UI + agent callers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ActorContext, authorize_gateway_access, require_user_or_agent
from app.db.session import get_session
from app.schemas.gateway_model_profiles import (
    GatewayModelProfileDefaultsRead,
    PatchGatewayModelProfileDefaultsRequest,
)
from app.services.gateway_model_profiles import GatewayModelProfileService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(
    prefix="/gateways",
    tags=["gateway-model-profiles"],
)

SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_user_or_agent)


@router.get(
    "/{gateway_id}/model-profile-defaults",
    response_model=GatewayModelProfileDefaultsRead,
    summary="Get gateway model profile defaults",
    description=(
        "Return the current model profile defaults for a gateway. "
        "Returns unset/empty defaults if no profiles have been configured yet."
    ),
    tags=["gateway-model-profiles"],
    responses={
        200: {"description": "Current profile defaults."},
        401: {"description": "Unauthorized."},
    },
)
async def get_model_profile_defaults(
    gateway_id: UUID,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> GatewayModelProfileDefaultsRead:
    await authorize_gateway_access(gateway_id, session, actor)
    svc = GatewayModelProfileService(session)
    return await svc.get_defaults(gateway_id)


@router.patch(
    "/{gateway_id}/model-profile-defaults",
    response_model=GatewayModelProfileDefaultsRead,
    summary="Update gateway model profile defaults",
    description=(
        "Set or clear model profile defaults for a gateway. "
        "Each profile field accepts a concrete catalog model_id, "
        "the 'default' sentinel, or null to clear. "
        "Returns the updated full profile defaults."
    ),
    tags=["gateway-model-profiles"],
    responses={
        200: {"description": "Updated profile defaults."},
        400: {"description": "Invalid model_id."},
        401: {"description": "Unauthorized."},
    },
)
async def patch_model_profile_defaults(
    gateway_id: UUID,
    payload: PatchGatewayModelProfileDefaultsRequest,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> GatewayModelProfileDefaultsRead:
    await authorize_gateway_access(gateway_id, session, actor)
    svc = GatewayModelProfileService(session)
    try:
        return await svc.patch_defaults(gateway_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
