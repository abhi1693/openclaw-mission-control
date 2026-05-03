"""Tests for ``GET /api/v1/gateways/projected-sessions``.

Reads the ``gateway_session_state`` projection table populated by the
``mc_gateway_subscriber`` worker. Operator-scoped (``require_org_admin``)
AND scoped at query time to the caller's organization via the
``Agent → Gateway → Organization`` join — codex review of slice 4c
flagged the original implementation as a cross-org leak (returned
ALL rows when no agent_id was passed). These tests pin the org-scoping
contract so it cannot regress.

Tests invoke the route handler directly against a sqlite session — auth
itself is exercised by ``test_openclaw_runtime_status.py``; a duplicate
full-stack test would only re-prove FastAPI dependency resolution.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.gateway import projected_gateway_sessions
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.services.mc_gateway_subscriber.session_state_projector import SessionState
from app.services.mc_gateway_subscriber.session_state_repo import SessionStateRepo
from app.services.organizations import OrganizationContext


# ---------------------------------------------------------------------------
# Fixture: seeded caller organization with one paired gateway and an
# OrganizationContext to feed the handler's ORG_ADMIN_DEP slot.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def caller_org_ctx(
    sqlite_session: AsyncSession,
) -> AsyncIterator[OrganizationContext]:
    org = Organization(name="caller-org")
    sqlite_session.add(org)
    await sqlite_session.flush()
    gateway = Gateway(
        organization_id=org.id,
        name="caller-gateway",
        url="ws://x",
        workspace_root="/tmp",
    )
    sqlite_session.add(gateway)
    await sqlite_session.flush()
    member = OrganizationMember(
        organization_id=org.id,
        user_id=uuid4(),
        role="admin",
    )
    sqlite_session.add(member)
    await sqlite_session.commit()
    yield OrganizationContext(organization=org, member=member)


async def _seed_org_agent(
    session: AsyncSession,
    *,
    org_ctx: OrganizationContext,
    agent_id: str = "mc-aaaaaaaa-1111-2222-3333-444444444444",
) -> None:
    """Create an MC ``agents`` row whose ``openclaw_session_id`` resolves
    to the gateway's projected ``agent_id`` via ``agent_key()``. The
    handler scopes by joining agents to the org's gateway, so the agent
    must live under that gateway."""
    gateway = (
        await session.exec(
            __import__("sqlalchemy").select(Gateway).where(  # type: ignore[attr-defined]
                Gateway.organization_id == org_ctx.organization.id
            )
        )
    ).scalars().first()
    assert gateway is not None
    session.add(
        Agent(
            gateway_id=gateway.id,
            name=agent_id,
            openclaw_session_id=f"agent:{agent_id}:main",
        )
    )
    await session.commit()


def _state(
    *,
    agent_id: str = "mc-aaaaaaaa-1111-2222-3333-444444444444",
    session_label: str = "main",
    last_changed_at_ms: int = 1_777_823_446_849,
    last_phase: str | None = "message",
    total_tokens: int | None = 64_667,
    aborted_last_run: bool = False,
) -> SessionState:
    return SessionState(
        agent_id=agent_id,
        session_label=session_label,
        session_id="062b709b-540e-430b-b451-d48f4acff7b9",
        last_phase=last_phase,
        last_message_seq=158,
        last_changed_at_ms=last_changed_at_ms,
        input_tokens=49_931,
        output_tokens=14_736,
        total_tokens=total_tokens,
        channel="webchat",
        aborted_last_run=aborted_last_run,
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projected_sessions_empty_when_no_org_agents(
    sqlite_session: AsyncSession,
    caller_org_ctx: OrganizationContext,
) -> None:
    """Org has no MC agents — endpoint must return empty even if the
    projection table has rows for some other org's agents."""
    await SessionStateRepo.upsert(
        sqlite_session,
        _state(agent_id="mc-stranger-1111-2222-3333-444444444444"),
    )
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=None, session=sqlite_session, ctx=caller_org_ctx
    )
    assert response.sessions == []


