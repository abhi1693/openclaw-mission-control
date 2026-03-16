from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tags import Tag


@dataclass
class _FakeExecResult:
    tags: list[Tag]

    def all(self) -> list[Tag]:
        return self.tags


@dataclass
class _FakeSession:
    tags: list[Tag]

    async def exec(self, _query: object) -> _FakeExecResult:
        return _FakeExecResult(self.tags)


def _board() -> Board:
    return Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Delivery",
        slug="delivery",
    )


def _agent_ctx(*, board_id: UUID | None) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Lead",
            is_board_lead=True,
        ),
    )


@pytest.mark.asyncio
async def test_list_tags_returns_tag_refs() -> None:
    board = _board()
    session = _FakeSession(
        tags=[
            Tag(
                id=uuid4(),
                organization_id=board.organization_id,
                name="Backend",
                slug="backend",
                color="0f172a",
            ),
            Tag(
                id=uuid4(),
                organization_id=board.organization_id,
                name="Urgent",
                slug="urgent",
                color="dc2626",
            ),
        ],
    )

    response = await agent_api.list_tags(
        board=board,
        session=session,  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id=board.id),
    )

    assert [tag.slug for tag in response] == ["backend", "urgent"]
    assert response[0].name == "Backend"
    assert response[1].color == "dc2626"


@pytest.mark.asyncio
async def test_list_tags_rejects_cross_board_agent() -> None:
    board = _board()
    session = _FakeSession(tags=[])

    with pytest.raises(HTTPException) as exc:
        await agent_api.list_tags(
            board=board,
            session=session,  # type: ignore[arg-type]
            agent_ctx=_agent_ctx(board_id=uuid4()),
        )

    assert exc.value.status_code == 403
