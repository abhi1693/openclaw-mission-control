# ruff: noqa: INP001
"""Integration tests for Phase II Blocker CRUD endpoints (plan §I1).

Exercises the handler functions directly with a live in-memory SQLite
session. HTTP-layer concerns (auth headers, pagination envelope) are
covered by the shared deps + fastapi_pagination tests and not
re-proven here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.blockers import create_task_blocker, update_task_blocker
from app.models.agents import Agent
from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.blockers import BlockerCreate, BlockerUpdate


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


@pytest_asyncio.fixture
async def seeded() -> AsyncIterator[tuple[AsyncSession, Board, Task, _ActorStub]]:
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
        name="Phase II test board",
        slug="phase-ii-test",
        description="Seeded for blocker API tests.",
    )
    session.add(board)
    agent = Agent(
        id=agent_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Filer Agent",
        status="online",
        openclaw_session_id="filer:session",
    )
    session.add(agent)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Test task",
        status="in_progress",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    actor = _ActorStub(agent=agent)
    try:
        yield session, board, task, actor
    finally:
        await session.close()
        await engine.dispose()


def _create_payload(**overrides: object) -> BlockerCreate:
    defaults: dict[str, object] = {
        "category": "source",
        "owner_role": "frontend-dev",
    }
    defaults.update(overrides)
    return BlockerCreate.model_validate(defaults)


@pytest.mark.asyncio
async def test_create_blocker_stamps_board_task_and_author(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    read = await create_task_blocker(
        payload=_create_payload(required_artifact="deploy-diff.json"),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert read.board_id == board.id
    assert read.task_id == task.id
    assert read.created_by_agent_id == actor.agent.id  # type: ignore[union-attr]
    assert read.resolved_at is None


@pytest.mark.asyncio
async def test_supersedes_resolves_prior_blocker(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Filing a sharpened blocker must close the superseded row in the
    same transaction — otherwise both show up as open."""

    session, board, task, actor = seeded
    prior = await create_task_blocker(
        payload=_create_payload(),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    sharpened = await create_task_blocker(
        payload=_create_payload(
            required_artifact="updated.json",
            supersedes_blocker_id=prior.id,
        ),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    prior_db = await session.get(Blocker, prior.id)
    assert prior_db is not None
    assert prior_db.resolved_at is not None
    assert sharpened.supersedes_blocker_id == prior.id


@pytest.mark.asyncio
async def test_supersedes_cross_task_blocker_404s(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """The self-FK must not leak blockers across tasks."""

    session, board, task, actor = seeded
    other_task_id = uuid4()
    session.add(
        Task(
            id=other_task_id,
            board_id=board.id,
            title="Other task",
            status="in_progress",
        ),
    )
    foreign = Blocker(
        board_id=board.id,
        task_id=other_task_id,
        category="source",
        owner_role="frontend-dev",
    )
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)

    with pytest.raises(HTTPException) as exc:
        await create_task_blocker(
            payload=_create_payload(supersedes_blocker_id=foreign.id),
            board=board,
            task=task,
            session=session,
            actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_acknowledge_then_resolve(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    created = await create_task_blocker(
        payload=_create_payload(),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )

    acked = await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="acknowledge"),
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert acked.acknowledged_at is not None
    assert acked.acknowledged_by_agent_id == actor.agent.id  # type: ignore[union-attr]
    assert acked.resolved_at is None

    resolved = await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="resolve"),
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    assert resolved.resolved_at is not None
    # Resolving shouldn't clobber the prior ack timestamp.
    assert resolved.acknowledged_at == acked.acknowledged_at


@pytest.mark.asyncio
async def test_patch_rejects_cross_task_blocker(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    other_task_id = uuid4()
    session.add(
        Task(
            id=other_task_id,
            board_id=board.id,
            title="Other task",
            status="in_progress",
        ),
    )
    foreign = Blocker(
        board_id=board.id,
        task_id=other_task_id,
        category="source",
        owner_role="frontend-dev",
    )
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)

    with pytest.raises(HTTPException) as exc:
        await update_task_blocker(
            blocker_id=foreign.id,
            payload=BlockerUpdate(status_transition="acknowledge"),
            task=task,
            session=session,
            actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_noop_payload_rejected() -> None:
    """Blank PATCH body must 422 — otherwise clients silently do nothing."""

    with pytest.raises(ValueError):
        BlockerUpdate()


@pytest.mark.asyncio
async def test_supersede_duplicate_rejected_with_409(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    """Partial unique index on supersedes_blocker_id surfaces as a 409
    via the handler's IntegrityError → HTTPException translation.

    This single-session test does not prove the prod TOCTOU race
    (that would need two concurrent connections); it proves the DB
    guard that makes the race race-safe.
    """

    session, board, task, actor = seeded
    prior = await create_task_blocker(
        payload=_create_payload(),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    await create_task_blocker(
        payload=_create_payload(supersedes_blocker_id=prior.id),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )

    with pytest.raises(HTTPException) as exc:
        await create_task_blocker(
            payload=_create_payload(supersedes_blocker_id=prior.id),
            board=board,
            task=task,
            session=session,
            actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_acknowledge_after_resolve_conflicts(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    created = await create_task_blocker(
        payload=_create_payload(),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="resolve"),
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    with pytest.raises(HTTPException) as exc:
        await update_task_blocker(
            blocker_id=created.id,
            payload=BlockerUpdate(status_transition="acknowledge"),
            task=task,
            session=session,
            actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_redundant_acknowledge_conflicts(
    seeded: tuple[AsyncSession, Board, Task, _ActorStub],
) -> None:
    session, board, task, actor = seeded
    created = await create_task_blocker(
        payload=_create_payload(),
        board=board,
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    await update_task_blocker(
        blocker_id=created.id,
        payload=BlockerUpdate(status_transition="acknowledge"),
        task=task,
        session=session,
        actor=actor,  # type: ignore[arg-type]
    )
    with pytest.raises(HTTPException) as exc:
        await update_task_blocker(
            blocker_id=created.id,
            payload=BlockerUpdate(status_transition="acknowledge"),
            task=task,
            session=session,
            actor=actor,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409