@pytest.mark.asyncio
async def test_projected_sessions_returns_org_scoped_rows(
    sqlite_session: AsyncSession,
    caller_org_ctx: OrganizationContext,
) -> None:
    a_id = "mc-aaaaaaaa-1111-2222-3333-444444444444"
    b_id = "mc-bbbbbbbb-1111-2222-3333-444444444444"
    await _seed_org_agent(sqlite_session, org_ctx=caller_org_ctx, agent_id=a_id)
    await _seed_org_agent(sqlite_session, org_ctx=caller_org_ctx, agent_id=b_id)
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id))
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=b_id))
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=None, session=sqlite_session, ctx=caller_org_ctx
    )
    assert {s.agent_id for s in response.sessions} == {a_id, b_id}


@pytest.mark.asyncio
async def test_projected_sessions_excludes_other_orgs(
    sqlite_session: AsyncSession,
    caller_org_ctx: OrganizationContext,
) -> None:
    """The original /projected-sessions implementation called list_all
    with no org filter — codex flagged this as a cross-org leak. The
    fix joins the projection through the caller's gateway. Verify that
    rows for an OTHER org's agent are NOT returned."""
    # Caller's org agent + row.
    a_id = "mc-aaaaaaaa-1111-2222-3333-444444444444"
    await _seed_org_agent(sqlite_session, org_ctx=caller_org_ctx, agent_id=a_id)
    await SessionStateRepo.upsert(sqlite_session, _state(agent_id=a_id))

    # Other org's gateway + agent + row — same projection table.
    other_org = Organization(name="other-org")
    sqlite_session.add(other_org)
    await sqlite_session.flush()
    other_gateway = Gateway(
        organization_id=other_org.id,
        name="other-gateway",
        url="ws://y",
        workspace_root="/tmp",
    )
    sqlite_session.add(other_gateway)
    await sqlite_session.flush()
    other_agent_id = "mc-cccccccc-1111-2222-3333-444444444444"
    sqlite_session.add(
        Agent(
            gateway_id=other_gateway.id,
            name=other_agent_id,
            openclaw_session_id=f"agent:{other_agent_id}:main",
        )
    )
    await SessionStateRepo.upsert(
        sqlite_session, _state(agent_id=other_agent_id)
    )
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=None, session=sqlite_session, ctx=caller_org_ctx
    )
    assert {s.agent_id for s in response.sessions} == {a_id}, (
        f"cross-org leak: {[s.agent_id for s in response.sessions]}"
    )


@pytest.mark.asyncio
async def test_projected_sessions_agent_id_filter_cannot_widen_across_orgs(
    sqlite_session: AsyncSession,
    caller_org_ctx: OrganizationContext,
) -> None:
    """Caller passes ?agent_id pointing at another org's agent. Filter
    is intersected with the caller's-org agent set so the result is
    empty, NOT the other org's row."""
    other_org = Organization(name="other-org")
    sqlite_session.add(other_org)
    await sqlite_session.flush()
    other_gateway = Gateway(
        organization_id=other_org.id,
        name="other-gateway",
        url="ws://y",
        workspace_root="/tmp",
    )
    sqlite_session.add(other_gateway)
    await sqlite_session.flush()
    other_agent_id = "mc-cccccccc-1111-2222-3333-444444444444"
    sqlite_session.add(
        Agent(
            gateway_id=other_gateway.id,
            name=other_agent_id,
            openclaw_session_id=f"agent:{other_agent_id}:main",
        )
    )
    await SessionStateRepo.upsert(
        sqlite_session, _state(agent_id=other_agent_id)
    )
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=other_agent_id,
        session=sqlite_session,
        ctx=caller_org_ctx,
    )
    assert response.sessions == []


@pytest.mark.asyncio
async def test_projected_sessions_excludes_gateway_internal_rows(
    sqlite_session: AsyncSession,
    caller_org_ctx: OrganizationContext,
) -> None:
    """Gateway-internal rows (mc-gateway-*) and lead-namespace rows
    (lead-*) have no MC agents binding so the org-scoping naturally
    drops them. Pinned because surfacing them would require a
    different operator-internal scope."""
    await SessionStateRepo.upsert(
        sqlite_session,
        _state(agent_id="mc-gateway-3821a85a-984c-412a-9340-cda50eaf174e"),
    )
    await SessionStateRepo.upsert(
        sqlite_session,
        _state(agent_id="lead-some-board-uuid"),
    )
    await sqlite_session.commit()

    response = await projected_gateway_sessions(
        agent_id=None, session=sqlite_session, ctx=caller_org_ctx
    )
    assert response.sessions == []
