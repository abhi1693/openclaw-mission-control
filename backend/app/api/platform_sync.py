"""Platform Sync API - Receives agent updates from OpenClaw Core platform.

This module provides endpoints for syncing data from the main OpenClaw platform
to Mission Control. It's designed to be called by the platform's internal services
with the shared LOCAL_AUTH_TOKEN for authentication.

The sync happens server-to-server, not through the user proxy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import get_auth_context, AuthContext
from app.db.session import get_session
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.models.organizations import Organization

router = APIRouter(prefix="/platform", tags=["platform-sync"])


class PlatformAgentSync(BaseModel):
    """Agent data from the OpenClaw platform to sync to Mission Control."""

    platform_agent_id: str = Field(description="Agent ID from the platform")
    tenant_id: str = Field(description="Tenant ID from the platform")
    name: str = Field(description="Agent display name")
    status: str = Field(default="active", description="Agent status")
    agent_type_id: str | None = Field(default=None, description="Agent type ID")
    specialization: str | None = Field(default=None, description="Agent specialization")
    model: str | None = Field(default=None, description="LLM model used")
    capabilities: list[str] | None = Field(default=None, description="Agent capabilities")


class PlatformAgentSyncResponse(BaseModel):
    """Response from agent sync operation."""

    success: bool
    mission_control_agent_id: UUID
    created: bool
    message: str


async def get_or_create_platform_gateway(
    session: AsyncSession,
    organization_id: UUID,
) -> Gateway:
    """Get or create the platform sync gateway for an organization."""
    # Look for existing platform gateway
    statement = select(Gateway).where(
        Gateway.organization_id == organization_id,
        Gateway.name == "OpenClaw Platform",
    )
    result = await session.exec(statement)
    gateway = result.first()

    if gateway:
        return gateway

    # Create platform gateway
    gateway = Gateway(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenClaw Platform",
        url="internal://platform",
        workspace_root="/platform",
    )
    session.add(gateway)
    await session.commit()
    await session.refresh(gateway)
    return gateway


async def get_organization_by_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> Organization | None:
    """Find organization by platform tenant ID.

    Organizations can store their platform tenant_id in metadata.
    Falls back to finding the first organization if none matches.
    """
    # First, try to find org with matching tenant_id in metadata
    # For now, just get the first organization as a fallback
    statement = select(Organization).limit(1)
    result = await session.exec(statement)
    return result.first()


@router.post("/agents/sync", response_model=PlatformAgentSyncResponse)
async def sync_platform_agent(
    payload: PlatformAgentSync,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> PlatformAgentSyncResponse:
    """Sync an agent from the OpenClaw platform to Mission Control.

    This endpoint is called by the platform when agents are created, updated,
    or deleted. It maintains a mirror of platform agents in Mission Control
    so they appear in the /control/agents view.

    Authentication: Requires LOCAL_AUTH_TOKEN (same as other platform proxied requests).
    """
    # Find organization for this tenant
    org = await get_organization_by_tenant(session, payload.tenant_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No organization found for tenant {payload.tenant_id}",
        )

    # Get or create the platform gateway
    gateway = await get_or_create_platform_gateway(session, org.id)

    # Check if agent already exists (by platform_agent_id stored in openclaw_session_id)
    statement = select(Agent).where(
        Agent.gateway_id == gateway.id,
        Agent.openclaw_session_id == payload.platform_agent_id,
    )
    result = await session.exec(statement)
    existing_agent = result.first()

    if existing_agent:
        # Update existing agent
        existing_agent.name = payload.name
        existing_agent.status = payload.status
        existing_agent.identity_profile = {
            "platform_tenant_id": payload.tenant_id,
            "platform_agent_type_id": payload.agent_type_id,
            "specialization": payload.specialization,
            "model": payload.model,
            "capabilities": payload.capabilities,
            "synced_from": "openclaw_platform",
        }
        existing_agent.updated_at = datetime.utcnow()
        session.add(existing_agent)
        await session.commit()
        await session.refresh(existing_agent)

        return PlatformAgentSyncResponse(
            success=True,
            mission_control_agent_id=existing_agent.id,
            created=False,
            message="Agent updated",
        )

    # Create new agent
    agent = Agent(
        id=uuid4(),
        gateway_id=gateway.id,
        board_id=None,  # Platform agents don't belong to a specific board
        name=payload.name,
        status=payload.status,
        openclaw_session_id=payload.platform_agent_id,  # Store platform ID for lookups
        identity_profile={
            "platform_tenant_id": payload.tenant_id,
            "platform_agent_type_id": payload.agent_type_id,
            "specialization": payload.specialization,
            "model": payload.model,
            "capabilities": payload.capabilities,
            "synced_from": "openclaw_platform",
        },
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    return PlatformAgentSyncResponse(
        success=True,
        mission_control_agent_id=agent.id,
        created=True,
        message="Agent created",
    )


@router.delete("/agents/sync/{platform_agent_id}")
async def delete_synced_agent(
    platform_agent_id: str,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    """Remove a synced agent when it's deleted from the platform."""
    # Find agent by platform ID
    statement = select(Agent).where(Agent.openclaw_session_id == platform_agent_id)
    result = await session.exec(statement)
    agent = result.first()

    if not agent:
        return {"success": True, "message": "Agent not found (already deleted)"}

    await session.delete(agent)
    await session.commit()

    return {"success": True, "message": "Agent deleted"}
