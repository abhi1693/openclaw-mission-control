"""Agent-scoped API routes for board operations and gateway coordination."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import SQLModel, col, select

from app.api import agents as agents_api
from app.api import approvals as approvals_api
from app.api import board_memory as board_memory_api
from app.api import board_onboarding as onboarding_api
from app.api import tasks as tasks_api
from app.api.deps import ActorContext, get_board_or_404, get_task_or_404
from app.core.agent_auth import AgentAuthContext, get_agent_auth_context
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tags import Tag
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.schemas.agents import (
    AgentCreate,
    AgentHeartbeat,
    AgentHeartbeatCreate,
    AgentNudge,
    AgentRead,
)
from app.schemas.approvals import ApprovalCreate, ApprovalRead, ApprovalStatus
from app.schemas.board_memory import BoardMemoryCreate, BoardMemoryRead
from app.schemas.board_onboarding import BoardOnboardingAgentUpdate, BoardOnboardingRead
from app.schemas.boards import BoardRead
from app.schemas.common import OkResponse
from app.schemas.gateway_coordination import (
    GatewayLeadBroadcastRequest,
    GatewayLeadBroadcastResponse,
    GatewayLeadMessageRequest,
    GatewayLeadMessageResponse,
    GatewayMainAskUserRequest,
    GatewayMainAskUserResponse,
)
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.tags import TagRef
from app.schemas.tasks import TaskCommentCreate, TaskCommentRead, TaskCreate, TaskRead, TaskUpdate
from app.services.activity_log import record_activity
from app.services.openclaw.coordination_service import GatewayCoordinationService
from app.services.openclaw.policies import OpenClawAuthorizationPolicy
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.services.tags import replace_tags, validate_tag_ids
from app.services.task_dependencies import (
    blocked_by_dependency_ids,
    dependency_status_by_id,
    validate_dependency_update,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.activity_events import ActivityEvent
    from app.models.board_memory import BoardMemory
    from app.models.board_onboarding import BoardOnboardingSession

router = APIRouter(prefix="/agent", tags=["agent"])
SESSION_DEP = Depends(get_session)
AGENT_CTX_DEP = Depends(get_agent_auth_context)
BOARD_DEP = Depends(get_board_or_404)
TASK_DEP = Depends(get_task_or_404)
BOARD_ID_QUERY = Query(default=None)
TASK_STATUS_QUERY = Query(default=None, alias="status")
IS_CHAT_QUERY = Query(default=None)
APPROVAL_STATUS_QUERY = Query(default=None, alias="status")

AGENT_LEAD_TAGS = cast("list[str | Enum]", ["agent-lead"])
AGENT_MAIN_TAGS = cast("list[str | Enum]", ["agent-main"])
AGENT_BOARD_TAGS = cast("list[str | Enum]", ["agent-lead", "agent-worker"])
AGENT_ALL_ROLE_TAGS = cast("list[str | Enum]", ["agent-lead", "agent-worker", "agent-main"])


def _coerce_agent_items(items: Sequence[Any]) -> list[Agent]:
    agents: list[Agent] = []
    for item in items:
        if not isinstance(item, Agent):
            msg = "Expected Agent items from paginated query"
            raise TypeError(msg)
        agents.append(item)
    return agents


class SoulUpdateRequest(SQLModel):
    """Payload for updating an agent SOUL document."""

    content: str
    source_url: str | None = None
    reason: str | None = None


class AgentTaskListFilters(SQLModel):
    """Query filters for board task listing in agent routes."""

    status_filter: str | None = None
    assigned_agent_id: UUID | None = None
    unassigned: bool | None = None


def _task_list_filters(
    status_filter: str | None = TASK_STATUS_QUERY,
    assigned_agent_id: UUID | None = None,
    unassigned: bool | None = None,
) -> AgentTaskListFilters:
    return AgentTaskListFilters(
        status_filter=status_filter,
        assigned_agent_id=assigned_agent_id,
        unassigned=unassigned,
    )


TASK_LIST_FILTERS_DEP = Depends(_task_list_filters)


def _actor(agent_ctx: AgentAuthContext) -> ActorContext:
    return ActorContext(actor_type="agent", agent=agent_ctx.agent)


def _guard_board_access(agent_ctx: AgentAuthContext, board: Board) -> None:
    allowed = not (agent_ctx.agent.board_id and agent_ctx.agent.board_id != board.id)
    OpenClawAuthorizationPolicy.require_board_write_access(allowed=allowed)


def _require_board_lead(agent_ctx: AgentAuthContext) -> Agent:
    return OpenClawAuthorizationPolicy.require_board_lead_actor(
        actor_agent=agent_ctx.agent,
        detail="Only board leads can perform this action",
    )


def _guard_task_access(agent_ctx: AgentAuthContext, task: Task) -> None:
    allowed = not (
        agent_ctx.agent.board_id and task.board_id and agent_ctx.agent.board_id != task.board_id
    )
    OpenClawAuthorizationPolicy.require_board_write_access(allowed=allowed)


@router.get(
    "/boards",
    response_model=DefaultLimitOffsetPage[BoardRead],
    tags=AGENT_ALL_ROLE_TAGS,
)
async def list_boards(
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> LimitOffsetPage[BoardRead]:
    """List boards visible to the authenticated agent.

    Board-scoped agents typically see only their assigned board.
    Main agents may see multiple boards when permitted by auth scope.
    """
    statement = select(Board)
    if agent_ctx.agent.board_id:
        statement = statement.where(col(Board.id) == agent_ctx.agent.board_id)
    statement = statement.order_by(col(Board.created_at).desc())
    return await paginate(session, statement)


@router.get("/boards/{board_id}", response_model=BoardRead, tags=AGENT_ALL_ROLE_TAGS)
def get_board(
    board: Board = BOARD_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> Board:
    """Return one board if the authenticated agent can access it.

    Use this when an agent needs board metadata (objective, status, target date)
    before planning or posting updates.
    """
    _guard_board_access(agent_ctx, board)
    return board


@router.get(
    "/agents",
    response_model=DefaultLimitOffsetPage[AgentRead],
    tags=AGENT_ALL_ROLE_TAGS,
)
async def list_agents(
    board_id: UUID | None = BOARD_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> LimitOffsetPage[AgentRead]:
    """List agents visible to the caller, optionally filtered by board.

    Useful for lead delegation and workload balancing.
    """
    statement = select(Agent)
    if agent_ctx.agent.board_id:
        if board_id:
            OpenClawAuthorizationPolicy.require_board_write_access(
                allowed=board_id == agent_ctx.agent.board_id,
            )
        statement = statement.where(Agent.board_id == agent_ctx.agent.board_id)
    elif board_id:
        statement = statement.where(Agent.board_id == board_id)
    statement = statement.order_by(col(Agent.created_at).desc())

    def _transform(items: Sequence[Any]) -> Sequence[Any]:
        agents = _coerce_agent_items(items)
        return [
            AgentLifecycleService.to_agent_read(
                AgentLifecycleService.with_computed_status(agent),
            )
            for agent in agents
        ]

    return await paginate(session, statement, transformer=_transform)


@router.get(
    "/boards/{board_id}/tasks",
    response_model=DefaultLimitOffsetPage[TaskRead],
    tags=AGENT_BOARD_TAGS,
)
async def list_tasks(
    filters: AgentTaskListFilters = TASK_LIST_FILTERS_DEP,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> LimitOffsetPage[TaskRead]:
    """List tasks on a board with status/assignment filters.

    Common patterns:
    - worker: fetch assigned inbox/in-progress tasks
    - lead: fetch unassigned inbox tasks for delegation
    """
    _guard_board_access(agent_ctx, board)
    return await tasks_api.list_tasks(
        status_filter=filters.status_filter,
        assigned_agent_id=filters.assigned_agent_id,
        unassigned=filters.unassigned,
        board=board,
        session=session,
        _actor=_actor(agent_ctx),
    )


@router.get("/boards/{board_id}/tags", response_model=list[TagRef], tags=AGENT_BOARD_TAGS)
async def list_tags(
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> list[TagRef]:
    """List available tags for the board's organization.

    Use returned ids in task create/update payloads (`tag_ids`).
    """
    _guard_board_access(agent_ctx, board)
    tags = (
        await session.exec(
            select(Tag)
            .where(col(Tag.organization_id) == board.organization_id)
            .order_by(func.lower(col(Tag.name)).asc(), col(Tag.created_at).asc()),
        )
    ).all()
    return [
        TagRef(
            id=tag.id,
            name=tag.name,
            slug=tag.slug,
            color=tag.color,
        )
        for tag in tags
    ]


@router.post("/boards/{board_id}/tasks", response_model=TaskRead, tags=AGENT_LEAD_TAGS)
async def create_task(
    payload: TaskCreate,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> TaskRead:
    """Create a task as the board lead.

    Lead-only endpoint. Supports dependency-aware creation via
    `depends_on_task_ids`, optional `tag_ids`, and `custom_field_values`.
    """
    _guard_board_access(agent_ctx, board)
    _require_board_lead(agent_ctx)
    data = payload.model_dump(
        exclude={"depends_on_task_ids", "tag_ids", "custom_field_values"},
    )
    depends_on_task_ids = list(payload.depends_on_task_ids)
    tag_ids = list(payload.tag_ids)
    custom_field_values = dict(payload.custom_field_values)

    task = Task.model_validate(data)
    task.board_id = board.id
    task.auto_created = True
    task.auto_reason = f"lead_agent:{agent_ctx.agent.id}"

    normalized_deps = await validate_dependency_update(
        session,
        board_id=board.id,
        task_id=task.id,
        depends_on_task_ids=depends_on_task_ids,
    )
    normalized_tag_ids = await validate_tag_ids(
        session,
        organization_id=board.organization_id,
        tag_ids=tag_ids,
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Task is blocked by incomplete dependencies.",
                "blocked_by_task_ids": [str(value) for value in blocked_by],
            },
        )
    if task.assigned_agent_id:
        agent = await Agent.objects.by_id(task.assigned_agent_id).first(session)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if agent.is_board_lead:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board leads cannot assign tasks to themselves.",
            )
        if agent.board_id and agent.board_id != board.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    session.add(task)
    # Ensure the task exists in the DB before inserting dependency rows.
    await session.flush()
    await tasks_api._set_task_custom_field_values_for_create(
        session,
        board_id=board.id,
        task_id=task.id,
        custom_field_values=custom_field_values,
    )
    for dep_id in normalized_deps:
        session.add(
            TaskDependency(
                board_id=board.id,
                task_id=task.id,
                depends_on_task_id=dep_id,
            ),
        )
    await replace_tags(
        session,
        task_id=task.id,
        tag_ids=normalized_tag_ids,
    )
    await session.commit()
    await session.refresh(task)
    record_activity(
        session,
        event_type="task.created",
        task_id=task.id,
        message=f"Task created by lead: {task.title}.",
        agent_id=agent_ctx.agent.id,
    )
    await session.commit()
    if task.assigned_agent_id:
        assigned_agent = await Agent.objects.by_id(task.assigned_agent_id).first(
            session,
        )
        if assigned_agent:
            await tasks_api.notify_agent_on_task_assign(
                session=session,
                board=board,
                task=task,
                agent=assigned_agent,
            )
    return await tasks_api._task_read_response(
        session,
        task=task,
        board_id=board.id,
    )


@router.patch(
    "/boards/{board_id}/tasks/{task_id}",
    response_model=TaskRead,
    tags=AGENT_BOARD_TAGS,
)
async def update_task(
    payload: TaskUpdate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> TaskRead:
    """Update a task after board-level authorization checks.

    Supports status, assignment, dependencies, and optional inline comment.
    """
    _guard_task_access(agent_ctx, task)
    return await tasks_api.update_task(
        payload=payload,
        task=task,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get(
    "/boards/{board_id}/tasks/{task_id}/comments",
    response_model=DefaultLimitOffsetPage[TaskCommentRead],
    tags=AGENT_BOARD_TAGS,
)
async def list_task_comments(
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> LimitOffsetPage[TaskCommentRead]:
    """List task comments visible to the authenticated agent.

    Read this before posting updates to avoid duplicate or low-value comments.
    """
    _guard_task_access(agent_ctx, task)
    return await tasks_api.list_task_comments(
        task=task,
        session=session,
    )


@router.post(
    "/boards/{board_id}/tasks/{task_id}/comments",
    response_model=TaskCommentRead,
    tags=AGENT_BOARD_TAGS,
)
async def create_task_comment(
    payload: TaskCommentCreate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> ActivityEvent:
    """Create a task comment as the authenticated agent.

    This is the primary collaboration/log surface for task progress.
    """
    _guard_task_access(agent_ctx, task)
    return await tasks_api.create_task_comment(
        payload=payload,
        task=task,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get(
    "/boards/{board_id}/memory",
    response_model=DefaultLimitOffsetPage[BoardMemoryRead],
    tags=AGENT_BOARD_TAGS,
)
async def list_board_memory(
    is_chat: bool | None = IS_CHAT_QUERY,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> LimitOffsetPage[BoardMemoryRead]:
    """List board memory with optional chat filtering.

    Use `is_chat=false` for durable context and `is_chat=true` for board chat.
    """
    _guard_board_access(agent_ctx, board)
    return await board_memory_api.list_board_memory(
        is_chat=is_chat,
        board=board,
        session=session,
        _actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/memory", response_model=BoardMemoryRead, tags=AGENT_BOARD_TAGS)
async def create_board_memory(
    payload: BoardMemoryCreate,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> BoardMemory:
    """Create a board memory entry.

    Use tags to indicate purpose (e.g. `chat`, `decision`, `plan`, `handoff`).
    """
    _guard_board_access(agent_ctx, board)
    return await board_memory_api.create_board_memory(
        payload=payload,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get(
    "/boards/{board_id}/approvals",
    response_model=DefaultLimitOffsetPage[ApprovalRead],
    tags=AGENT_BOARD_TAGS,
)
async def list_approvals(
    status_filter: ApprovalStatus | None = APPROVAL_STATUS_QUERY,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> LimitOffsetPage[ApprovalRead]:
    """List approvals for a board.

    Use status filtering to process pending approvals efficiently.
    """
    _guard_board_access(agent_ctx, board)
    return await approvals_api.list_approvals(
        status_filter=status_filter,
        board=board,
        session=session,
        _actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/approvals", response_model=ApprovalRead, tags=AGENT_BOARD_TAGS)
async def create_approval(
    payload: ApprovalCreate,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> ApprovalRead:
    """Create an approval request for risky or low-confidence actions.

    Include `task_id` or `task_ids` to scope the decision precisely.
    """
    _guard_board_access(agent_ctx, board)
    return await approvals_api.create_approval(
        payload=payload,
        board=board,
        session=session,
        _actor=_actor(agent_ctx),
    )


@router.post(
    "/boards/{board_id}/onboarding",
    response_model=BoardOnboardingRead,
    tags=AGENT_BOARD_TAGS,
)
async def update_onboarding(
    payload: BoardOnboardingAgentUpdate,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> BoardOnboardingSession:
    """Apply board onboarding updates from an agent workflow.

    Used during structured objective/success-metric intake loops.
    """
    _guard_board_access(agent_ctx, board)
    return await onboarding_api.agent_onboarding_update(
        payload=payload,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/agents", response_model=AgentRead, tags=AGENT_LEAD_TAGS)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> AgentRead:
    """Create a new board agent as lead.

    The new agent is always forced onto the caller's board (`board_id` override).
    """
    lead = _require_board_lead(agent_ctx)
    payload = AgentCreate(
        **{**payload.model_dump(), "board_id": lead.board_id},
    )
    return await agents_api.create_agent(
        payload=payload,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post(
    "/boards/{board_id}/agents/{agent_id}/nudge",
    response_model=OkResponse,
    tags=AGENT_LEAD_TAGS,
)
async def nudge_agent(
    payload: AgentNudge,
    agent_id: str,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> OkResponse:
    """Send a direct nudge to one board agent.

    Lead-only endpoint for stale or blocked in-progress work.
    """
    _guard_board_access(agent_ctx, board)
    _require_board_lead(agent_ctx)
    coordination = GatewayCoordinationService(session)
    await coordination.nudge_board_agent(
        board=board,
        actor_agent=agent_ctx.agent,
        target_agent_id=agent_id,
        message=payload.message,
        correlation_id=f"nudge:{board.id}:{agent_id}",
    )
    return OkResponse()


@router.post("/heartbeat", response_model=AgentRead, tags=AGENT_ALL_ROLE_TAGS)
async def agent_heartbeat(
    payload: AgentHeartbeatCreate,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> AgentRead:
    """Record heartbeat status for the authenticated agent.

    Heartbeats are identity-bound to the token's agent id.
    """
    # Heartbeats must apply to the authenticated agent; agent names are not unique.
    return await agents_api.heartbeat_agent(
        agent_id=str(agent_ctx.agent.id),
        payload=AgentHeartbeat(status=payload.status),
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get(
    "/boards/{board_id}/agents/{agent_id}/soul",
    response_model=str,
    tags=AGENT_BOARD_TAGS,
)
async def get_agent_soul(
    agent_id: str,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> str:
    """Fetch an agent's SOUL.md content.

    Allowed for board lead, or for an agent reading its own SOUL.
    """
    _guard_board_access(agent_ctx, board)
    OpenClawAuthorizationPolicy.require_board_lead_or_same_actor(
        actor_agent=agent_ctx.agent,
        target_agent_id=agent_id,
    )
    coordination = GatewayCoordinationService(session)
    return await coordination.get_agent_soul(
        board=board,
        target_agent_id=agent_id,
        correlation_id=f"soul.read:{board.id}:{agent_id}",
    )


@router.put(
    "/boards/{board_id}/agents/{agent_id}/soul",
    response_model=OkResponse,
    tags=AGENT_LEAD_TAGS,
)
async def update_agent_soul(
    agent_id: str,
    payload: SoulUpdateRequest,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> OkResponse:
    """Update an agent's SOUL.md template in DB and gateway.

    Lead-only endpoint. Persists as `soul_template` for future reprovisioning.
    """
    _guard_board_access(agent_ctx, board)
    _require_board_lead(agent_ctx)
    coordination = GatewayCoordinationService(session)
    await coordination.update_agent_soul(
        board=board,
        target_agent_id=agent_id,
        content=payload.content,
        reason=payload.reason,
        source_url=payload.source_url,
        actor_agent_id=agent_ctx.agent.id,
        correlation_id=f"soul.write:{board.id}:{agent_id}",
    )
    return OkResponse()


@router.delete(
    "/boards/{board_id}/agents/{agent_id}",
    response_model=OkResponse,
    tags=AGENT_LEAD_TAGS,
)
async def delete_board_agent(
    agent_id: str,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> OkResponse:
    """Delete a board agent as board lead.

    Cleans up runtime/session state through lifecycle services.
    """
    _guard_board_access(agent_ctx, board)
    _require_board_lead(agent_ctx)
    service = AgentLifecycleService(session)
    return await service.delete_agent_as_lead(
        agent_id=agent_id,
        actor_agent=agent_ctx.agent,
    )


@router.post(
    "/boards/{board_id}/gateway/main/ask-user",
    response_model=GatewayMainAskUserResponse,
    tags=AGENT_LEAD_TAGS,
)
async def ask_user_via_gateway_main(
    payload: GatewayMainAskUserRequest,
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> GatewayMainAskUserResponse:
    """Ask the human via gateway-main external channels.

    Lead-only endpoint for situations where board chat is not responsive.
    """
    _guard_board_access(agent_ctx, board)
    _require_board_lead(agent_ctx)
    coordination = GatewayCoordinationService(session)
    return await coordination.ask_user_via_gateway_main(
        board=board,
        payload=payload,
        actor_agent=agent_ctx.agent,
    )


@router.post(
    "/gateway/boards/{board_id}/lead/message",
    response_model=GatewayLeadMessageResponse,
    tags=AGENT_MAIN_TAGS,
)
async def message_gateway_board_lead(
    board_id: UUID,
    payload: GatewayLeadMessageRequest,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> GatewayLeadMessageResponse:
    """Send a gateway-main control message to one board lead."""
    coordination = GatewayCoordinationService(session)
    return await coordination.message_gateway_board_lead(
        actor_agent=agent_ctx.agent,
        board_id=board_id,
        payload=payload,
    )


@router.post(
    "/gateway/leads/broadcast",
    response_model=GatewayLeadBroadcastResponse,
    tags=AGENT_MAIN_TAGS,
)
async def broadcast_gateway_lead_message(
    payload: GatewayLeadBroadcastRequest,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> GatewayLeadBroadcastResponse:
    """Broadcast a gateway-main control message to multiple board leads."""
    coordination = GatewayCoordinationService(session)
    return await coordination.broadcast_gateway_lead_message(
        actor_agent=agent_ctx.agent,
        payload=payload,
    )
