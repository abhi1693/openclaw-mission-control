"""Coverage for `POST /api/v1/agent/boards/{board_id}/memory/intake/reconcile`.

The agent endpoint is the gateway-side trigger that the
``lead-memory-intake`` skill calls before its verification phase. The
endpoint thinly wraps ``app.services.board_memory_intake.reconcile_board_memory_intake``;
service-level coverage lives in ``test_board_memory_intake.py``. This
file owns the HTTP-shape contract: 200 OK with the four counter fields
(``scanned``, ``created``, ``skipped_existing``, ``skipped_non_actionable``)
the skill's downstream Python parser doesn't read but operator
dashboards and structured heartbeat reports do.

Production gap 2026-05-04: the endpoint did not exist. The skill
issued ``curl -fsS POST /memory/intake/reconcile``, which exited
non-zero on 404; the Supervisor heartbeat then reported
``HEARTBEAT_FAILED`` per the skill's ``Output ABI`` mapping. The
service implementation already existed
(``reconcile_board_memory_intake``); only the HTTP wiring was missing.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task


def _agent_ctx(*, board_id: UUID, gateway_id: UUID) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=gateway_id,
            name="Lead",
            status="online",
            is_board_lead=True,
        ),
    )


async def _seed_board(session: AsyncSession) -> Board:
    org_id = uuid4()
    gateway_id = uuid4()
    session.add(Organization(id=org_id, name="acme"))
    session.add(
        Gateway(
            id=gateway_id, organization_id=org_id, name="gw",
            url="ws://gw.example/ws", workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=uuid4(), organization_id=org_id, gateway_id=gateway_id,
        name="board", slug="board",
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


@pytest.mark.asyncio
async def test_reconcile_endpoint_returns_200_with_four_counter_fields(
    sqlite_session: AsyncSession,
) -> None:
    """The skill and any operator dashboard depend on the response
    JSON exposing exactly ``scanned``, ``created``, ``skipped_existing``,
    ``skipped_non_actionable`` as integers."""
    board = await _seed_board(sqlite_session)
    ctx = _agent_ctx(board_id=board.id, gateway_id=board.gateway_id)

    result = await agent_api.reconcile_board_memory_intake_endpoint(
        board=board, session=sqlite_session, agent_ctx=ctx,
    )
    payload = result.model_dump()
    for field in ("scanned", "created", "skipped_existing", "skipped_non_actionable"):
        assert field in payload, f"missing counter field: {field}"
        assert isinstance(payload[field], int), f"{field} must be int, got {type(payload[field])}"


@pytest.mark.asyncio
async def test_reconcile_creates_intake_task_for_unlinked_operator_findings_memory(
    sqlite_session: AsyncSession,
) -> None:
    """End-to-end: a qualifying operator+findings memory with no task
    yet must produce one inbox task after reconcile."""
    board = await _seed_board(sqlite_session)
    ctx = _agent_ctx(board_id=board.id, gateway_id=board.gateway_id)

    memory = BoardMemory(
        board_id=board.id,
        content="Operator finding: cookie banner regression on /trust at 375px viewport.",
        tags=["operator", "findings"],
    )
    sqlite_session.add(memory)
    await sqlite_session.commit()

    result = await agent_api.reconcile_board_memory_intake_endpoint(
        board=board, session=sqlite_session, agent_ctx=ctx,
    )

    assert result.scanned == 1
    assert result.created == 1
    assert result.skipped_existing == 0
    assert result.skipped_non_actionable == 0


@pytest.mark.asyncio
async def test_reconcile_skips_existing_linked_memory(
    sqlite_session: AsyncSession,
) -> None:
    """If a task already references the memory via ``source_memory_id``,
    the gate is idempotent — no duplicate task is created."""
    board = await _seed_board(sqlite_session)
    ctx = _agent_ctx(board_id=board.id, gateway_id=board.gateway_id)

    memory = BoardMemory(
        board_id=board.id,
        content="Operator finding: i18n switcher missing on /privacy.",
        tags=["operator", "findings"],
    )
    sqlite_session.add(memory)
    await sqlite_session.commit()
    sqlite_session.add(
        Task(
            id=uuid4(), board_id=board.id, title="prior intake",
            status="inbox", source_memory_id=memory.id,
        ),
    )
    await sqlite_session.commit()

    result = await agent_api.reconcile_board_memory_intake_endpoint(
        board=board, session=sqlite_session, agent_ctx=ctx,
    )

    assert result.scanned == 1
    assert result.created == 0
    assert result.skipped_existing == 1


@pytest.mark.asyncio
async def test_reconcile_skips_non_operator_memory(
    sqlite_session: AsyncSession,
) -> None:
    """``e2e_canary``-tagged or chat memories must not produce intake
    tasks — the gate is operator-finding-scoped."""
    board = await _seed_board(sqlite_session)
    ctx = _agent_ctx(board_id=board.id, gateway_id=board.gateway_id)

    sqlite_session.add(
        BoardMemory(
            board_id=board.id, content="random chat", tags=["chat"],
        ),
    )
    sqlite_session.add(
        BoardMemory(
            board_id=board.id, content="canary smoke", tags=["operator", "findings", "e2e_canary"],
        ),
    )
    await sqlite_session.commit()

    result = await agent_api.reconcile_board_memory_intake_endpoint(
        board=board, session=sqlite_session, agent_ctx=ctx,
    )

    assert result.scanned == 2
    assert result.created == 0
    assert result.skipped_non_actionable == 2


@pytest.mark.asyncio
async def test_reconcile_endpoint_rejects_non_lead_agent_with_403(
    sqlite_session: AsyncSession,
) -> None:
    """Codex review 2026-05-04: the reconcile endpoint claims
    ``required_privilege=board_lead`` in its OpenAPI hint but only
    called ``_guard_board_access``, letting any worker on the board
    trigger operator-memory→task materialization. Add a board-lead
    guard and assert the 403 here."""
    from fastapi import HTTPException

    board = await _seed_board(sqlite_session)
    worker_ctx = AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board.id,
            gateway_id=board.gateway_id,
            name="Programmer-Frontend",
            status="online",
            is_board_lead=False,
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await agent_api.reconcile_board_memory_intake_endpoint(
            board=board, session=sqlite_session, agent_ctx=worker_ctx,
        )
    assert exc.value.status_code == 403
