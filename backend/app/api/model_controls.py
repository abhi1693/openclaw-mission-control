"""FastAPI router for per-agent model assignment, fallback override, and recommendation regeneration.

Auth: uses `require_user_or_agent` — the same dual-auth dependency used by other
Mission Control routes that serve both the admin UI (human user token via
LOCAL_AUTH_TOKEN / Clerk) and agent callers (agent-token auth). This ensures
the same endpoints work from the Mission Control web UI and from agent API calls.

All write endpoints return the full aggregate assignment payload, matching
the GET response shape so clients never need a follow-up read.

Routes:
  GET  /api/v1/mission-control/agents/{agent_id}/model-assignment
  PATCH /api/v1/mission-control/agents/{agent_id}/model-assignment/primary
  PUT  /api/v1/mission-control/agents/{agent_id}/model-assignment/fallback-override
  POST /api/v1/mission-control/agents/{agent_id}/model-assignment/recommendation:regenerate
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ActorContext, authorize_agent_access, require_user_or_agent
from app.db.session import get_session
from app.schemas.model_controls import (
    AgentModelAssignmentRead,
    ModelCatalogResponse,
    PatchPrimaryRequest,
    PutFallbackOverrideRequest,
    RegenerateRecommendationRequest,
)
from app.services.model_controls import AgentModelAssignmentService, get_model_catalog

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(
    prefix="/mission-control/agents",
    tags=["model-controls"],
)

SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_user_or_agent)


# ---------------------------------------------------------------------------
# Model catalog endpoint (not agent-scoped)
# ---------------------------------------------------------------------------


@router.get(
    "/model-catalog",
    response_model=ModelCatalogResponse,
    summary="Get dynamic model catalog",
    description=(
        "Return the available model catalog, optionally filtered by role_fit, "
        "capability_class, supports_primary, or supports_fallback. "
        "Only active models are returned. "
        "Clients should cache this response with a short TTL (30-60s) and "
        "refresh on manual user action."
    ),
    tags=["model-controls"],
    responses={
        200: {"description": "Filtered model catalog."},
        401: {"description": "Unauthorized."},
    },
)
async def get_catalog(
    role_fit: str | None = None,
    capability_class: str | None = None,
    supports_primary: bool | None = None,
    supports_fallback: bool | None = None,
    gateway_id: UUID | None = None,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> ModelCatalogResponse:
    entries = await get_model_catalog(
        session,
        gateway_id=gateway_id,
        role_fit=role_fit,
        capability_class=capability_class,
        supports_primary=supports_primary,
        supports_fallback=supports_fallback,
    )
    filters: dict[str, str | bool] = {}
    if role_fit:
        filters["role_fit"] = role_fit
    if capability_class:
        filters["capability_class"] = capability_class
    if supports_primary is not None:
        filters["supports_primary"] = supports_primary
    if supports_fallback is not None:
        filters["supports_fallback"] = supports_fallback
    return ModelCatalogResponse(
        models=entries,
        total=len(entries),
        filters_applied=filters,
    )


@router.get(
    "/{agent_id}/model-assignment",
    response_model=AgentModelAssignmentRead,
    summary="Get model assignment for an agent",
    description=(
        "Return the full aggregate model assignment payload for a single agent, "
        "including primary selection, fallback policy, recommendation metadata, "
        "and validation state. Bootstraps a pending profile if none exists yet."
    ),
    tags=["model-controls"],
    responses={
        200: {"description": "Aggregate assignment payload."},
        401: {"description": "Unauthorized."},
    },
)
async def get_model_assignment(
    agent_id: UUID,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentModelAssignmentRead:
    await authorize_agent_access(agent_id, session, actor)
    svc = AgentModelAssignmentService(session)
    return await svc.get_assignment(agent_id)


@router.patch(
    "/{agent_id}/model-assignment/primary",
    response_model=AgentModelAssignmentRead,
    summary="Set or clear manual primary model",
    description=(
        "Set a manual primary model for an agent or switch back to auto (recommendation-backed). "
        "Does not overwrite recommendation state. "
        "Returns the updated aggregate assignment payload."
    ),
    tags=["model-controls"],
    responses={
        200: {"description": "Updated aggregate assignment payload."},
        400: {"description": "Invalid request — e.g. model_id missing when mode=manual."},
        401: {"description": "Unauthorized."},
    },
)
async def patch_primary(
    agent_id: UUID,
    payload: PatchPrimaryRequest,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentModelAssignmentRead:
    await authorize_agent_access(agent_id, session, actor)
    svc = AgentModelAssignmentService(session)
    try:
        return await svc.patch_primary(agent_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put(
    "/{agent_id}/model-assignment/fallback-override",
    response_model=AgentModelAssignmentRead,
    summary="Replace manual fallback override list",
    description=(
        "Full-list replacement for the manual fallback entries of an agent. "
        "The supplied entries list atomically replaces all previously stored manual entries. "
        "Set override_mode=none with an empty entries list to revert to generated-only fallback. "
        "Returns the updated aggregate assignment payload."
    ),
    tags=["model-controls"],
    responses={
        200: {"description": "Updated aggregate assignment payload."},
        400: {"description": "Invalid request."},
        401: {"description": "Unauthorized."},
    },
)
async def put_fallback_override(
    agent_id: UUID,
    payload: PutFallbackOverrideRequest,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentModelAssignmentRead:
    await authorize_agent_access(agent_id, session, actor)
    svc = AgentModelAssignmentService(session)
    try:
        return await svc.put_fallback_override(agent_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{agent_id}/model-assignment/recommendation:regenerate",
    response_model=AgentModelAssignmentRead,
    summary="Regenerate recommendation for an agent",
    description=(
        "Recompute the recommended primary model and generated fallback policy for an agent. "
        "Does not overwrite valid admin manual overrides. "
        "Appends a recommendation run history record. "
        "Returns the updated aggregate assignment payload."
    ),
    tags=["model-controls"],
    responses={
        200: {"description": "Updated aggregate assignment payload."},
        401: {"description": "Unauthorized."},
    },
)
async def regenerate_recommendation(
    agent_id: UUID,
    payload: RegenerateRecommendationRequest,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentModelAssignmentRead:
    await authorize_agent_access(agent_id, session, actor)
    svc = AgentModelAssignmentService(session)
    return await svc.regenerate_recommendation(agent_id, payload)
