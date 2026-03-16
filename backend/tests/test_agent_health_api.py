from __future__ import annotations

from uuid import UUID, uuid4

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent


def _agent_ctx(*, board_id: UUID | None, status: str, is_board_lead: bool) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Health Probe Agent",
            status=status,
            is_board_lead=is_board_lead,
        ),
    )


def test_agent_healthz_returns_authenticated_agent_context() -> None:
    agent_ctx = _agent_ctx(board_id=uuid4(), status="online", is_board_lead=True)

    response = agent_api.agent_healthz(agent_ctx=agent_ctx)

    assert response.ok is True
    assert response.agent_id == agent_ctx.agent.id
    assert response.board_id == agent_ctx.agent.board_id
    assert response.gateway_id == agent_ctx.agent.gateway_id
    assert response.status == "online"
    assert response.is_board_lead is True
