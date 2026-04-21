"""Phase II Blocker CRUD endpoints (plan §I1).

Blockers are per-task sidecar rows that carry the routing state the
Supervisor needs to escalate or reassign work. This router only
handles the data plane; the ``is_blocked`` derivation + rollout-flag
gating ship in follow-up commits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col, select

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    get_task_or_404,
    require_user_or_agent,
)
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.blockers import Blocker
from app.models.tasks import Task
from app.schemas.blockers import BlockerCreate, BlockerRead, BlockerUpdate
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(
    prefix="/boards/{board_id}/tasks/{task_id}/blockers", tags=["blockers"]
)

BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
TASK_DEP = Depends(get_task_or_404)
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_user_or_agent)


def _agent_id_for(actor: ActorContext) -> UUID | None:
    return actor.agent.id if actor.agent is not None else None


async def _load_blocker(
    session: "AsyncSession", *, task: Task, blocker_id: UUID
) -> Blocker:
    stmt = (
        select(Blocker)
        .where(col(Blocker.id) == blocker_id)
        .where(col(Blocker.task_id) == task.id)
    )
    blocker = (await session.exec(stmt)).first()
    if blocker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return blocker


@router.get("", response_model=DefaultLimitOffsetPage[BlockerRead])
async def list_task_blockers(
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _board: "Board" = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> "LimitOffsetPage[BlockerRead]":
    """List blockers filed against the task, newest first."""

    statement = (
        select(Blocker)
        .where(col(Blocker.task_id) == task.id)
        .order_by(col(Blocker.created_at).desc())
    )
    return await paginate(session, statement)


@router.post("", response_model=BlockerRead, status_code=status.HTTP_201_CREATED)
async def create_task_blocker(
    payload: BlockerCreate,
    board: "Board" = BOARD_WRITE_DEP,
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BlockerRead:
    """File a new blocker against the task."""

    if payload.supersedes_blocker_id is not None:
        # Guard the self-FK: the superseded row must live on the same
        # task so we don't leak cross-task blocker chains.
        prior = await _load_blocker(
            session, task=task, blocker_id=payload.supersedes_blocker_id
        )
        if prior.resolved_at is None:
            prior.resolved_at = utcnow()
            session.add(prior)

    blocker = Blocker(
        board_id=board.id,
        task_id=task.id,
        category=payload.category,
        owner_role=payload.owner_role,
        required_artifact=payload.required_artifact,
        target_env=payload.target_env,
        reopen_condition=payload.reopen_condition,
        supersedes_blocker_id=payload.supersedes_blocker_id,
        created_by_agent_id=_agent_id_for(actor),
    )
    session.add(blocker)
    await session.commit()
    await session.refresh(blocker)
    return BlockerRead.model_validate(blocker.model_dump())


@router.patch("/{blocker_id}", response_model=BlockerRead)
async def update_task_blocker(
    blocker_id: UUID,
    payload: BlockerUpdate,
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _board: "Board" = BOARD_WRITE_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BlockerRead:
    """Acknowledge, resolve, or sharpen an open blocker."""

    blocker = await _load_blocker(session, task=task, blocker_id=blocker_id)

    if payload.acknowledge and blocker.acknowledged_at is None:
        blocker.acknowledged_at = utcnow()
        blocker.acknowledged_by_agent_id = _agent_id_for(actor)
    if payload.resolve and blocker.resolved_at is None:
        blocker.resolved_at = utcnow()
    if "required_artifact" in payload.model_fields_set:
        blocker.required_artifact = payload.required_artifact
    if "target_env" in payload.model_fields_set:
        blocker.target_env = payload.target_env
    if "reopen_condition" in payload.model_fields_set:
        blocker.reopen_condition = payload.reopen_condition

    session.add(blocker)
    await session.commit()
    await session.refresh(blocker)
    return BlockerRead.model_validate(blocker.model_dump())


@router.delete("/{blocker_id}", response_model=OkResponse)
async def delete_task_blocker(
    blocker_id: UUID,
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _board: "Board" = BOARD_WRITE_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> OkResponse:
    """Hard-delete a blocker. Prefer resolve over delete — delete drops audit."""

    blocker = await _load_blocker(session, task=task, blocker_id=blocker_id)
    await session.delete(blocker)
    await session.commit()
    return OkResponse()
