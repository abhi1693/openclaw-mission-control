from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.tasks import Task


def _agent_ctx(*, board_id: UUID, is_board_lead: bool) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Worker",
            is_board_lead=is_board_lead,
        ),
    )


@pytest.mark.asyncio
async def test_delete_task_rejects_non_lead_agent() -> None:
    board_id = uuid4()
    task = Task(
        id=uuid4(),
        board_id=board_id,
        title="Obsolete task",
    )

    with pytest.raises(HTTPException) as exc:
        await agent_api.delete_task(
            task=task,
            session=object(),  # type: ignore[arg-type]
            agent_ctx=_agent_ctx(board_id=board_id, is_board_lead=False),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Only board leads can perform this action"


@pytest.mark.asyncio
async def test_delete_task_allows_board_lead_and_calls_delete_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    task = Task(
        id=uuid4(),
        board_id=board_id,
        title="Obsolete task",
    )
    session = object()
    called: dict[str, object] = {}

    async def _fake_delete_task_and_related_records(_session: object, *, task: Task) -> None:
        called["session"] = _session
        called["task_id"] = task.id

    monkeypatch.setattr(
        agent_api.tasks_api,
        "delete_task_and_related_records",
        _fake_delete_task_and_related_records,
    )

    response = await agent_api.delete_task(
        task=task,
        session=session,  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id=board_id, is_board_lead=True),
    )

    assert response.ok is True
    assert called["session"] is session
    assert called["task_id"] == task.id
