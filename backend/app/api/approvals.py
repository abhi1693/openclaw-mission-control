"""Approval listing, streaming, creation, and update endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import asc, func, or_
from sqlmodel import col, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    get_board_for_user_write,
    require_admin_or_agent,
)
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.tasks import Task
from app.schemas.approvals import ApprovalCreate, ApprovalRead, ApprovalStatus, ApprovalUpdate
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.activity_log import record_activity
from app.services.approval_task_links import (
    load_task_ids_by_approval,
    lock_tasks_for_approval,
    normalize_task_ids,
    pending_approval_conflicts_by_task,
    replace_approval_task_links,
    task_counts_for_board,
)
from app.services.openclaw.gateway_dispatch import GatewayDispatchService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/approvals", tags=["approvals"])
logger = get_logger(__name__)

STREAM_POLL_SECONDS = 2
STATUS_FILTER_QUERY = Query(default=None, alias="status")
SINCE_QUERY = Query(default=None)
BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
BOARD_USER_WRITE_DEP = Depends(get_board_for_user_write)
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_admin_or_agent)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _approval_updated_at(approval: Approval) -> datetime:
    return approval.resolved_at or approval.created_at


async def _approval_task_ids_map(
    session: AsyncSession,
    approvals: Sequence[Approval],
) -> dict[UUID, list[UUID]]:
    approval_ids = [approval.id for approval in approvals]
    mapping = await load_task_ids_by_approval(session, approval_ids=approval_ids)
    for approval in approvals:
        if mapping.get(approval.id):
            continue
        if approval.task_id is not None:
            mapping[approval.id] = [approval.task_id]
        else:
            mapping[approval.id] = []
    return mapping


async def _task_titles_by_id(
    session: AsyncSession,
    *,
    task_ids: set[UUID],
) -> dict[UUID, str]:
    if not task_ids:
        return {}
    rows = list(
        await session.exec(
            select(col(Task.id), col(Task.title)).where(col(Task.id).in_(task_ids)),
        ),
    )
    return {task_id: title for task_id, title in rows}


def _approval_to_read(
    approval: Approval,
    *,
    task_ids: list[UUID],
    task_titles: list[str],
) -> ApprovalRead:
    primary_task_id = task_ids[0] if task_ids else None
    model = ApprovalRead.model_validate(approval, from_attributes=True)
    return model.model_copy(
        update={
            "task_id": primary_task_id,
            "task_ids": task_ids,
            "task_titles": task_titles,
        },
    )


async def _approval_reads(
    session: AsyncSession,
    approvals: Sequence[Approval],
) -> list[ApprovalRead]:
    mapping = await _approval_task_ids_map(session, approvals)
    title_by_id = await _task_titles_by_id(
        session,
        task_ids={task_id for task_ids in mapping.values() for task_id in task_ids},
    )
    return [
        _approval_to_read(
            approval,
            task_ids=(task_ids := mapping.get(approval.id, [])),
            task_titles=[title_by_id[task_id] for task_id in task_ids if task_id in title_by_id],
        )
        for approval in approvals
    ]


def _serialize_approval(approval: ApprovalRead) -> dict[str, object]:
    return approval.model_dump(mode="json")


def _pending_conflict_detail(conflicts: dict[UUID, UUID]) -> dict[str, object]:
    ordered = sorted(conflicts.items(), key=lambda item: str(item[0]))
    return {
        "message": "Each task can have only one pending approval.",
        "conflicts": [
            {
                "task_id": str(task_id),
                "approval_id": str(approval_id),
            }
            for task_id, approval_id in ordered
        ],
    }


async def _ensure_no_pending_approval_conflicts(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Sequence[UUID],
    exclude_approval_id: UUID | None = None,
) -> None:
    normalized_task_ids = list({*task_ids})
    if not normalized_task_ids:
        return
    await lock_tasks_for_approval(session, task_ids=normalized_task_ids)
    conflicts = await pending_approval_conflicts_by_task(
        session,
        board_id=board_id,
        task_ids=normalized_task_ids,
        exclude_approval_id=exclude_approval_id,
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_pending_conflict_detail(conflicts),
        )


def _approval_resolution_message(
    *,
    board: Board,
    approval: Approval,
    task_ids: Sequence[UUID] | None = None,
) -> str:
    status_text = "approved" if approval.status == "approved" else "rejected"
    lines = [
        "APPROVAL RESOLVED",
        f"Board: {board.name}",
        f"Approval ID: {approval.id}",
        f"Action: {approval.action_type}",
        f"Decision: {status_text}",
        f"Confidence: {approval.confidence}",
    ]
    normalized_task_ids = list(task_ids or [])
    if not normalized_task_ids and approval.task_id is not None:
        normalized_task_ids = [approval.task_id]
    if len(normalized_task_ids) == 1:
        lines.append(f"Task ID: {normalized_task_ids[0]}")
    elif normalized_task_ids:
        lines.append(f"Task IDs: {', '.join(str(value) for value in normalized_task_ids)}")
    lines.append("")
    lines.append("Take action: continue execution using the final approval decision.")
    return "\n".join(lines)


async def _resolve_board_lead(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> Agent | None:
    return (
        await Agent.objects.filter_by(board_id=board_id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )


async def _notify_lead_on_approval_resolution(
    *,
    session: AsyncSession,
    board: Board,
    approval: Approval,
) -> None:
    if approval.status not in {"approved", "rejected"}:
        return
    lead = await _resolve_board_lead(session, board_id=board.id)
    if lead is None or not lead.openclaw_session_id:
        return

    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return

    task_ids_by_approval = await load_task_ids_by_approval(session, approval_ids=[approval.id])
    message = _approval_resolution_message(
        board=board,
        approval=approval,
        task_ids=task_ids_by_approval.get(approval.id, []),
    )
    error = await dispatch.try_send_agent_message(
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=message,
        deliver=False,
    )
    if error is None:
        record_activity(
            session,
            event_type="approval.lead_notified",
            message=f"Lead agent notified for {approval.status} approval {approval.id}.",
            agent_id=lead.id,
            task_id=approval.task_id,
        )
    else:
        record_activity(
            session,
            event_type="approval.lead_notify_failed",
            message=f"Lead notify failed for approval {approval.id}: {error}",
            agent_id=lead.id,
            task_id=approval.task_id,
        )
    await session.commit()


async def _fetch_approval_events(
    session: AsyncSession,
    board_id: UUID,
    since: datetime,
) -> list[Approval]:
    statement = (
        Approval.objects.filter_by(board_id=board_id)
        .filter(
            or_(
                col(Approval.created_at) >= since,
                col(Approval.resolved_at) >= since,
            ),
        )
        .order_by(asc(col(Approval.created_at)))
    )
    return await statement.all(session)


@router.get("", response_model=DefaultLimitOffsetPage[ApprovalRead])
async def list_approvals(
    status_filter: ApprovalStatus | None = STATUS_FILTER_QUERY,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> LimitOffsetPage[ApprovalRead]:
    """List approvals for a board, optionally filtering by status."""
    statement = Approval.objects.filter_by(board_id=board.id)
    if status_filter:
        statement = statement.filter(col(Approval.status) == status_filter)
    statement = statement.order_by(col(Approval.created_at).desc())

    async def _transform(items: Sequence[object]) -> Sequence[ApprovalRead]:
        approvals: list[Approval] = []
        for item in items:
            if not isinstance(item, Approval):
                msg = "Expected Approval items from approvals pagination query."
                raise TypeError(msg)
            approvals.append(item)
        return await _approval_reads(session, approvals)

    return await paginate(session, statement.statement, transformer=_transform)


@router.get("/stream")
async def stream_approvals(
    request: Request,
    board: Board = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
    since: str | None = SINCE_QUERY,
) -> EventSourceResponse:
    """Stream approval updates for a board using server-sent events."""
    since_dt = _parse_since(since) or utcnow()
    last_seen = since_dt

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        nonlocal last_seen
        while True:
            if await request.is_disconnected():
                break
            async with async_session_maker() as session:
                approvals = await _fetch_approval_events(session, board.id, last_seen)
                approval_reads = await _approval_reads(session, approvals)
                pending_approvals_count = int(
                    (
                        await session.exec(
                            select(func.count(col(Approval.id)))
                            .where(col(Approval.board_id) == board.id)
                            .where(col(Approval.status) == "pending"),
                        )
                    ).one(),
                )
                task_ids = {
                    task_id
                    for approval_read in approval_reads
                    for task_id in approval_read.task_ids
                }
                counts_by_task_id = await task_counts_for_board(
                    session,
                    board_id=board.id,
                    task_ids=task_ids,
                )
            for approval, approval_read in zip(approvals, approval_reads, strict=True):
                updated_at = _approval_updated_at(approval)
                last_seen = max(updated_at, last_seen)
                payload: dict[str, object] = {
                    "approval": _serialize_approval(approval_read),
                    "pending_approvals_count": pending_approvals_count,
                }
                task_counts = [
                    {
                        "task_id": str(task_id),
                        "approvals_count": total,
                        "approvals_pending_count": pending,
                    }
                    for task_id in approval_read.task_ids
                    if (counts := counts_by_task_id.get(task_id)) is not None
                    for total, pending in [counts]
                ]
                if len(task_counts) == 1:
                    payload["task_counts"] = task_counts[0]
                elif task_counts:
                    payload["task_counts"] = task_counts
                yield {"event": "approval", "data": json.dumps(payload)}
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(event_generator(), ping=15)


@router.post("", response_model=ApprovalRead)
async def create_approval(
    payload: ApprovalCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> ApprovalRead:
    """Create an approval for a board."""
    task_ids = normalize_task_ids(
        task_id=payload.task_id,
        task_ids=payload.task_ids,
        payload=payload.payload,
    )
    task_id = task_ids[0] if task_ids else None
    if payload.status == "pending":
        await _ensure_no_pending_approval_conflicts(
            session,
            board_id=board.id,
            task_ids=task_ids,
        )
    approval = Approval(
        board_id=board.id,
        task_id=task_id,
        agent_id=payload.agent_id,
        action_type=payload.action_type,
        payload=payload.payload,
        confidence=payload.confidence,
        rubric_scores=payload.rubric_scores,
        status=payload.status,
    )
    session.add(approval)
    await session.flush()
    await replace_approval_task_links(
        session,
        approval_id=approval.id,
        task_ids=task_ids,
    )
    await session.commit()
    await session.refresh(approval)
    title_by_id = await _task_titles_by_id(session, task_ids=set(task_ids))
    return _approval_to_read(
        approval,
        task_ids=task_ids,
        task_titles=[title_by_id[task_id] for task_id in task_ids if task_id in title_by_id],
    )


@router.patch("/{approval_id}", response_model=ApprovalRead)
async def update_approval(
    approval_id: str,
    payload: ApprovalUpdate,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApprovalRead:
    """Update an approval's status and resolution timestamp."""
    approval = await Approval.objects.by_id(approval_id).first(session)
    if approval is None or approval.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updates = payload.model_dump(exclude_unset=True)
    prior_status = approval.status
    if "status" in updates:
        target_status = updates["status"]
        if target_status == "pending" and prior_status != "pending":
            task_ids_by_approval = await load_task_ids_by_approval(
                session, approval_ids=[approval.id]
            )
            approval_task_ids = task_ids_by_approval.get(approval.id)
            if not approval_task_ids and approval.task_id is not None:
                approval_task_ids = [approval.task_id]
            await _ensure_no_pending_approval_conflicts(
                session,
                board_id=board.id,
                task_ids=approval_task_ids or [],
                exclude_approval_id=approval.id,
            )
        approval.status = target_status
        if approval.status != "pending":
            approval.resolved_at = utcnow()
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    if approval.status in {"approved", "rejected"} and approval.status != prior_status:
        try:
            await _notify_lead_on_approval_resolution(
                session=session,
                board=board,
                approval=approval,
            )
        except Exception:
            logger.exception(
                "approval.lead_notify_unexpected board_id=%s approval_id=%s status=%s",
                board.id,
                approval.id,
                approval.status,
            )
    reads = await _approval_reads(session, [approval])
    return reads[0]
