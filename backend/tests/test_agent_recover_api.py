from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.boards import Board


def _agent_ctx(*, board_id: UUID, is_board_lead: bool) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Supervisor",
            is_board_lead=is_board_lead,
        ),
    )


@pytest.mark.asyncio
async def test_recover_agent_rejects_non_lead_agent() -> None:
    board_id = uuid4()
    board = Board(id=board_id, gateway_id=uuid4(), name="Roadmap")

    with pytest.raises(HTTPException) as exc:
        await agent_api.recover_agent(
            agent_id=str(uuid4()),
            board=board,
            session=object(),  # type: ignore[arg-type]
            agent_ctx=_agent_ctx(board_id=board_id, is_board_lead=False),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Only board leads can perform this action"


@pytest.mark.asyncio
async def test_recover_agent_allows_board_lead_and_calls_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    board = Board(id=board_id, gateway_id=uuid4(), name="Roadmap")
    session = object()
    target_agent_id = str(uuid4())
    called: dict[str, object] = {}

    class _ServiceStub:
        def __init__(self, _session: object) -> None:
            called["session"] = _session

        async def recover_board_agent(
            self,
            *,
            board: Board,
            actor_agent: Agent,
            target_agent_id: str,
        ) -> None:
            called["board_id"] = board.id
            called["actor_id"] = actor_agent.id
            called["target_agent_id"] = target_agent_id

    monkeypatch.setattr(agent_api, "GatewayCoordinationService", _ServiceStub)
    agent_ctx = _agent_ctx(board_id=board_id, is_board_lead=True)

    response = await agent_api.recover_agent(
        agent_id=target_agent_id,
        board=board,
        session=session,  # type: ignore[arg-type]
        agent_ctx=agent_ctx,
    )

    assert response.ok is True
    assert called["session"] is session
    assert called["board_id"] == board_id
    assert called["actor_id"] == agent_ctx.agent.id
    assert called["target_agent_id"] == target_agent_id
