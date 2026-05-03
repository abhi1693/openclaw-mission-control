"""Phase II Blocker CRUD endpoints (plan §I1).

Blockers are per-task sidecar rows that carry the routing state the
Supervisor needs to escalate or reassign work. This router only
handles the data plane; the ``is_blocked`` derivation + rollout-flag
gating ship in follow-up commits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

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
from app.services.lead_notify import notify_lead_after_blocker_resolved

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


async def _task_has_other_open_blockers(
    session: "AsyncSession", *, task: Task, exclude_blocker_id: UUID
) -> bool:
    """True iff the task has any open Blocker other than the one given.

    Used to decide whether a resolve transition was the LAST open
    Blocker on the task — only that case warrants the lead wake.
    """
    other = await Blocker.objects.filter_by(task_id=task.id).filter(
        col(Blocker.id) != exclude_blocker_id,
        col(Blocker.resolved_at).is_(None),
    ).first(session)
    return other is not None


@router.get("", response_model=DefaultLimitOffsetPage[BlockerRead])
async def list_task_blockers(
    task: Task = TASK_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _board: "Board" = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
    status: Literal["open", "resolved"] | None = Query(
        default=None,
        description=(
            "Filter blockers by lifecycle state. ``open`` returns rows "
            "with ``resolved_at IS NULL``; ``resolved`` returns rows "
            "with ``resolved_at IS NOT NULL``. Omit to return both."
        ),
    ),
) -> "LimitOffsetPage[BlockerRead]":
    """List blockers filed against the task, newest first.

    The ``status`` query filter was added 2026-05-02 after a triage
    incident: the param had been documented (and used by operators)
    but not implemented. FastAPI silently accepted it and returned all
    rows, leading callers to read ``is_blocked=True`` from response
    bodies even when every Blocker was resolved.
    """
    statement = (
        Blocker.objects.filter_by(task_id=task.id)
        .order_by(Blocker.created_at.desc())
        .statement
    )
    if status == "open":
        statement = statement.where(col(Blocker.resolved_at).is_(None))
    elif status == "resolved":
        statement = statement.where(col(Blocker.resolved_at).is_not(None))
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
    # Phase V §I9 Fix 2 — retroactive reconcile path. If pipeline events
    # already satisfied the unblock condition BEFORE the lead opened
    # this Blocker (race window: worker posts events at T0, lead opens
    # Blocker at T0+ε), auto-resolve it now so it doesn't get stuck open.
    # Same helper used by ``record_task_pipeline_event`` for the
    # forward race.
    from app.services.blockers import auto_resolve_pipeline_blockers_if_ready

    resolved_count = await auto_resolve_pipeline_blockers_if_ready(
        session,
        board_id=board.id,
        task_id=task.id,
    )
    if resolved_count:
        await session.commit()
        await session.refresh(blocker)
        # Mirror the wake hook on the explicit resolve PATCH path: if the
        # auto-resolve closed the LAST open Blocker on this task, wake the
        # lead. Without this, the retroactive race (events landed first,
        # blocker filed second, auto-resolved immediately) silently leaves
        # the task actionable but un-routed.
        from app.services.blockers import task_has_open_blocker
        if not await task_has_open_blocker(
            session, board_id=board.id, task_id=task.id
        ):
            await notify_lead_after_blocker_resolved(session=session, task=task)
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
    # Closing the LAST open Blocker flips is_blocked from True to False;
    # wake the lead so the drain loop picks up the now-actionable task
    # instead of waiting for the next 5min heartbeat tick. Symmetric
    # with review-event PASS waking the next reviewer in tasks.py.
    if payload.status_transition == "resolve" and not await _task_has_other_open_blockers(
        session, task=task, exclude_blocker_id=blocker.id,
    ):
        await notify_lead_after_blocker_resolved(session=session, task=task)
    return BlockerRead.model_validate(blocker, from_attributes=True)
