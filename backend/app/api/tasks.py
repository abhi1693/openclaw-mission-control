from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import json
import re
from collections import deque
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import asc, desc, delete
from sqlmodel import Session, col, select

from app.api.deps import (
    ActorContext,
    get_board_or_404,
    get_task_or_404,
    require_admin_auth,
    require_admin_or_agent,
)
from app.core.auth import AuthContext
from app.db.session import engine, get_session
from app.integrations.openclaw_gateway import (
    GatewayConfig as GatewayClientConfig,
    OpenClawGatewayError,
    ensure_session,
    send_message,
)
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.tasks import Task
from app.models.task_fingerprints import TaskFingerprint
from app.schemas.tasks import TaskCommentCreate, TaskCommentRead, TaskCreate, TaskRead, TaskUpdate
from app.services.activity_log import record_activity

router = APIRouter(prefix="/boards/{board_id}/tasks", tags=["tasks"])

ALLOWED_STATUSES = {"inbox", "in_progress", "review", "done"}
TASK_EVENT_TYPES = {
    "task.created",
    "task.updated",
    "task.status_changed",
    "task.comment",
}
SSE_SEEN_MAX = 2000
MENTION_PATTERN = re.compile(r"@([A-Za-z][\w-]{0,31})")


def validate_task_status(status_value: str) -> None:
    if status_value not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported task status.",
        )


def _comment_validation_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Comment is required.",
    )


def has_valid_recent_comment(
    session: Session,
    task: Task,
    agent_id: UUID | None,
    since: datetime | None,
) -> bool:
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
    event = session.exec(statement).first()
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
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _extract_mentions(message: str) -> set[str]:
    return {match.group(1).lower() for match in MENTION_PATTERN.finditer(message)}


def _matches_mention(agent: Agent, mentions: set[str]) -> bool:
    if not mentions:
        return False
    name = (agent.name or "").strip()
    if not name:
        return False
    normalized = name.lower()
    if normalized in mentions:
        return True
    first = normalized.split()[0]
    return first in mentions


def _lead_was_mentioned(
    session: Session,
    task: Task,
    lead: Agent,
) -> bool:
    statement = (
        select(ActivityEvent.message)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    for message in session.exec(statement):
        if not message:
            continue
        mentions = _extract_mentions(message)
        if _matches_mention(lead, mentions):
            return True
    return False


def _fetch_task_events(
    board_id: UUID,
    since: datetime,
) -> list[tuple[ActivityEvent, Task | None]]:
    with Session(engine) as session:
        task_ids = list(
            session.exec(select(Task.id).where(col(Task.board_id) == board_id))
        )
        if not task_ids:
            return []
        statement = (
            select(ActivityEvent, Task)
            .outerjoin(Task, ActivityEvent.task_id == Task.id)
            .where(col(ActivityEvent.task_id).in_(task_ids))
            .where(col(ActivityEvent.event_type).in_(TASK_EVENT_TYPES))
            .where(col(ActivityEvent.created_at) >= since)
            .order_by(asc(col(ActivityEvent.created_at)))
        )
        return list(session.exec(statement))


def _serialize_task(task: Task | None) -> dict[str, object] | None:
    if task is None:
        return None
    return TaskRead.model_validate(task).model_dump(mode="json")


def _serialize_comment(event: ActivityEvent) -> dict[str, object]:
    return TaskCommentRead.model_validate(event).model_dump(mode="json")


def _gateway_config(session: Session, board: Board) -> GatewayClientConfig | None:
    if not board.gateway_id:
        return None
    gateway = session.get(Gateway, board.gateway_id)
    if gateway is None or not gateway.url:
        return None
    return GatewayClientConfig(url=gateway.url, token=gateway.token)


async def _send_lead_task_message(
    *,
    session_key: str,
    config: GatewayClientConfig,
    message: str,
) -> None:
    await ensure_session(session_key, config=config, label="Lead Agent")
    await send_message(message, session_key=session_key, config=config, deliver=False)


async def _send_agent_task_message(
    *,
    session_key: str,
    config: GatewayClientConfig,
    agent_name: str,
    message: str,
) -> None:
    await ensure_session(session_key, config=config, label=agent_name)
    await send_message(message, session_key=session_key, config=config, deliver=False)


def _notify_agent_on_task_assign(
    *,
    session: Session,
    board: Board,
    task: Task,
    agent: Agent,
) -> None:
    if not agent.openclaw_session_id:
        return
    config = _gateway_config(session, board)
    if config is None:
        return
    description = (task.description or "").strip()
    if len(description) > 500:
        description = f"{description[:497]}..."
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
        + "\n\nTake action: open the task and begin work. Post updates as task comments."
    )
    try:
        asyncio.run(
            _send_agent_task_message(
                session_key=agent.openclaw_session_id,
                config=config,
                agent_name=agent.name,
                message=message,
            )
        )
        record_activity(
            session,
            event_type="task.assignee_notified",
            message=f"Agent notified for assignment: {agent.name}.",
            agent_id=agent.id,
            task_id=task.id,
        )
        session.commit()
    except OpenClawGatewayError as exc:
        record_activity(
            session,
            event_type="task.assignee_notify_failed",
            message=f"Assignee notify failed: {exc}",
            agent_id=agent.id,
            task_id=task.id,
        )
        session.commit()


