# ruff: noqa: INP001
"""Integration tests for Phase III OperatorDecision endpoints (plan §I3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.operator_decisions import (
    create_operator_decision,
    update_operator_decision,
)
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.operator_decisions import (
    OperatorDecision,
    OperatorDecisionTaskLink,
)
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.operator_decisions import (
    OperatorDecisionCreate,
    OperatorDecisionUpdate,
)


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


@pytest_asyncio.fixture
async def seeded() -> AsyncIterator[
    tuple[AsyncSession, Board, Task, _ActorStub]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)

    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    agent_id = uuid4()
    task_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="https://gateway.example.local",
            workspace_root="/tmp/workspace",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="Phase III test board",
        slug="phase-iii-test",
        description="Seeded for operator-decision API tests.",
    )
    session.add(board)
    agent = Agent(
        id=agent_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Escalator",
        status="online",
        openclaw_session_id="escalator:session",
    )
    session.add(agent)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Decision target",
        status="in_progress",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    try:
        yield session, board, task, _ActorStub(agent=agent)
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_decision_defaults_pending_and_stamps_author(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    read = await create_operator_decision(
        payload=OperatorDecisionCreate(
            question="Should rollout continue?",
            dependent_task_ids=[task.id],
        ),
        board=board,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert read.status == "pending"
    assert read.created_by_agent_id == actor.agent.id  # type: ignore[union-attr]
    assert read.dependent_task_ids == [task.id]
    persisted = (
        await session.exec(
            select(OperatorDecisionTaskLink).where(
                col(OperatorDecisionTaskLink.decision_id) == read.id
            )
        )
    ).all()
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_resolve_transition_requires_resolved_value() -> None:
    """resolve without a value is a schema-layer 422 — the answer is
    mandatory because downstream consumers act on it."""

    with pytest.raises(ValidationError):
        OperatorDecisionUpdate(status_transition="resolve")


def test_resolve_transition_rejects_explicit_null_resolved_value() -> None:
    """Explicit ``resolved_value: None`` used to satisfy model_fields_set
    and silently persist a null answer. Guard now checks the value too."""

    with pytest.raises(ValidationError):
        OperatorDecisionUpdate(status_transition="resolve", resolved_value=None)


@pytest.mark.asyncio
async def test_resolve_sets_value_and_stamps_resolved_at(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    created = await create_operator_decision(
        payload=OperatorDecisionCreate(
            question="Should rollout continue?",
            dependent_task_ids=[task.id],
        ),
        board=board,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    resolved = await update_operator_decision(
        decision_id=created.id,
        payload=OperatorDecisionUpdate(
            status_transition="resolve", resolved_value="yes, proceed"
        ),
        board=board,
        session=session,
        _actor=actor,  # type: ignore[arg-type]
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_value == "yes, proceed"
    assert resolved.resolved_at is not None


@pytest.mark.asyncio
async def test_cancel_without_resolved_value_allowed(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, _task, actor = seeded
    created = await create_operator_decision(
        payload=OperatorDecisionCreate(question="Moot now?"),
        board=board,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    cancelled = await update_operator_decision(
        decision_id=created.id,
        payload=OperatorDecisionUpdate(status_transition="cancel"),
        board=board,
        session=session,
        _actor=actor,  # type: ignore[arg-type]
    )
    assert cancelled.status == "cancelled"
    assert cancelled.resolved_value is None


@pytest.mark.asyncio
async def test_double_resolve_conflicts(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, _task, actor = seeded
    created = await create_operator_decision(
        payload=OperatorDecisionCreate(question="Ship?"),
        board=board,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    await update_operator_decision(
        decision_id=created.id,
        payload=OperatorDecisionUpdate(
            status_transition="resolve", resolved_value="yes"
        ),
        board=board,
        session=session,
        _actor=actor,  # type: ignore[arg-type]
    )
    with pytest.raises(HTTPException) as exc:
        await update_operator_decision(
            decision_id=created.id,
            payload=OperatorDecisionUpdate(
                status_transition="resolve", resolved_value="yes"
            ),
            board=board,
            session=session,
            _actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_resolved_decision_metadata_conflicts(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Closed decisions are audit material — sharpening
    ``unblock_rule`` post-resolve would silently rewrite history."""

    session, board, _task, actor = seeded
    created = await create_operator_decision(
        payload=OperatorDecisionCreate(question="Ship?"),
        board=board,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    await update_operator_decision(
        decision_id=created.id,
        payload=OperatorDecisionUpdate(
            status_transition="resolve", resolved_value="yes"
        ),
        board=board,
        session=session,
        _actor=actor,  # type: ignore[arg-type]
    )
    with pytest.raises(HTTPException) as exc:
        await update_operator_decision(
            decision_id=created.id,
            payload=OperatorDecisionUpdate(unblock_rule="updated after close"),
            board=board,
            session=session,
            _actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_noop_payload_rejected() -> None:
    with pytest.raises(ValidationError):
        OperatorDecisionUpdate()


@pytest.mark.asyncio
async def test_create_rejects_cross_board_dependent_task_id(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Tenant-isolation guard: dependent_task_ids must all belong to
    the board being POST'd against. Without this check an attacker
    with write access to board A could link a foreign task from
    board B — leaking its UUID and merging blocking signal across
    tenants post-§I6."""

    session, board, _task, actor = seeded
    other_board_id = uuid4()
    session.add(
        Task(
            id=(foreign_task_id := uuid4()),
            board_id=other_board_id,
            title="Foreign",
            status="in_progress",
        ),
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_operator_decision(
            payload=OperatorDecisionCreate(
                question="Ship?",
                dependent_task_ids=[foreign_task_id],
            ),
            board=board,
            session=session,
            actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 422
    assert "unknown_task_ids" in exc.value.detail  # type: ignore[operator]


@pytest.mark.asyncio
async def test_cancel_clears_draft_resolved_value(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Pending decisions allow drafting ``resolved_value`` before
    committing; cancelling must erase the draft so the audit trail
    reads "cancelled", not "answered <stale draft> then cancelled"."""

    session, board, _task, actor = seeded
    created = await create_operator_decision(
        payload=OperatorDecisionCreate(question="Ship?"),
        board=board,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    drafted = await update_operator_decision(
        decision_id=created.id,
        payload=OperatorDecisionUpdate(resolved_value="yes, ship"),
        board=board,
        session=session,
        _actor=actor,  # type: ignore[arg-type]
    )
    assert drafted.resolved_value == "yes, ship"
    cancelled = await update_operator_decision(
        decision_id=created.id,
        payload=OperatorDecisionUpdate(status_transition="cancel"),
        board=board,
        session=session,
        _actor=actor,  # type: ignore[arg-type]
    )
    assert cancelled.status == "cancelled"
    assert cancelled.resolved_value is None


@pytest.mark.asyncio
async def test_load_decision_404_cross_board(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Decisions filed against another board must not be reachable —
    protects the board-scoped tenant isolation."""

    session, board, _task, actor = seeded
    other_board_id = uuid4()
    foreign = OperatorDecision(
        board_id=other_board_id,
        question="foreign decision",
    )
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)

    with pytest.raises(HTTPException) as exc:
        await update_operator_decision(
            decision_id=foreign.id,
            payload=OperatorDecisionUpdate(unblock_rule="hijack attempt"),
            board=board,
            session=session,
            _actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 404
