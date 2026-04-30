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
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    ACTOR_DEP,
    SESSION_DEP,
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    get_task_or_404,
)
from app.core.time import utcnow
from app.db.pagination import paginate
from app.models.blockers import Blocker
from app.models.tasks import Task
from app.schemas.blockers import BlockerCreate, BlockerRead, BlockerUpdate
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


async def _load_blocker(
    session: "AsyncSession", *, task: Task, blocker_id: UUID
) -> Blocker:
    """Load a blocker scoped to the task, or raise 404.

    The task-scoped filter is load-bearing — it prevents cross-task
    self-FK reuse when filing a superseding blocker.
    """

    blocker = await Blocker.objects.filter_by(
        id=blocker_id, task_id=task.id
    ).first(session)
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
        Blocker.objects.filter_by(task_id=task.id)
        .order_by(Blocker.created_at.desc())
        .statement
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
        reason_code=payload.reason_code,
        owner_role=payload.owner_role,
        required_artifact=payload.required_artifact,
        target_env=payload.target_env,
        reopen_condition=payload.reopen_condition,
        citation=payload.citation,
        supersedes_blocker_id=payload.supersedes_blocker_id,
        created_by_agent_id=actor.agent.id if actor.agent is not None else None,
    )
    session.add(blocker)
    try:
        await session.commit()
    except IntegrityError as exc:
        # Partial unique index on supersedes_blocker_id serialises
        # concurrent POSTs that both try to supersede the same prior.
        # The loser sees 409, not 500.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="blocker already superseded",
        ) from exc
    # Blocker columns are all Python-side defaults or payload copies
    # — no server-side defaults, no triggers — so ``refresh()`` would
    # just burn a round trip reading back what we already know.
    return BlockerRead.model_validate(blocker, from_attributes=True)


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
    if blocker.resolved_at is not None and payload.status_transition is None:
        # Sharpening a resolved row would silently rewrite audit
        # material. A transition is the only legitimate PATCH against
        # a closed blocker, and the transition cases below already
        # reject both status_transition values on a resolved row.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot update a resolved blocker",
        )
    mutated = False

    if payload.status_transition == "acknowledge":
        if blocker.resolved_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot acknowledge a resolved blocker",
            )
        if blocker.acknowledged_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="blocker already acknowledged",
            )
        blocker.acknowledged_at = utcnow()
        blocker.acknowledged_by_agent_id = (
            actor.agent.id if actor.agent is not None else None
        )
        mutated = True
    elif payload.status_transition == "resolve":
        if blocker.resolved_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="blocker already resolved",
            )
        blocker.resolved_at = utcnow()
        mutated = True

    for field in ("required_artifact", "target_env", "reopen_condition", "citation", "reason_code"):
        if field in payload.model_fields_set:
            setattr(blocker, field, getattr(payload, field))
            mutated = True

    if mutated:
        session.add(blocker)
        await session.commit()
    return BlockerRead.model_validate(blocker, from_attributes=True)