def _notify_lead_on_task_create(
    *,
    session: Session,
    board: Board,
    task: Task,
) -> None:
    lead = session.exec(
        select(Agent)
        .where(Agent.board_id == board.id)
        .where(Agent.is_board_lead.is_(True))
    ).first()
    if lead is None or not lead.openclaw_session_id:
        return
    config = _gateway_config(session, board)
    if config is None:
        return
    description = (task.description or "").strip()
    if len(description) > 500:
        description = f"{description[:497]}..."
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
    try:
        asyncio.run(
            _send_lead_task_message(
                session_key=lead.openclaw_session_id,
                config=config,
                message=message,
            )
        )
        record_activity(
            session,
            event_type="task.lead_notified",
            message=f"Lead agent notified for task: {task.title}.",
            agent_id=lead.id,
            task_id=task.id,
        )
        session.commit()
    except OpenClawGatewayError as exc:
        record_activity(
            session,
            event_type="task.lead_notify_failed",
            message=f"Lead notify failed: {exc}",
            agent_id=lead.id,
            task_id=task.id,
        )
        session.commit()


def _notify_lead_on_task_unassigned(
    *,
    session: Session,
    board: Board,
    task: Task,
) -> None:
    lead = session.exec(
        select(Agent)
        .where(Agent.board_id == board.id)
        .where(Agent.is_board_lead.is_(True))
    ).first()
    if lead is None or not lead.openclaw_session_id:
        return
    config = _gateway_config(session, board)
    if config is None:
        return
    description = (task.description or "").strip()
    if len(description) > 500:
        description = f"{description[:497]}..."
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
    try:
        asyncio.run(
            _send_lead_task_message(
                session_key=lead.openclaw_session_id,
                config=config,
                message=message,
            )
        )
        record_activity(
            session,
            event_type="task.lead_unassigned_notified",
            message=f"Lead notified task returned to inbox: {task.title}.",
            agent_id=lead.id,
            task_id=task.id,
        )
        session.commit()
    except OpenClawGatewayError as exc:
        record_activity(
            session,
            event_type="task.lead_unassigned_notify_failed",
            message=f"Lead notify failed: {exc}",
            agent_id=lead.id,
            task_id=task.id,
        )
        session.commit()


@router.get("/stream")
async def stream_tasks(
    request: Request,
    board: Board = Depends(get_board_or_404),
    actor: ActorContext = Depends(require_admin_or_agent),
    since: str | None = Query(default=None),
) -> EventSourceResponse:
    since_dt = _parse_since(since) or datetime.utcnow()
    seen_ids: set[UUID] = set()
    seen_queue: deque[UUID] = deque()

    async def event_generator():
        last_seen = since_dt
        while True:
            if await request.is_disconnected():
                break
            rows = await run_in_threadpool(_fetch_task_events, board.id, last_seen)
            for event, task in rows:
                if event.id in seen_ids:
                    continue
                seen_ids.add(event.id)
                seen_queue.append(event.id)
                if len(seen_queue) > SSE_SEEN_MAX:
                    oldest = seen_queue.popleft()
                    seen_ids.discard(oldest)
                if event.created_at > last_seen:
                    last_seen = event.created_at
                payload: dict[str, object] = {"type": event.event_type}
                if event.event_type == "task.comment":
                    payload["comment"] = _serialize_comment(event)
                else:
                    payload["task"] = _serialize_task(task)
                yield {"event": "task", "data": json.dumps(payload)}
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator(), ping=15)


@router.get("", response_model=list[TaskRead])
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    assigned_agent_id: UUID | None = None,
    unassigned: bool | None = None,
    limit: int | None = Query(default=None, ge=1, le=200),
    board: Board = Depends(get_board_or_404),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> list[Task]:
    statement = select(Task).where(Task.board_id == board.id)
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        if statuses:
            if any(status_value not in ALLOWED_STATUSES for status_value in statuses):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Unsupported task status filter.",
                )
            statement = statement.where(col(Task.status).in_(statuses))
    if assigned_agent_id is not None:
        statement = statement.where(col(Task.assigned_agent_id) == assigned_agent_id)
    if unassigned:
        statement = statement.where(col(Task.assigned_agent_id).is_(None))
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement))


