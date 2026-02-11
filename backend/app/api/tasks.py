"""Task API routes for listing, streaming, and mutating board tasks."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import asc, desc, or_
from sqlmodel import col, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_user_write,
    get_task_or_404,
    require_admin_auth,
    require_admin_or_agent,
)
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.tasks import Task
from app.schemas.common import OkResponse
from app.schemas.errors import BlockedTaskError
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.tasks import TaskCommentCreate, TaskCommentRead, TaskCreate, TaskRead, TaskUpdate
from app.services.activity_log import record_activity
from app.services.mentions import extract_mentions, matches_agent_mention
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.organizations import require_board_access
from app.services.task_dependencies import (
    blocked_by_dependency_ids,
    dependency_ids_by_task_id,
    dependency_status_by_id,
    dependent_task_ids,
    replace_task_dependencies,
    validate_dependency_update,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import SelectOfScalar

    from app.core.auth import AuthContext
    from app.models.users import User

router = APIRouter(prefix="/boards/{board_id}/tasks", tags=["tasks"])

ALLOWED_STATUSES = {"inbox", "in_progress", "review", "done"}
TASK_EVENT_TYPES = {
    "task.created",
    "task.updated",
    "task.status_changed",
    "task.comment",
}
SSE_SEEN_MAX = 2000
TASK_SNIPPET_MAX_LEN = 500
TASK_SNIPPET_TRUNCATED_LEN = 497
TASK_EVENT_ROW_LEN = 2
BOARD_READ_DEP = Depends(get_board_for_actor_read)
ACTOR_DEP = Depends(require_admin_or_agent)
SINCE_QUERY = Query(default=None)
STATUS_QUERY = Query(default=None, alias="status")
BOARD_WRITE_DEP = Depends(get_board_for_user_write)
SESSION_DEP = Depends(get_session)
ADMIN_AUTH_DEP = Depends(require_admin_auth)
TASK_DEP = Depends(get_task_or_404)


def _comment_validation_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Comment is required.",
    )


def _blocked_task_error(blocked_by_task_ids: Sequence[UUID]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "Task is blocked by incomplete dependencies.",
            "blocked_by_task_ids": [str(value) for value in blocked_by_task_ids],
        },
    )


def _truncate_snippet(value: str) -> str:
    text = value.strip()
    if len(text) <= TASK_SNIPPET_MAX_LEN:
        return text
    return f"{text[:TASK_SNIPPET_TRUNCATED_LEN]}..."


async def has_valid_recent_comment(
    session: AsyncSession,
    task: Task,
    agent_id: UUID | None,
    since: datetime | None,
) -> bool:
    """Check whether the task has a recent non-empty comment by the agent."""
    if agent_id is None or since is None:
        return False
    statement = (
        select(ActivityEvent)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.agent_id) == agent_id)
        .where(col(ActivityEvent.created_at) >= since)
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    event = (await session.exec(statement)).first()
    if event is None or event.message is None:
        return False
    return bool(event.message.strip())


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


def _coerce_task_items(items: Sequence[object]) -> list[Task]:
    tasks: list[Task] = []
    for item in items:
        if not isinstance(item, Task):
            msg = "Expected Task items from paginated query"
            raise TypeError(msg)
        tasks.append(item)
    return tasks


def _coerce_task_event_rows(
    items: Sequence[object],
) -> list[tuple[ActivityEvent, Task | None]]:
    rows: list[tuple[ActivityEvent, Task | None]] = []
    for item in items:
        first: object
        second: object

        if isinstance(item, tuple):
            if len(item) != TASK_EVENT_ROW_LEN:
                msg = "Expected (ActivityEvent, Task | None) rows"
                raise TypeError(msg)
            first, second = item
        else:
            try:
                row_len = len(item)  # type: ignore[arg-type]
                first = item[0]  # type: ignore[index]
                second = item[1]  # type: ignore[index]
            except (IndexError, KeyError, TypeError):
                msg = "Expected (ActivityEvent, Task | None) rows"
                raise TypeError(msg) from None
            if row_len != TASK_EVENT_ROW_LEN:
                msg = "Expected (ActivityEvent, Task | None) rows"
                raise TypeError(msg)

        if isinstance(first, ActivityEvent) and (isinstance(second, Task) or second is None):
            rows.append((first, second))
            continue

        msg = "Expected (ActivityEvent, Task | None) rows"
        raise TypeError(msg)
    return rows


async def _lead_was_mentioned(
    session: AsyncSession,
    task: Task,
    lead: Agent,
) -> bool:
    statement = (
        select(ActivityEvent.message)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    for message in await session.exec(statement):
        if not message:
            continue
        mentions = extract_mentions(message)
        if matches_agent_mention(lead, mentions):
            return True
    return False


def _lead_created_task(task: Task, lead: Agent) -> bool:
    if not task.auto_created or not task.auto_reason:
        return False
    return task.auto_reason == f"lead_agent:{lead.id}"


async def _reconcile_dependents_for_dependency_toggle(
    session: AsyncSession,
    *,
    board_id: UUID,
    dependency_task: Task,
    previous_status: str,
    actor_agent_id: UUID | None,
) -> None:
    done_toggled = (previous_status == "done") != (dependency_task.status == "done")
    if not done_toggled:
        return

    dependent_ids = await dependent_task_ids(
        session,
        board_id=board_id,
        dependency_task_id=dependency_task.id,
    )
    if not dependent_ids:
        return

    dependents = list(
        await session.exec(
            select(Task)
            .where(col(Task.board_id) == board_id)
            .where(col(Task.id).in_(dependent_ids)),
        ),
    )
    reopened = previous_status == "done" and dependency_task.status != "done"

    for dependent in dependents:
        if dependent.status == "done":
            continue
        if reopened:
            should_reset = (
                dependent.status != "inbox"
                or dependent.assigned_agent_id is not None
                or dependent.in_progress_at is not None
            )
            if should_reset:
                dependent.status = "inbox"
                dependent.assigned_agent_id = None
                dependent.in_progress_at = None
                dependent.updated_at = utcnow()
                session.add(dependent)
                record_activity(
                    session,
                    event_type="task.status_changed",
                    task_id=dependent.id,
                    message=(
                        "Task returned to inbox: dependency reopened " f"({dependency_task.title})."
                    ),
                    agent_id=actor_agent_id,
                )
            else:
                record_activity(
                    session,
                    event_type="task.updated",
                    task_id=dependent.id,
                    message=f"Dependency completion changed: {dependency_task.title}.",
                    agent_id=actor_agent_id,
                )
        else:
            record_activity(
                session,
                event_type="task.updated",
                task_id=dependent.id,
                message=f"Dependency completion changed: {dependency_task.title}.",
                agent_id=actor_agent_id,
            )


async def _fetch_task_events(
    session: AsyncSession,
    board_id: UUID,
    since: datetime,
) -> list[tuple[ActivityEvent, Task | None]]:
    task_ids = list(
        await session.exec(select(Task.id).where(col(Task.board_id) == board_id)),
    )
    if not task_ids:
        return []
    statement = (
        select(ActivityEvent, Task)
        .outerjoin(Task, col(ActivityEvent.task_id) == col(Task.id))
        .where(col(ActivityEvent.task_id).in_(task_ids))
        .where(col(ActivityEvent.event_type).in_(TASK_EVENT_TYPES))
        .where(col(ActivityEvent.created_at) >= since)
        .order_by(asc(col(ActivityEvent.created_at)))
    )
    result = await session.execute(statement)
    return _coerce_task_event_rows(list(result.tuples().all()))


def _serialize_comment(event: ActivityEvent) -> dict[str, object]:
    return TaskCommentRead.model_validate(event).model_dump(mode="json")


async def _send_lead_task_message(
    *,
    dispatch: GatewayDispatchService,
    session_key: str,
    config: GatewayClientConfig,
    message: str,
) -> OpenClawGatewayError | None:
    return await dispatch.try_send_agent_message(
        session_key=session_key,
        config=config,
        agent_name="Lead Agent",
        message=message,
        deliver=False,
    )


async def _send_agent_task_message(
    *,
    dispatch: GatewayDispatchService,
    session_key: str,
    config: GatewayClientConfig,
    agent_name: str,
    message: str,
) -> OpenClawGatewayError | None:
    return await dispatch.try_send_agent_message(
        session_key=session_key,
        config=config,
        agent_name=agent_name,
        message=message,
        deliver=False,
    )


async def _notify_agent_on_task_assign(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
) -> None:
    if not agent.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    message = (
        "TASK ASSIGNED\n"
        + "\n".join(details)
        + ("\n\nTake action: open the task and begin work. " "Post updates as task comments.")
    )
    error = await _send_agent_task_message(
        dispatch=dispatch,
        session_key=agent.openclaw_session_id,
        config=config,
        agent_name=agent.name,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.assignee_notified",
            message=f"Agent notified for assignment: {agent.name}.",
            agent_id=agent.id,
            task_id=task.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.assignee_notify_failed",
            message=f"Assignee notify failed: {error}",
            agent_id=agent.id,
            task_id=task.id,
        )
        await session.commit()


async def notify_agent_on_task_assign(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
) -> None:
    """Notify an assignee via gateway after task assignment."""
    await _notify_agent_on_task_assign(
        session=session,
        board=board,
        task=task,
        agent=agent,
    )


async def _notify_lead_on_task_create(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
) -> None:
    lead = (
        await Agent.objects.filter_by(board_id=board.id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    message = (
        "NEW TASK ADDED\n"
        + "\n".join(details)
        + "\n\nTake action: triage, assign, or plan next steps."
    )
    error = await _send_lead_task_message(
        dispatch=dispatch,
        session_key=lead.openclaw_session_id,
        config=config,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.lead_notified",
            message=f"Lead agent notified for task: {task.title}.",
            agent_id=lead.id,
            task_id=task.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.lead_notify_failed",
            message=f"Lead notify failed: {error}",
            agent_id=lead.id,
            task_id=task.id,
        )
        await session.commit()


async def _notify_lead_on_task_unassigned(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
) -> None:
    lead = (
        await Agent.objects.filter_by(board_id=board.id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    message = (
        "TASK BACK IN INBOX\n"
        + "\n".join(details)
        + "\n\nTake action: assign a new owner or adjust the plan."
    )
    error = await _send_lead_task_message(
        dispatch=dispatch,
        session_key=lead.openclaw_session_id,
        config=config,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.lead_unassigned_notified",
            message=f"Lead notified task returned to inbox: {task.title}.",
            agent_id=lead.id,
            task_id=task.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.lead_unassigned_notify_failed",
            message=f"Lead notify failed: {error}",
            agent_id=lead.id,
            task_id=task.id,
        )
        await session.commit()


def _status_values(status_filter: str | None) -> list[str]:
    if not status_filter:
        return []
    values = [s.strip() for s in status_filter.split(",") if s.strip()]
    if any(value not in ALLOWED_STATUSES for value in values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported task status filter.",
        )
    return values


def _task_list_statement(
    *,
    board_id: UUID,
    status_filter: str | None,
    assigned_agent_id: UUID | None,
    unassigned: bool | None,
) -> SelectOfScalar[Task]:
    statement = select(Task).where(Task.board_id == board_id)
    statuses = _status_values(status_filter)
    if statuses:
        statement = statement.where(col(Task.status).in_(statuses))
    if assigned_agent_id is not None:
        statement = statement.where(col(Task.assigned_agent_id) == assigned_agent_id)
    if unassigned:
        statement = statement.where(col(Task.assigned_agent_id).is_(None))
    return statement.order_by(col(Task.created_at).desc())


async def _task_read_page(
    *,
    session: AsyncSession,
    board_id: UUID,
    tasks: Sequence[Task],
) -> list[TaskRead]:
    if not tasks:
        return []

    task_ids = [task.id for task in tasks]
    deps_map = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=task_ids,
    )
    dep_ids: list[UUID] = []
    for value in deps_map.values():
        dep_ids.extend(value)
    dep_status = await dependency_status_by_id(
        session,
        board_id=board_id,
        dependency_ids=list({*dep_ids}),
    )

    output: list[TaskRead] = []
    for task in tasks:
        dep_list = deps_map.get(task.id, [])
        blocked_by = blocked_by_dependency_ids(
            dependency_ids=dep_list,
            status_by_id=dep_status,
        )
        if task.status == "done":
            blocked_by = []
        output.append(
            TaskRead.model_validate(task, from_attributes=True).model_copy(
                update={
                    "depends_on_task_ids": dep_list,
                    "blocked_by_task_ids": blocked_by,
                    "is_blocked": bool(blocked_by),
                },
            ),
        )
    return output


async def _stream_dependency_state(
    session: AsyncSession,
    *,
    board_id: UUID,
    rows: list[tuple[ActivityEvent, Task | None]],
) -> tuple[dict[UUID, list[UUID]], dict[UUID, str]]:
    task_ids = [
        task.id for event, task in rows if task is not None and event.event_type != "task.comment"
    ]
    if not task_ids:
        return {}, {}

    deps_map = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=list({*task_ids}),
    )
    dep_ids: list[UUID] = []
    for value in deps_map.values():
        dep_ids.extend(value)
    if not dep_ids:
        return deps_map, {}

    dep_status = await dependency_status_by_id(
        session,
        board_id=board_id,
        dependency_ids=list({*dep_ids}),
    )
    return deps_map, dep_status


def _task_event_payload(
    event: ActivityEvent,
    task: Task | None,
    *,
    deps_map: dict[UUID, list[UUID]],
    dep_status: dict[UUID, str],
) -> dict[str, object]:
    payload: dict[str, object] = {"type": event.event_type}
    if event.event_type == "task.comment":
        payload["comment"] = _serialize_comment(event)
        return payload
    if task is None:
        payload["task"] = None
        return payload

    dep_list = deps_map.get(task.id, [])
    blocked_by = blocked_by_dependency_ids(
        dependency_ids=dep_list,
        status_by_id=dep_status,
    )
    if task.status == "done":
        blocked_by = []
    payload["task"] = (
        TaskRead.model_validate(task, from_attributes=True)
        .model_copy(
            update={
                "depends_on_task_ids": dep_list,
                "blocked_by_task_ids": blocked_by,
                "is_blocked": bool(blocked_by),
            },
        )
        .model_dump(mode="json")
    )
    return payload


async def _task_event_generator(
    *,
    request: Request,
    board_id: UUID,
    since_dt: datetime,
) -> AsyncIterator[dict[str, str]]:
    last_seen = since_dt
    seen_ids: set[UUID] = set()
    seen_queue: deque[UUID] = deque()

    while True:
        if await request.is_disconnected():
            break

        async with async_session_maker() as session:
            rows = await _fetch_task_events(session, board_id, last_seen)
            deps_map, dep_status = await _stream_dependency_state(
                session,
                board_id=board_id,
                rows=rows,
            )

        for event, task in rows:
            if event.id in seen_ids:
                continue
            seen_ids.add(event.id)
            seen_queue.append(event.id)
            if len(seen_queue) > SSE_SEEN_MAX:
                oldest = seen_queue.popleft()
                seen_ids.discard(oldest)
            last_seen = max(event.created_at, last_seen)

            payload = _task_event_payload(
                event,
                task,
                deps_map=deps_map,
                dep_status=dep_status,
            )
            yield {"event": "task", "data": json.dumps(payload)}
        await asyncio.sleep(2)


@router.get("/stream")
async def stream_tasks(
    request: Request,
    board: Board = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
    since: str | None = SINCE_QUERY,
) -> EventSourceResponse:
    """Stream task and task-comment events as SSE payloads."""
    since_dt = _parse_since(since) or utcnow()
    return EventSourceResponse(
        _task_event_generator(
            request=request,
            board_id=board.id,
            since_dt=since_dt,
        ),
        ping=15,
    )


@router.get("", response_model=DefaultLimitOffsetPage[TaskRead])
async def list_tasks(
    status_filter: str | None = STATUS_QUERY,
    assigned_agent_id: UUID | None = None,
    unassigned: bool | None = None,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> LimitOffsetPage[TaskRead]:
    """List board tasks with optional status and assignment filters."""
    statement = _task_list_statement(
        board_id=board.id,
        status_filter=status_filter,
        assigned_agent_id=assigned_agent_id,
        unassigned=unassigned,
    )

    async def _transform(items: Sequence[object]) -> Sequence[object]:
        tasks = _coerce_task_items(items)
        return await _task_read_page(
            session=session,
            board_id=board.id,
            tasks=tasks,
        )

    return await paginate(session, statement, transformer=_transform)


@router.post("", response_model=TaskRead, responses={409: {"model": BlockedTaskError}})
async def create_task(
    payload: TaskCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = ADMIN_AUTH_DEP,
) -> TaskRead:
    """Create a task and initialize dependency rows."""
    data = payload.model_dump(exclude={"depends_on_task_ids"})
    depends_on_task_ids = list(payload.depends_on_task_ids)

    task = Task.model_validate(data)
    task.board_id = board.id
    if task.created_by_user_id is None and auth.user is not None:
        task.created_by_user_id = auth.user.id

    normalized_deps = await validate_dependency_update(
        session,
        board_id=board.id,
        task_id=task.id,
        depends_on_task_ids=depends_on_task_ids,
    )
    dep_status = await dependency_status_by_id(
        session,
        board_id=board.id,
        dependency_ids=normalized_deps,
    )
    blocked_by = blocked_by_dependency_ids(
        dependency_ids=normalized_deps,
        status_by_id=dep_status,
    )
    if blocked_by and (task.assigned_agent_id is not None or task.status != "inbox"):
        raise _blocked_task_error(blocked_by)
    session.add(task)
    # Ensure the task exists in the DB before inserting dependency rows.
    await session.flush()
    for dep_id in normalized_deps:
        session.add(
            TaskDependency(
                board_id=board.id,
                task_id=task.id,
                depends_on_task_id=dep_id,
            ),
        )
    await session.commit()
    await session.refresh(task)

    record_activity(
        session,
        event_type="task.created",
        task_id=task.id,
        message=f"Task created: {task.title}.",
    )
    await session.commit()
    await _notify_lead_on_task_create(session=session, board=board, task=task)
    if task.assigned_agent_id:
        assigned_agent = await Agent.objects.by_id(task.assigned_agent_id).first(
            session,
        )
        if assigned_agent:
            await _notify_agent_on_task_assign(
                session=session,
                board=board,
                task=task,
                agent=assigned_agent,
            )
    return TaskRead.model_validate(task, from_attributes=True).model_copy(
        update={
            "depends_on_task_ids": normalized_deps,
            "blocked_by_task_ids": blocked_by,
            "is_blocked": bool(blocked_by),
        },
    )


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    responses={409: {"model": BlockedTaskError}},
)
async def update_task(
    payload: TaskUpdate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> TaskRead:
    """Update task status, assignment, comment, and dependency state."""
    if task.board_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task board_id is required.",
        )
    board_id = task.board_id
    if actor.actor_type == "user" and actor.user is not None:
        await _require_task_user_write_access(
            session,
            board_id=board_id,
            user=actor.user,
        )
    previous_status = task.status
    previous_assigned = task.assigned_agent_id
    updates = payload.model_dump(exclude_unset=True)
    comment = payload.comment if "comment" in payload.model_fields_set else None
    depends_on_task_ids = (
        payload.depends_on_task_ids if "depends_on_task_ids" in payload.model_fields_set else None
    )
    updates.pop("comment", None)
    updates.pop("depends_on_task_ids", None)
    update = _TaskUpdateInput(
        task=task,
        actor=actor,
        board_id=board_id,
        previous_status=previous_status,
        previous_assigned=previous_assigned,
        updates=updates,
        comment=comment,
        depends_on_task_ids=depends_on_task_ids,
    )
    if actor.actor_type == "agent" and actor.agent and actor.agent.is_board_lead:
        return await _apply_lead_task_update(session, update=update)

    if actor.actor_type == "agent":
        await _apply_non_lead_agent_task_rules(session, update=update)
    else:
        await _apply_admin_task_rules(session, update=update)
    return await _finalize_updated_task(
        session,
        update=update,
    )


@router.delete("/{task_id}", response_model=OkResponse)
async def delete_task(
    session: AsyncSession = SESSION_DEP,
    task: Task = TASK_DEP,
    auth: AuthContext = ADMIN_AUTH_DEP,
) -> OkResponse:
    """Delete a task and related records."""
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    board = await Board.objects.by_id(task.board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=True)
    await crud.delete_where(
        session,
        ActivityEvent,
        col(ActivityEvent.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskFingerprint,
        col(TaskFingerprint.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        Approval,
        col(Approval.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskDependency,
        or_(
            col(TaskDependency.task_id) == task.id,
            col(TaskDependency.depends_on_task_id) == task.id,
        ),
        commit=False,
    )
    await session.delete(task)
    await session.commit()
    return OkResponse()


@router.get(
    "/{task_id}/comments",
    response_model=DefaultLimitOffsetPage[TaskCommentRead],
)
async def list_task_comments(
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[TaskCommentRead]:
    """List comments for a task in chronological order."""
    statement = (
        select(ActivityEvent)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .order_by(asc(col(ActivityEvent.created_at)))
    )
    return await paginate(session, statement)


async def _validate_task_comment_access(
    session: AsyncSession,
    *,
    task: Task,
    actor: ActorContext,
) -> None:
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    if actor.actor_type == "user" and actor.user is not None:
        board = await Board.objects.by_id(task.board_id).first(session)
        if board is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await require_board_access(session, user=actor.user, board=board, write=True)

    if (
        actor.actor_type == "agent"
        and actor.agent
        and actor.agent.is_board_lead
        and task.status != "review"
        and not await _lead_was_mentioned(session, task, actor.agent)
        and not _lead_created_task(task, actor.agent)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Board leads can only comment during review, when mentioned, "
                "or on tasks they created."
            ),
        )


def _comment_actor_id(actor: ActorContext) -> UUID | None:
    if actor.actor_type == "agent" and actor.agent:
        return actor.agent.id
    return None


def _comment_actor_name(actor: ActorContext) -> str:
    if actor.actor_type == "agent" and actor.agent:
        return actor.agent.name
    return "User"


async def _comment_targets(
    session: AsyncSession,
    *,
    task: Task,
    message: str,
    actor: ActorContext,
) -> tuple[dict[UUID, Agent], set[str]]:
    mention_names = extract_mentions(message)
    targets: dict[UUID, Agent] = {}
    if mention_names and task.board_id:
        for agent in await Agent.objects.filter_by(board_id=task.board_id).all(session):
            if matches_agent_mention(agent, mention_names):
                targets[agent.id] = agent
    if not mention_names and task.assigned_agent_id:
        assigned_agent = await Agent.objects.by_id(task.assigned_agent_id).first(
            session,
        )
        if assigned_agent:
            targets[assigned_agent.id] = assigned_agent

    if actor.actor_type == "agent" and actor.agent:
        targets.pop(actor.agent.id, None)
    return targets, mention_names


@dataclass(frozen=True, slots=True)
class _TaskCommentNotifyRequest:
    task: Task
    actor: ActorContext
    message: str
    targets: dict[UUID, Agent]
    mention_names: set[str]


async def _notify_task_comment_targets(
    session: AsyncSession,
    *,
    request: _TaskCommentNotifyRequest,
) -> None:
    if not request.targets:
        return
    board = (
        await Board.objects.by_id(request.task.board_id).first(session)
        if request.task.board_id
        else None
    )
    if board is None:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if not config:
        return

    snippet = _truncate_snippet(request.message)
    actor_name = _comment_actor_name(request.actor)
    for agent in request.targets.values():
        if not agent.openclaw_session_id:
            continue
        mentioned = matches_agent_mention(agent, request.mention_names)
        header = "TASK MENTION" if mentioned else "NEW TASK COMMENT"
        action_line = (
            "You were mentioned in this comment."
            if mentioned
            else "A new comment was posted on your task."
        )
        notification = (
            f"{header}\n"
            f"Board: {board.name}\n"
            f"Task: {request.task.title}\n"
            f"Task ID: {request.task.id}\n"
            f"From: {actor_name}\n\n"
            f"{action_line}\n\n"
            f"Comment:\n{snippet}\n\n"
            "If you are mentioned but not assigned, reply in the task "
            "thread but do not change task status."
        )
        await _send_agent_task_message(
            dispatch=dispatch,
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=notification,
        )


@dataclass(slots=True)
class _TaskUpdateInput:
    task: Task
    actor: ActorContext
    board_id: UUID
    previous_status: str
    previous_assigned: UUID | None
    updates: dict[str, object]
    comment: str | None
    depends_on_task_ids: list[UUID] | None


def _required_status_value(value: object) -> str:
    if isinstance(value, str):
        return value
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _optional_assigned_agent_id(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


async def _task_dep_ids(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> list[UUID]:
    deps_map = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=[task_id],
    )
    return deps_map.get(task_id, [])


async def _task_blocked_ids(
    session: AsyncSession,
    *,
    board_id: UUID,
    dep_ids: Sequence[UUID],
) -> list[UUID]:
    if not dep_ids:
        return []
    dep_status = await dependency_status_by_id(
        session,
        board_id=board_id,
        dependency_ids=list(dep_ids),
    )
    return blocked_by_dependency_ids(
        dependency_ids=list(dep_ids),
        status_by_id=dep_status,
    )


async def _task_read_response(
    session: AsyncSession,
    *,
    task: Task,
    board_id: UUID,
) -> TaskRead:
    dep_ids = await _task_dep_ids(session, board_id=board_id, task_id=task.id)
    blocked_ids = await _task_blocked_ids(
        session,
        board_id=board_id,
        dep_ids=dep_ids,
    )
    if task.status == "done":
        blocked_ids = []
    return TaskRead.model_validate(task, from_attributes=True).model_copy(
        update={
            "depends_on_task_ids": dep_ids,
            "blocked_by_task_ids": blocked_ids,
            "is_blocked": bool(blocked_ids),
        },
    )


async def _require_task_user_write_access(
    session: AsyncSession,
    *,
    board_id: UUID,
    user: User | None,
) -> None:
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=user, board=board, write=True)


def _lead_requested_fields(update: _TaskUpdateInput) -> set[str]:
    requested_fields = set(update.updates)
    if update.comment is not None:
        requested_fields.add("comment")
    if update.depends_on_task_ids is not None:
        requested_fields.add("depends_on_task_ids")
    return requested_fields


def _validate_lead_update_request(update: _TaskUpdateInput) -> None:
    allowed_fields = {"assigned_agent_id", "status", "depends_on_task_ids"}
    requested_fields = _lead_requested_fields(update)
    if update.comment is not None or not requested_fields.issubset(allowed_fields):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Board leads can only assign/unassign tasks, update "
                "dependencies, or resolve review tasks."
            ),
        )


async def _lead_effective_dependencies(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> tuple[list[UUID], list[UUID]]:
    normalized_deps: list[UUID] | None = None
    if update.depends_on_task_ids is not None:
        if update.task.status == "done":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Cannot change task dependencies after a task is done."),
            )
        normalized_deps = await replace_task_dependencies(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
            depends_on_task_ids=update.depends_on_task_ids,
        )
    effective_deps = (
        normalized_deps
        if normalized_deps is not None
        else await _task_dep_ids(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
        )
    )
    blocked_by = await _task_blocked_ids(
        session,
        board_id=update.board_id,
        dep_ids=effective_deps,
    )
    return effective_deps, blocked_by


async def _lead_apply_assignment(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if "assigned_agent_id" not in update.updates:
        return
    assigned_id = _optional_assigned_agent_id(update.updates["assigned_agent_id"])
    if not assigned_id:
        update.task.assigned_agent_id = None
        return
    agent = await Agent.objects.by_id(assigned_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if agent.is_board_lead:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Board leads cannot assign tasks to themselves.",
        )
    if agent.board_id and update.task.board_id and agent.board_id != update.task.board_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    update.task.assigned_agent_id = agent.id


def _lead_apply_status(update: _TaskUpdateInput) -> None:
    if "status" not in update.updates:
        return
    if update.task.status != "review":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Board leads can only change status when a task is " "in review."),
        )
    target_status = _required_status_value(update.updates["status"])
    if target_status not in {"done", "inbox"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Board leads can only move review tasks to done " "or inbox."),
        )
    if target_status == "inbox":
        update.task.assigned_agent_id = None
        update.task.in_progress_at = None
    update.task.status = target_status


def _task_event_details(task: Task, previous_status: str) -> tuple[str, str]:
    if task.status != previous_status:
        return "task.status_changed", f"Task moved to {task.status}: {task.title}."
    return "task.updated", f"Task updated: {task.title}."


async def _lead_notify_new_assignee(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if (
        not update.task.assigned_agent_id
        or update.task.assigned_agent_id == update.previous_assigned
    ):
        return
    assigned_agent = await Agent.objects.by_id(update.task.assigned_agent_id).first(
        session,
    )
    if assigned_agent is None:
        return
    board = (
        await Board.objects.by_id(update.task.board_id).first(session)
        if update.task.board_id
        else None
    )
    if board:
        await _notify_agent_on_task_assign(
            session=session,
            board=board,
            task=update.task,
            agent=assigned_agent,
        )


async def _apply_lead_task_update(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> TaskRead:
    if update.actor.actor_type != "agent" or update.actor.agent is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    _validate_lead_update_request(update)
    _effective_deps, blocked_by = await _lead_effective_dependencies(
        session,
        update=update,
    )

    if blocked_by and update.task.status != "done":
        update.task.status = "inbox"
        update.task.assigned_agent_id = None
        update.task.in_progress_at = None
    else:
        await _lead_apply_assignment(session, update=update)
        _lead_apply_status(update)

    update.task.updated_at = utcnow()
    session.add(update.task)
    event_type, message = _task_event_details(update.task, update.previous_status)
    record_activity(
        session,
        event_type=event_type,
        task_id=update.task.id,
        message=message,
        agent_id=update.actor.agent.id,
    )
    await _reconcile_dependents_for_dependency_toggle(
        session,
        board_id=update.board_id,
        dependency_task=update.task,
        previous_status=update.previous_status,
        actor_agent_id=update.actor.agent.id,
    )
    await session.commit()
    await session.refresh(update.task)
    await _lead_notify_new_assignee(session, update=update)
    return await _task_read_response(
        session,
        task=update.task,
        board_id=update.board_id,
    )


async def _apply_non_lead_agent_task_rules(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.actor.actor_type != "agent":
        return
    if (
        update.actor.agent
        and update.actor.agent.board_id
        and update.task.board_id
        and update.actor.agent.board_id != update.task.board_id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    allowed_fields = {"status", "comment"}
    if update.depends_on_task_ids is not None or not set(update.updates).issubset(
        allowed_fields,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if "status" in update.updates:
        status_value = _required_status_value(update.updates["status"])
        if status_value != "inbox":
            dep_ids = await _task_dep_ids(
                session,
                board_id=update.board_id,
                task_id=update.task.id,
            )
            blocked_ids = await _task_blocked_ids(
                session,
                board_id=update.board_id,
                dep_ids=dep_ids,
            )
            if blocked_ids:
                raise _blocked_task_error(blocked_ids)
        if status_value == "inbox":
            update.task.assigned_agent_id = None
            update.task.in_progress_at = None
        else:
            update.task.assigned_agent_id = update.actor.agent.id if update.actor.agent else None
            if status_value == "in_progress":
                update.task.in_progress_at = utcnow()


async def _apply_admin_task_rules(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    admin_normalized_deps: list[UUID] | None = None
    if update.depends_on_task_ids is not None:
        if update.task.status == "done":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Cannot change task dependencies after a task is done."),
            )
        admin_normalized_deps = await replace_task_dependencies(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
            depends_on_task_ids=update.depends_on_task_ids,
        )

    effective_deps = (
        admin_normalized_deps
        if admin_normalized_deps is not None
        else await _task_dep_ids(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
        )
    )
    blocked_ids = await _task_blocked_ids(
        session,
        board_id=update.board_id,
        dep_ids=effective_deps,
    )
    target_status = _required_status_value(
        update.updates.get("status", update.task.status),
    )
    if blocked_ids and not (update.task.status == "done" and target_status == "done"):
        update.task.status = "inbox"
        update.task.assigned_agent_id = None
        update.task.in_progress_at = None
        update.updates["status"] = "inbox"
        update.updates["assigned_agent_id"] = None

    if "status" in update.updates:
        status_value = _required_status_value(update.updates["status"])
        if status_value == "inbox":
            update.task.assigned_agent_id = None
            update.task.in_progress_at = None
        elif status_value == "in_progress":
            update.task.in_progress_at = utcnow()

    assigned_agent_id = _optional_assigned_agent_id(
        update.updates.get("assigned_agent_id"),
    )
    if assigned_agent_id:
        agent = await Agent.objects.by_id(assigned_agent_id).first(session)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if agent.board_id and update.task.board_id and agent.board_id != update.task.board_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT)


async def _record_task_comment_from_update(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.comment is None or not update.comment.strip():
        return
    event = ActivityEvent(
        event_type="task.comment",
        message=update.comment,
        task_id=update.task.id,
        agent_id=(
            update.actor.agent.id
            if update.actor.actor_type == "agent" and update.actor.agent
            else None
        ),
    )
    session.add(event)
    await session.commit()


async def _record_task_update_activity(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    event_type, message = _task_event_details(update.task, update.previous_status)
    actor_agent_id = (
        update.actor.agent.id if update.actor.actor_type == "agent" and update.actor.agent else None
    )
    record_activity(
        session,
        event_type=event_type,
        task_id=update.task.id,
        message=message,
        agent_id=actor_agent_id,
    )
    await _reconcile_dependents_for_dependency_toggle(
        session,
        board_id=update.board_id,
        dependency_task=update.task,
        previous_status=update.previous_status,
        actor_agent_id=actor_agent_id,
    )
    await session.commit()


async def _notify_task_update_assignment_changes(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if (
        update.task.status == "inbox"
        and update.task.assigned_agent_id is None
        and (update.previous_status != "inbox" or update.previous_assigned is not None)
    ):
        board = (
            await Board.objects.by_id(update.task.board_id).first(session)
            if update.task.board_id
            else None
        )
        if board:
            await _notify_lead_on_task_unassigned(
                session=session,
                board=board,
                task=update.task,
            )

    if (
        not update.task.assigned_agent_id
        or update.task.assigned_agent_id == update.previous_assigned
    ):
        return
    if (
        update.actor.actor_type == "agent"
        and update.actor.agent
        and update.task.assigned_agent_id == update.actor.agent.id
    ):
        return
    assigned_agent = await Agent.objects.by_id(update.task.assigned_agent_id).first(
        session,
    )
    if assigned_agent is None:
        return
    board = (
        await Board.objects.by_id(update.task.board_id).first(session)
        if update.task.board_id
        else None
    )
    if board:
        await _notify_agent_on_task_assign(
            session=session,
            board=board,
            task=update.task,
            agent=assigned_agent,
        )


async def _finalize_updated_task(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> TaskRead:
    for key, value in update.updates.items():
        setattr(update.task, key, value)
    update.task.updated_at = utcnow()

    status_raw = update.updates.get("status")
    if status_raw == "review":
        comment_text = (update.comment or "").strip()
        if not comment_text and not await has_valid_recent_comment(
            session,
            update.task,
            update.task.assigned_agent_id,
            update.task.in_progress_at,
        ):
            raise _comment_validation_error()

    session.add(update.task)
    await session.commit()
    await session.refresh(update.task)
    await _record_task_comment_from_update(session, update=update)
    await _record_task_update_activity(session, update=update)
    await _notify_task_update_assignment_changes(session, update=update)

    return await _task_read_response(
        session,
        task=update.task,
        board_id=update.board_id,
    )


@router.post("/{task_id}/comments", response_model=TaskCommentRead)
async def create_task_comment(
    payload: TaskCommentCreate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> ActivityEvent:
    """Create a task comment and notify relevant agents."""
    await _validate_task_comment_access(session, task=task, actor=actor)
    event = ActivityEvent(
        event_type="task.comment",
        message=payload.message,
        task_id=task.id,
        agent_id=_comment_actor_id(actor),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    targets, mention_names = await _comment_targets(
        session,
        task=task,
        message=payload.message,
        actor=actor,
    )
    await _notify_task_comment_targets(
        session,
        request=_TaskCommentNotifyRequest(
            task=task,
            actor=actor,
            message=payload.message,
            targets=targets,
            mention_names=mention_names,
        ),
    )
    return event
