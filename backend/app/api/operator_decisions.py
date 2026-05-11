"""Phase III OperatorDecision endpoints (plan §I3).

Board-scoped CRUD for first-class operator decisions. Unlike blockers
(per-task) or reviews (per-task), a decision is board-scoped and can
link to multiple tasks. The compatibility bridge that ORs pending
decisions into ``is_blocked`` lands in a follow-up commit.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import update as sa_update
from sqlmodel import col, select

from app.api.deps import (
    ACTOR_DEP,
    SESSION_DEP,
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
)
from app.core.time import utcnow
from app.db.pagination import paginate
from app.models.operator_decisions import (
    OperatorDecision,
    OperatorDecisionTaskLink,
)
from app.models.tasks import Task
from app.schemas.operator_decisions import (
    OperatorDecisionCreate,
    OperatorDecisionRead,
    OperatorDecisionStatus,
    OperatorDecisionUpdate,
)
from app.schemas.pagination import DefaultLimitOffsetPage

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/operator_decisions", tags=["operator_decisions"])

BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)

STATUS_FILTER_QUERY: OperatorDecisionStatus | None = Query(default=None, alias="status")


async def _task_ids_by_decision(
    session: "AsyncSession", decision_ids: "Iterable[UUID]"
) -> dict[UUID, list[UUID]]:
    """Batch-preload the task id list per decision — the hot query
    for list-endpoint hydration. One SELECT instead of N."""

    ids = list(decision_ids)
    if not ids:
        return {}
    stmt = (
        select(
            col(OperatorDecisionTaskLink.decision_id),
            col(OperatorDecisionTaskLink.task_id),
        )
        .where(col(OperatorDecisionTaskLink.decision_id).in_(ids))
        .order_by(col(OperatorDecisionTaskLink.created_at).asc())
    )
    grouped: dict[UUID, list[UUID]] = defaultdict(list)
    for decision_id, task_id in (await session.exec(stmt)).all():
        grouped[decision_id].append(task_id)
    return grouped


def _decision_read(decision: OperatorDecision, task_ids: list[UUID]) -> OperatorDecisionRead:
    return OperatorDecisionRead(
        id=decision.id,
        board_id=decision.board_id,
        question=decision.question,
        owner_user_id=decision.owner_user_id,
        unblock_rule=decision.unblock_rule,
        reason_code=decision.reason_code,
        status=decision.status,
        resolved_value=decision.resolved_value,
        created_by_agent_id=decision.created_by_agent_id,
        created_at=decision.created_at,
        resolved_at=decision.resolved_at,
        dependent_task_ids=task_ids,
    )


async def _load_decision(
    session: "AsyncSession", *, board_id: UUID, decision_id: UUID
) -> OperatorDecision:
    """Load a decision scoped to the board, or raise 404."""

    decision = await OperatorDecision.objects.filter_by(id=decision_id, board_id=board_id).first(
        session
    )
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return decision


@router.get("", response_model=DefaultLimitOffsetPage[OperatorDecisionRead])
async def list_board_operator_decisions(
    board: "Board" = BOARD_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
    status_filter: OperatorDecisionStatus | None = STATUS_FILTER_QUERY,
) -> "LimitOffsetPage[OperatorDecisionRead]":
    """List operator decisions on the board, newest first.

    Optional ``status=pending|resolved|cancelled`` filter narrows to
    the inbox lane the operator cares about.
    """

    async def _transform(
        rows: "Sequence[object]",
    ) -> list[OperatorDecisionRead]:
        decisions: list[OperatorDecision] = []
        for row in rows:
            if not isinstance(row, OperatorDecision):
                msg = "Expected OperatorDecision rows from pagination query."
                raise TypeError(msg)
            decisions.append(row)
        tasks_by_decision = await _task_ids_by_decision(session, (d.id for d in decisions))
        return [
            _decision_read(decision, tasks_by_decision.get(decision.id, []))
            for decision in decisions
        ]

    statement = OperatorDecision.objects.filter_by(board_id=board.id)
    if status_filter is not None:
        statement = statement.filter(col(OperatorDecision.status) == status_filter)
    statement = statement.order_by(col(OperatorDecision.created_at).desc())
    return await paginate(session, statement.statement, transformer=_transform)


@router.post(
    "",
    response_model=OperatorDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_operator_decision(
    payload: OperatorDecisionCreate,
    board: "Board" = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> OperatorDecisionRead:
    """Escalate a new operator decision for the board.

    ``dependent_task_ids`` may be empty — the decision can exist in
    the inbox before the operator links it to specific tasks. The
    link management endpoint covers post-creation updates.
    """

    # Dedupe dependent_task_ids preserving order. Duplicates would
    # otherwise hit the ``(decision_id, task_id)`` unique constraint
    # at commit time and surface as a 500 IntegrityError.
    seen: set[UUID] = set()
    unique_task_ids: list[UUID] = []
    for task_id in payload.dependent_task_ids:
        if task_id in seen:
            continue
        seen.add(task_id)
        unique_task_ids.append(task_id)

    if unique_task_ids:
        # Tenant-isolation guard: every linked task_id must belong to
        # this board. The FK on ``operator_decision_task_links.task_id``
        # points at ``tasks.id`` globally, so without this check a
        # write-scoped caller could link cross-board tasks, leak their
        # UUIDs back in reads, and (post-§I6) silently merge blocking
        # signal across tenants.
        resolved = (
            await session.exec(
                select(col(Task.id))
                .where(col(Task.board_id) == board.id)
                .where(col(Task.id).in_(unique_task_ids))
            )
        ).all()
        resolved_set = set(resolved)
        missing = [str(task_id) for task_id in unique_task_ids if task_id not in resolved_set]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": "dependent_task_ids must reference tasks on this board",
                    "unknown_task_ids": missing,
                },
            )

    decision = OperatorDecision(
        board_id=board.id,
        question=payload.question,
        owner_user_id=payload.owner_user_id,
        unblock_rule=payload.unblock_rule,
        reason_code=payload.reason_code,
        created_by_agent_id=actor.agent.id if actor.agent is not None else None,
    )
    session.add(decision)
    for task_id in unique_task_ids:
        session.add(
            OperatorDecisionTaskLink(decision_id=decision.id, task_id=task_id),
        )
    await session.commit()
    return _decision_read(decision, unique_task_ids)


@router.patch("/{decision_id}", response_model=OperatorDecisionRead)
async def update_operator_decision(
    decision_id: UUID,
    payload: OperatorDecisionUpdate,
    board: "Board" = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> OperatorDecisionRead:
    """Resolve, cancel, or sharpen a pending operator decision."""

    decision = await _load_decision(session, board_id=board.id, decision_id=decision_id)
    # Preload the task-id list alongside the load so the response can
    # be synthesised without a post-commit refetch. PATCH never
    # mutates the link set today, so the list is invariant across the
    # handler's body.
    task_ids_by_decision = await _task_ids_by_decision(session, [decision.id])
    task_ids = task_ids_by_decision.get(decision.id, [])

    # Closed decisions are audit material: any PATCH — transition or
    # metadata — would either double-transition or silently rewrite
    # history. ``reject_noop_update`` on the schema already 422s the
    # empty-payload case, so every non-pending PATCH here is an edit.
    if decision.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot update a {decision.status} decision",
        )

    # Build the mutation dict up front so the write can CAS on status
    # in a single statement. Without the CAS, two concurrent PATCHes
    # can both observe ``pending``, both commit, and the audit trail
    # shows an already-terminal row accepting a second transition.
    new_values: dict[str, object] = {}
    if payload.status_transition == "resolve":
        new_values["status"] = "resolved"
        new_values["resolved_at"] = utcnow()
        new_values["resolved_value"] = payload.resolved_value
    elif payload.status_transition == "cancel":
        new_values["status"] = "cancelled"
        new_values["resolved_at"] = utcnow()
        # Clear any draft answer so the audit trail doesn't read
        # "answered yes then cancelled" — cancel means "moot", not
        # "resolved with <stale draft>".
        new_values["resolved_value"] = None
    elif "resolved_value" in payload.model_fields_set:
        # Draft sharpening while still pending.
        new_values["resolved_value"] = payload.resolved_value
    for field in ("owner_user_id", "unblock_rule", "reason_code"):
        if field in payload.model_fields_set:
            new_values[field] = getattr(payload, field)

    if new_values:
        result = await session.exec(
            sa_update(OperatorDecision)
            .where(col(OperatorDecision.id) == decision.id)
            .where(col(OperatorDecision.status) == "pending")
            .values(**new_values),
        )
        if result.rowcount == 0:
            # The row transitioned out of ``pending`` between load and
            # write — a concurrent resolve/cancel raced us.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="decision state changed concurrently",
            )
        await session.commit()
        # Mirror the write back onto the in-memory instance so the
        # response reflects the persisted state without a re-read.
        for key, value in new_values.items():
            setattr(decision, key, value)

    return _decision_read(decision, task_ids)