@router.post("", response_model=TaskRead)
def create_task(
    payload: TaskCreate,
    board: Board = Depends(get_board_or_404),
    session: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> Task:
    validate_task_status(payload.status)
    task = Task.model_validate(payload)
    task.board_id = board.id
    if task.created_by_user_id is None and auth.user is not None:
        task.created_by_user_id = auth.user.id
    session.add(task)
    session.commit()
    session.refresh(task)

    record_activity(
        session,
        event_type="task.created",
        task_id=task.id,
        message=f"Task created: {task.title}.",
    )
    session.commit()
    _notify_lead_on_task_create(session=session, board=board, task=task)
    if task.assigned_agent_id:
        assigned_agent = session.get(Agent, task.assigned_agent_id)
        if assigned_agent:
            _notify_agent_on_task_assign(
                session=session,
                board=board,
                task=task,
                agent=assigned_agent,
            )
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    payload: TaskUpdate,
    task: Task = Depends(get_task_or_404),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> Task:
    previous_status = task.status
    previous_assigned = task.assigned_agent_id
    updates = payload.model_dump(exclude_unset=True)
    comment = updates.pop("comment", None)
    if comment is not None and not comment.strip():
        comment = None

    if actor.actor_type == "agent" and actor.agent and actor.agent.is_board_lead:
        allowed_fields = {"assigned_agent_id", "status"}
        if comment is not None or not set(updates).issubset(allowed_fields):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board leads can only assign or unassign tasks.",
            )
        if "assigned_agent_id" in updates:
            assigned_id = updates["assigned_agent_id"]
            if assigned_id:
                agent = session.get(Agent, assigned_id)
                if agent is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
                if agent.is_board_lead:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Board leads cannot assign tasks to themselves.",
                    )
                if agent.board_id and task.board_id and agent.board_id != task.board_id:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT)
                task.assigned_agent_id = agent.id
            else:
                task.assigned_agent_id = None
        if "status" in updates:
            validate_task_status(updates["status"])
            if task.status != "review":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Board leads can only change status when a task is in review.",
                )
            if updates["status"] not in {"done", "inbox"}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Board leads can only move review tasks to done or inbox.",
                )
            if updates["status"] == "inbox":
                task.assigned_agent_id = None
                task.in_progress_at = None
            task.status = updates["status"]
        task.updated_at = datetime.utcnow()
        session.add(task)
        if task.status != previous_status:
            event_type = "task.status_changed"
            message = f"Task moved to {task.status}: {task.title}."
        else:
            event_type = "task.updated"
            message = f"Task updated: {task.title}."
        record_activity(
            session,
            event_type=event_type,
            task_id=task.id,
            message=message,
            agent_id=actor.agent.id,
        )
        session.commit()
        session.refresh(task)
        return task
    if actor.actor_type == "agent":
        if actor.agent and actor.agent.board_id and task.board_id:
            if actor.agent.board_id != task.board_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        allowed_fields = {"status", "comment"}
        if not set(updates).issubset(allowed_fields):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if "status" in updates:
            validate_task_status(updates["status"])
            if updates["status"] == "inbox":
                task.assigned_agent_id = None
                task.in_progress_at = None
            else:
                task.assigned_agent_id = actor.agent.id if actor.agent else None
                if updates["status"] == "in_progress":
                    task.in_progress_at = datetime.utcnow()
    elif "status" in updates:
        validate_task_status(updates["status"])
        if updates["status"] == "inbox":
            task.assigned_agent_id = None
            task.in_progress_at = None
        elif updates["status"] == "in_progress":
            task.in_progress_at = datetime.utcnow()
    if "assigned_agent_id" in updates and updates["assigned_agent_id"]:
        agent = session.get(Agent, updates["assigned_agent_id"])
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if agent.board_id and task.board_id and agent.board_id != task.board_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    for key, value in updates.items():
        setattr(task, key, value)
    task.updated_at = datetime.utcnow()

    if "status" in updates and updates["status"] == "review":
        if comment is not None and comment.strip():
            if not comment.strip():
                raise _comment_validation_error()
        else:
            if not has_valid_recent_comment(
                session,
                task,
                task.assigned_agent_id,
                task.in_progress_at,
            ):
                raise _comment_validation_error()

    session.add(task)
    session.commit()
    session.refresh(task)

    if comment is not None and comment.strip():
        event = ActivityEvent(
            event_type="task.comment",
            message=comment,
            task_id=task.id,
            agent_id=actor.agent.id if actor.actor_type == "agent" and actor.agent else None,
        )
        session.add(event)
        session.commit()

    if "status" in updates and task.status != previous_status:
        event_type = "task.status_changed"
        message = f"Task moved to {task.status}: {task.title}."
    else:
        event_type = "task.updated"
        message = f"Task updated: {task.title}."
    record_activity(
        session,
        event_type=event_type,
        task_id=task.id,
        message=message,
        agent_id=actor.agent.id if actor.actor_type == "agent" and actor.agent else None,
    )
    session.commit()
    if task.status == "inbox" and task.assigned_agent_id is None:
        if previous_status != "inbox" or previous_assigned is not None:
            board = session.get(Board, task.board_id) if task.board_id else None
            if board:
                _notify_lead_on_task_unassigned(
                    session=session,
                    board=board,
                    task=task,
                )
    if task.assigned_agent_id and task.assigned_agent_id != previous_assigned:
        if (
            actor.actor_type == "agent"
            and actor.agent
            and task.assigned_agent_id == actor.agent.id
        ):
            return task
        assigned_agent = session.get(Agent, task.assigned_agent_id)
        if assigned_agent:
            board = session.get(Board, task.board_id) if task.board_id else None
            if board:
                _notify_agent_on_task_assign(
                    session=session,
                    board=board,
                    task=task,
                    agent=assigned_agent,
                )
    return task


