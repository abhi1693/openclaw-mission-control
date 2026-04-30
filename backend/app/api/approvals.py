"""Approval listing, streaming, creation, and update endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
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
    require_user_or_agent,
)
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.agents import Agent
from app.models.approval_history import ApprovalHistory
from app.models.approvals import Approval
from app.models.tasks import Task
from app.schemas.approvals import (
    ApprovalCreate,
    ApprovalRead,
    ApprovalStatus,
    ApprovalUnblock,
    ApprovalUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.tasks import actionability_missing_fields
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
ACTOR_DEP = Depends(require_user_or_agent)


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


DONE_APPROVAL_ACTION_TYPES = (
    "move_to_done",
    "mark_done",
    "task_done",
    "move_task_to_done",
)


async def _ensure_move_to_done_targets_in_review(
    session: AsyncSession,
    *,
    board_id: UUID,
    action_type: str,
    task_ids: Sequence[UUID],
) -> None:
    if action_type not in DONE_APPROVAL_ACTION_TYPES or not task_ids:
        return
    rows = await session.exec(
        select(Task.id, Task.status)
        .where(col(Task.board_id) == board_id)
        .where(col(Task.id).in_(list(task_ids)))
    )
    status_by_task_id = {task_id: status for task_id, status in rows}
    invalid_task_ids = [
        str(task_id) for task_id in task_ids if status_by_task_id.get(task_id) != "review"
    ]
    if invalid_task_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "move_to_done approvals can only be created for tasks currently in review.",
                "task_ids": invalid_task_ids,
            },
        )


async def _ensure_move_to_done_targets_have_delivery_contract(
    session: AsyncSession,
    *,
    board_id: UUID,
    action_type: str,
    task_ids: Sequence[UUID],
) -> None:
    if action_type not in DONE_APPROVAL_ACTION_TYPES or not task_ids:
        return
    rows = await session.exec(
        select(
            Task.id,
            Task.status,
            Task.review_packet_type,
            Task.validation_target,
            Task.validation_target_kind,
            Task.validation_target_scope,
            Task.assigned_agent_id,
        )
        .where(col(Task.board_id) == board_id)
        .where(col(Task.id).in_(list(task_ids)))
    )
    task_details: list[dict[str, object]] = []
    invalid_task_ids: list[str] = []
    for (
        task_id,
        status_value,
        review_packet_type,
        validation_target,
        validation_target_kind,
        validation_target_scope,
        assigned_agent_id,
    ) in rows:
        # Phase IV §I2: validate against the TARGET state (``done``)
        # not the task's current state (usually ``review``). Under the
        # current status, the owner carve-out for ``review`` would
        # silently skip the owner check — an assignee cleared between
        # approval creation and execution would commit an ownerless
        # ``done`` row via the lead PATCH path.
        missing_fields = actionability_missing_fields(
            status="done",
            review_packet_type=review_packet_type,
            validation_target=validation_target,
            validation_target_kind=validation_target_kind,
            validation_target_scope=validation_target_scope,
            assigned_agent_id=assigned_agent_id,
        )
        if not missing_fields:
            continue
        invalid_task_ids.append(str(task_id))
        task_details.append(
            {
                "task_id": str(task_id),
                "status": status_value,
                "missing_fields": missing_fields,
            }
        )
    if invalid_task_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "move_to_done approvals require a complete delivery contract.",
                "code": "task_delivery_contract_incomplete",
                "task_ids": invalid_task_ids,
                "task_details": task_details,
            },
        )


REJECTION_LOOP_THRESHOLD = 3
REJECTION_LOOP_WINDOW_HOURS = 24

# Event type constants for ApprovalHistory. Kept in this file (not in
# the model) so all producers are obvious in one place.
HISTORY_EVENT_SUBMITTED = "submitted"
HISTORY_EVENT_REJECTED = "rejected"
HISTORY_EVENT_APPROVED = "approved"
HISTORY_EVENT_UNBLOCKED = "unblocked"


async def _record_approval_history_event(
    session: AsyncSession,
    *,
    approval_id: UUID,
    board_id: UUID,
    task_ids: Sequence[UUID],
    event_type: str,
    actor: ActorContext | None,
    message: str | None = None,
) -> None:
    """Append one or more rows to ``approval_history``.

    When an approval covers multiple linked tasks we record a separate
    row per task so per-task streak queries are correct without joins.
    Passing an empty ``task_ids`` records a single row with ``task_id``
    null (e.g., approval-level events that are not tied to a task).
    """
    actor_type: str
    actor_user_id: UUID | None = None
    actor_agent_id: UUID | None = None
    if actor is None:
        actor_type = "system"
    elif actor.user is not None:
        actor_type = "user"
        actor_user_id = actor.user.id
    elif actor.agent is not None:
        actor_type = "agent"
        actor_agent_id = actor.agent.id
    else:  # pragma: no cover - ActorContext invariant violation
        actor_type = "system"

    normalized = list({*task_ids}) if task_ids else [None]  # type: ignore[list-item]
    for task_id in normalized:
        event = ApprovalHistory(
            approval_id=approval_id,
            board_id=board_id,
            task_id=task_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            actor_agent_id=actor_agent_id,
            message=(message[:2000] if message else None),
        )
        session.add(event)


async def _ensure_no_rejection_loop(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Sequence[UUID],
) -> None:
    """Block re-submission after ``REJECTION_LOOP_THRESHOLD`` consecutive
    rejections on the same task within ``REJECTION_LOOP_WINDOW_HOURS``.

    Correctness properties (vs the broken v1):

    - **Append-only history**: reads ``approval_history`` rows, not the
      mutable ``approvals`` table. Reject-reopen-reject cycles cannot
      hide history because each rejection is a separate row.
    - **Per-task streak**: computes the consecutive-rejection streak for
      each task independently. A batch approval covering tasks A and B
      does not pollute A's streak with B's rejections.
    - **Authenticated unblock**: only an ``unblocked`` or ``approved``
      event written by ``POST .../unblock`` or the PATCH resolve flow
      clears the streak. String-matching on worker-controlled comments
      is gone.
    - **Correct time column**: history rows have their own ``created_at``
      that records when each event happened. No ``Approval.created_at``
      vs ``resolved_at`` confusion.
    """
    normalized = list({*task_ids})
    if not normalized:
        return
    window_start = utcnow() - timedelta(hours=REJECTION_LOOP_WINDOW_HOURS)
    stmt = (
        select(ApprovalHistory)
        .where(
            ApprovalHistory.board_id == board_id,
            col(ApprovalHistory.task_id).in_(normalized),
            ApprovalHistory.created_at >= window_start,
            col(ApprovalHistory.event_type).in_(
                [
                    HISTORY_EVENT_REJECTED,
                    HISTORY_EVENT_APPROVED,
                    HISTORY_EVENT_UNBLOCKED,
                ]
            ),
        )
        .order_by(col(ApprovalHistory.created_at).asc())
    )
    result = await session.exec(stmt)
    events = list(result.all())
    if not events:
        return
    # Compute per-task streaks. Walk chronologically so we can reset the
    # streak on approved/unblocked events.
    streaks: dict[UUID, int] = {task_id: 0 for task_id in normalized}
    for event in events:
        event_task_id = event.task_id
        if event_task_id is None:
            continue
        if event.event_type in (HISTORY_EVENT_APPROVED, HISTORY_EVENT_UNBLOCKED):
            streaks[event_task_id] = 0
        elif event.event_type == HISTORY_EVENT_REJECTED:
            streaks[event_task_id] = streaks.get(event_task_id, 0) + 1
    exceeded = [
        (task_id, count)
        for task_id, count in streaks.items()
        if count >= REJECTION_LOOP_THRESHOLD
    ]
    if not exceeded:
        return
    worst_task_id, worst_count = max(exceeded, key=lambda pair: pair[1])
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Rejection loop detected on task {worst_task_id}: "
            f"{worst_count} consecutive rejections in the last "
            f"{REJECTION_LOOP_WINDOW_HOURS}h. Escalation required — a board "
            f"lead or human operator must call "
            f"POST /api/v1/boards/{{board_id}}/approvals/{{approval_id}}/unblock "
            f"to clear the streak before any re-submission. Repeatedly cycling "
            f"the same code through approval is forbidden by board hard rules."
        ),
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
            board_id=approval.board_id,
        )
    else:
        record_activity(
            session,
            event_type="approval.lead_notify_failed",
            message=f"Lead notify failed for approval {approval.id}: {error}",
            agent_id=lead.id,
            task_id=approval.task_id,
            board_id=approval.board_id,
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
    actor: ActorContext = ACTOR_DEP,
) -> ApprovalRead:
    """Create an approval for a board."""
    task_ids = normalize_task_ids(
        task_id=payload.task_id,
        task_ids=payload.task_ids,
        payload=payload.payload,
    )
    # ``move_to_done`` approvals must target tasks that are currently in
    # ``review`` — regardless of submit vs. resolve path. Runs before the
    # pending-only guard so a ``status="approved"`` move_to_done against
    # a non-review task reports the more specific 409, not a generic 400.
    await _ensure_move_to_done_targets_in_review(
        session,
        board_id=board.id,
        action_type=payload.action_type,
        task_ids=task_ids,
    )
    await _ensure_move_to_done_targets_have_delivery_contract(
        session,
        board_id=board.id,
        action_type=payload.action_type,
        task_ids=task_ids,
    )
    # Privileged-state guard (v2 Codex review finding): ``create_approval``
    # is strictly for submitting a NEW pending request. State transitions
    # go through ``PATCH .../approvals/{id}`` or ``POST .../unblock``.
    # Rationale: an approved approval seed creates an ``approved`` event
    # in ``approval_history`` which resets ``_ensure_no_rejection_loop``;
    # keeping a second admin-seed path for humans was a footgun. Admin
    # overrides explicitly go through the unblock endpoint with an
    # audited reason string.
    if payload.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "create_approval only accepts status='pending'. "
                "Use PATCH /approvals/{id} to resolve, or "
                "POST /approvals/{id}/unblock to clear a rejection loop."
            ),
        )
    task_id = task_ids[0] if task_ids else None
    if payload.status == "pending":
        await _ensure_no_pending_approval_conflicts(
            session,
            board_id=board.id,
            task_ids=task_ids,
        )
        await _ensure_no_rejection_loop(
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
    # Status is guaranteed ``pending`` by the guard above, so we always
    # record a ``submitted`` history event here.
    reason_value = (payload.payload or {}).get("reason") if payload.payload else None
    history_message = str(reason_value) if reason_value is not None else None
    await _record_approval_history_event(
        session,
        approval_id=approval.id,
        board_id=board.id,
        task_ids=task_ids,
        event_type=HISTORY_EVENT_SUBMITTED,
        actor=actor,
        message=history_message,
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
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = Depends(require_user_or_agent),
) -> ApprovalRead:
    """Update an approval's status and resolution timestamp.

    Agents (board lead only) can reject approvals to unblock rework.
    Only humans can approve (final quality gate).
    """
    updates = payload.model_dump(exclude_unset=True)
    if actor.agent and "status" in updates:
        if updates["status"] != "rejected":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agents can only reject approvals, not approve. Human approval required.",
            )
        if not actor.agent.is_board_lead:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only board leads can reject approvals.",
            )
    approval = await Approval.objects.by_id(approval_id).first(session)
    if approval is None or approval.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    prior_status = approval.status
    history_event_to_record: str | None = None
    history_task_ids_for_event: list[UUID] = []
    if "status" in updates:
        target_status = updates["status"]
        # Idempotency: a same-decision resolve on an already-resolved approval
        # returns the current state without mutating ``resolved_at``, writing
        # history, or firing lead notifications. Mirrors the OpenClaw 4.27
        # gateway-side approval idempotency contract so client retries after
        # a transient network blip do not double-record.
        if (
            target_status in {"approved", "rejected"}
            and prior_status == target_status
        ):
            reads = await _approval_reads(session, [approval])
            return reads[0]
        # Conflict guard: refuse to flip an already-resolved approval to a
        # different terminal decision. Callers that need to overturn a
        # decision must open a new approval (or use the unblock path) so the
        # audit trail remains accurate.
        if (
            prior_status in {"approved", "rejected"}
            and target_status in {"approved", "rejected"}
            and prior_status != target_status
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "Approval is already resolved; refusing conflicting "
                        "terminal decision."
                    ),
                    "approval_id": str(approval.id),
                    "current_status": prior_status,
                    "requested_status": target_status,
                },
            )
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
            await _ensure_no_rejection_loop(
                session,
                board_id=board.id,
                task_ids=approval_task_ids or [],
            )
            history_event_to_record = HISTORY_EVENT_SUBMITTED
            history_task_ids_for_event = approval_task_ids or []
        elif target_status == "approved" and prior_status != "approved":
            task_ids_by_approval = await load_task_ids_by_approval(
                session, approval_ids=[approval.id]
            )
            approval_task_ids = task_ids_by_approval.get(approval.id)
            if not approval_task_ids and approval.task_id is not None:
                approval_task_ids = [approval.task_id]
            await _ensure_move_to_done_targets_in_review(
                session,
                board_id=board.id,
                action_type=approval.action_type,
                task_ids=approval_task_ids or [],
            )
            await _ensure_move_to_done_targets_have_delivery_contract(
                session,
                board_id=board.id,
                action_type=approval.action_type,
                task_ids=approval_task_ids or [],
            )
            history_event_to_record = HISTORY_EVENT_APPROVED
        elif target_status == "rejected" and prior_status != "rejected":
            history_event_to_record = HISTORY_EVENT_REJECTED
        approval.status = target_status
        if approval.status != "pending":
            approval.resolved_at = utcnow()
    if history_event_to_record is not None:
        if not history_task_ids_for_event:
            task_ids_by_approval = await load_task_ids_by_approval(
                session, approval_ids=[approval.id]
            )
            history_task_ids_for_event = (
                task_ids_by_approval.get(approval.id)
                or ([approval.task_id] if approval.task_id is not None else [])
            )
        await _record_approval_history_event(
            session,
            approval_id=approval.id,
            board_id=board.id,
            task_ids=history_task_ids_for_event,
            event_type=history_event_to_record,
            actor=actor,
        )
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


@router.post("/{approval_id}/unblock", response_model=OkResponse)
async def unblock_approval(
    approval_id: str,
    payload: ApprovalUnblock,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = Depends(require_user_or_agent),
) -> OkResponse:
    """Clear a rejection loop by recording an authenticated ``unblocked``
    event in ``approval_history``.

    Authorization: human users pass via ``require_user_or_agent``; board
    lead agents may also unblock. Ordinary worker agents get 403 — this
    is the explicit privileged state Codex called for in the v1 review.

    Effect: appends one ``unblocked`` row per linked task. The next
    ``_ensure_no_rejection_loop`` query sees the reset and lets the next
    pending submission through. A non-empty ``reason`` is required so
    the audit trail records why the loop was cut.
    """
    if actor.user is None and actor.agent is not None:
        if not actor.agent.is_board_lead:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Only board leads or human operators can unblock "
                    "rejection loops."
                ),
            )
    approval = await Approval.objects.by_id(approval_id).first(session)
    if approval is None or approval.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    task_ids_by_approval = await load_task_ids_by_approval(
        session, approval_ids=[approval.id]
    )
    approval_task_ids = task_ids_by_approval.get(approval.id)
    if not approval_task_ids and approval.task_id is not None:
        approval_task_ids = [approval.task_id]
    await _record_approval_history_event(
        session,
        approval_id=approval.id,
        board_id=board.id,
        task_ids=approval_task_ids or [],
        event_type=HISTORY_EVENT_UNBLOCKED,
        actor=actor,
        message=payload.reason,
    )
    await session.commit()
    return OkResponse()