@router.delete("/{task_id}")
def delete_task(
    session: Session = Depends(get_session),
    task: Task = Depends(get_task_or_404),
    auth: AuthContext = Depends(require_admin_auth),
) -> dict[str, bool]:
    session.execute(delete(ActivityEvent).where(col(ActivityEvent.task_id) == task.id))
    session.execute(delete(TaskFingerprint).where(col(TaskFingerprint.task_id) == task.id))
    session.delete(task)
    session.commit()
    return {"ok": True}


@router.get("/{task_id}/comments", response_model=list[TaskCommentRead])
def list_task_comments(
    task: Task = Depends(get_task_or_404),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> list[ActivityEvent]:
    if actor.actor_type == "agent" and actor.agent:
        if actor.agent.board_id and task.board_id and actor.agent.board_id != task.board_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    statement = (
        select(ActivityEvent)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .order_by(asc(col(ActivityEvent.created_at)))
    )
    return list(session.exec(statement))


@router.post("/{task_id}/comments", response_model=TaskCommentRead)
def create_task_comment(
    payload: TaskCommentCreate,
    task: Task = Depends(get_task_or_404),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> ActivityEvent:
    if actor.actor_type == "agent" and actor.agent:
        if actor.agent.is_board_lead and task.status != "review":
            if not _lead_was_mentioned(session, task, actor.agent):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Board leads can only comment during review or when mentioned."
                    ),
                )
        if actor.agent.board_id and task.board_id and actor.agent.board_id != task.board_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if not payload.message.strip():
        raise _comment_validation_error()
    event = ActivityEvent(
        event_type="task.comment",
        message=payload.message,
        task_id=task.id,
        agent_id=actor.agent.id if actor.actor_type == "agent" and actor.agent else None,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    mention_names = _extract_mentions(payload.message)
    targets: dict[UUID, Agent] = {}
    if task.assigned_agent_id:
        assigned_agent = session.get(Agent, task.assigned_agent_id)
        if assigned_agent:
            targets[assigned_agent.id] = assigned_agent
    if mention_names and task.board_id:
        statement = select(Agent).where(col(Agent.board_id) == task.board_id)
        for agent in session.exec(statement):
            if _matches_mention(agent, mention_names):
                targets[agent.id] = agent
    if actor.actor_type == "agent" and actor.agent:
        targets.pop(actor.agent.id, None)
    if targets:
        board = session.get(Board, task.board_id) if task.board_id else None
        config = _gateway_config(session, board) if board else None
        if board and config:
            snippet = payload.message.strip()
            if len(snippet) > 500:
                snippet = f"{snippet[:497]}..."
            actor_name = (
                actor.agent.name
                if actor.actor_type == "agent" and actor.agent
                else "User"
            )
            for agent in targets.values():
                if not agent.openclaw_session_id:
                    continue
                mentioned = _matches_mention(agent, mention_names)
                header = "TASK MENTION" if mentioned else "NEW TASK COMMENT"
                action_line = (
                    "You were mentioned in this comment."
                    if mentioned
                    else "A new comment was posted on your task."
                )
                message = (
                    f"{header}\n"
                    f"Board: {board.name}\n"
                    f"Task: {task.title}\n"
                    f"Task ID: {task.id}\n"
                    f"From: {actor_name}\n\n"
                    f"{action_line}\n\n"
                    f"Comment:\n{snippet}\n\n"
                    "If you are mentioned but not assigned, reply in the task thread but do not change task status."
                )
                try:
                    asyncio.run(
                        _send_agent_task_message(
                            session_key=agent.openclaw_session_id,
                            config=config,
                            agent_name=agent.name,
                            message=message,
                        )
                    )
                except OpenClawGatewayError:
                    pass
    return event
