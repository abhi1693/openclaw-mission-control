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
from app.models.board_webhook_payloads import BoardWebhookPayload
from app.models.tags import Tag
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.schemas.agents import (
    AgentCreate,
    AgentHeartbeat,
    AgentNudge,
    AgentRead,
)
from app.schemas.approvals import ApprovalCreate, ApprovalRead, ApprovalStatus
from app.schemas.board_memory import BoardMemoryCreate, BoardMemoryRead
from app.schemas.board_onboarding import BoardOnboardingAgentUpdate, BoardOnboardingRead
from app.schemas.board_webhooks import BoardWebhookPayloadRead
from app.schemas.boards import BoardRead
from app.schemas.common import OkResponse
from app.schemas.errors import LLMErrorResponse
from app.schemas.gateway_coordination import (
    GatewayLeadBroadcastRequest,
    GatewayLeadBroadcastResponse,
    GatewayLeadMessageRequest,
    GatewayLeadMessageResponse,
    GatewayMainAskUserRequest,
    GatewayMainAskUserResponse,
)
from app.schemas.health import AgentHealthStatusResponse
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


def _agent_board_openapi_hints(
    *,
    intent: str,
    when_to_use: list[str],
    routing_examples: list[dict[str, object]],
    required_actor: str = "any_agent",
    when_not_to_use: list[str] | None = None,
    routing_policy: list[str] | None = None,
    negative_guidance: list[str] | None = None,
    prerequisites: list[str] | None = None,
    side_effects: list[str] | None = None,
) -> dict[str, object]:
    return {
        "x-llm-intent": intent,
        "x-when-to-use": when_to_use,
        "x-when-not-to-use": when_not_to_use
        or [
            "Use a more specific endpoint for direct state mutation or direct messaging.",
        ],
        "x-required-actor": required_actor,
        "x-prerequisites": prerequisites
        or [
            "Authenticated agent token",
            "Board access is validated before execution",
        ],
        "x-side-effects": side_effects or ["Read/write side effects vary by endpoint semantics."],
        "x-negative-guidance": negative_guidance
        or ["Avoid this endpoint when a focused sibling endpoint handles the action."],
        "x-routing-policy": routing_policy
        or [
            "Use when the request intent matches this board-scoped route.",
            "Prefer dedicated mutation/read routes once intent is narrowed.",
        ],
        "x-routing-policy-examples": routing_examples,
    }


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
    "/healthz",
    response_model=AgentHealthStatusResponse,
    tags=AGENT_ALL_ROLE_TAGS,
    summary="Agent Auth Health Check",
    description=(
        "Token-authenticated liveness probe for agent API clients.\n\n"
        "Use this endpoint when the caller needs to verify both service availability "
        "and agent-token validity in one request."
    ),
    openapi_extra={
        "x-llm-intent": "agent_auth_health",
        "x-when-to-use": [
            "Verify agent token validity before entering an automation loop",
            "Confirm agent API availability with caller identity context",
        ],
        "x-when-not-to-use": [
            "General infrastructure liveness checks that do not require auth context",
            "Task, board, or messaging workflow actions",
        ],
        "x-required-actor": "any_agent",
        "x-prerequisites": [
            "Authenticated agent token via X-Agent-Token header",
        ],
        "x-side-effects": [
            "May refresh agent last-seen presence metadata via auth middleware",
        ],
        "x-negative-guidance": [
            "Do not parse this response as an array.",
            "Do not use this endpoint for task routing decisions.",
        ],
        "x-routing-policy": [
            "Use this as the first probe for agent-scoped automation health.",
            "Use /healthz only for unauthenticated service-level liveness checks.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "agent startup probe with token verification",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_auth_health",
            },
            {
                "input": {
                    "intent": "platform-level probe with no agent token",
                    "required_privilege": "none",
                },
                "decision": "service_healthz",
            },
        ],
    },
)
def agent_healthz(
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> AgentHealthStatusResponse:
    """Return authenticated liveness metadata for the current agent token."""
    return AgentHealthStatusResponse(
        ok=True,
        agent_id=agent_ctx.agent.id,
        board_id=agent_ctx.agent.board_id,
        gateway_id=agent_ctx.agent.gateway_id,
        status=agent_ctx.agent.status,
        is_board_lead=agent_ctx.agent.is_board_lead,
    )


@router.get(
    "/boards",
    response_model=DefaultLimitOffsetPage[BoardRead],
    tags=AGENT_ALL_ROLE_TAGS,
    summary="List boards visible to the caller",
    description=(
        "Return boards the authenticated agent can access.\n\n"
        "Use this as a discovery step before board-scoped operations."
    ),
    openapi_extra={
        "x-llm-intent": "agent_board_discovery",
        "x-when-to-use": [
            "Discover boards available to the current agent",
            "Build a board selection list before read/write operations",
        ],
        "x-when-not-to-use": [
            "Use direct board-id endpoints when the target board is already known",
            "Use task-only views when board context is not needed",
        ],
        "x-required-actor": "any_agent",
        "x-prerequisites": [
            "Authenticated agent token",
            "Read access policy enforcement applied",
        ],
        "x-side-effects": [
            "No persisted side effects",
        ],
        "x-negative-guidance": [
            "Do not use as a task mutation mechanism.",
            "Do not treat this as a strict inventory cache endpoint.",
        ],
        "x-routing-policy": [
            "Use for board discovery before board-scoped actions.",
            "Fallback to board-specific fetch or task routes once target is known.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "agent needs boards to plan next actions",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_discovery",
            },
            {
                "input": {
                    "intent": "board target is known",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_get_board",
            },
        ],
    },
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


@router.get(
    "/boards/{board_id}",
    response_model=BoardRead,
    tags=AGENT_ALL_ROLE_TAGS,
    summary="Fetch a board by id",
    description=(
        "Read a single board entity if it is visible to the authenticated agent.\n\n"
        "Use for targeted planning and routing decisions."
    ),
    openapi_extra={
        "x-llm-intent": "agent_board_lookup",
        "x-when-to-use": [
            "Resolve board metadata before creating or updating board tasks",
            "Validate board context before routing actions",
        ],
        "x-when-not-to-use": [
            "Bulk discovery of all accessible boards",
            "Task list mutation workflows without board context",
        ],
        "x-required-actor": "any_agent",
        "x-prerequisites": [
            "Authenticated agent token",
            "Target board id must be accessible",
        ],
        "x-side-effects": [
            "No persisted side effects",
        ],
        "x-negative-guidance": [
            "Do not call for creating or mutating board fields.",
            "Do not use when board_id is unknown; discover first.",
        ],
        "x-routing-policy": [
            "Use when a specific board id is known and validation of scope is needed.",
            "Use task list endpoints for repeated board-scoped task discovery.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "agent needs full board context for planning",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_lookup",
            },
            {
                "input": {
                    "intent": "need multiple accessible boards first",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_discovery",
            },
        ],
    },
)
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
    summary="List visible agents",
    description=(
        "Return agents visible to the caller, optionally filtered by board.\n\n"
        "Use when downstream routing or coordination needs recipient actors."
    ),
    openapi_extra={
        "x-llm-intent": "agent_roster_discovery",
        "x-when-to-use": [
            "Discover agents available for assignment or coordination",
            "Build actor lists for lead and worker handoffs",
        ],
        "x-when-not-to-use": [
            "Fetching one specific agent identity (use agent lookup route if available)",
            "Mutating agent state",
        ],
        "x-required-actor": "any_agent",
        "x-prerequisites": [
            "Authenticated agent token",
            "Optional board_id filter scoped by caller access",
        ],
        "x-side-effects": [
            "No persisted side effects",
        ],
        "x-negative-guidance": [
            "Do not use for agent lifecycle changes.",
            "Do not assume full global visibility when filtered by board scopes.",
        ],
        "x-routing-policy": [
            "Use when coordination needs a roster and not a single agent lookup.",
            "Use task or direct nudge endpoints for one-off actor targeting.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "find eligible agents on a board",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_roster_discovery",
            },
            {
                "input": {
                    "intent": "target one agent for coordination",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_nudge_agent",
            },
        ],
    },
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
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_task_discovery",
        when_to_use=[
            "Agent needs board task list for work selection or queue management.",
            "Lead needs a filtered view for delegation planning.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "get assigned tasks for current agent",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_task_discovery",
            },
            {
                "input": {
                    "intent": "find unassigned backlog for delegation",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_board_task_discovery",
            },
        ],
    ),
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


@router.get(
    "/boards/{board_id}/tags",
    response_model=list[TagRef],
    tags=AGENT_BOARD_TAGS,
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_tag_discovery",
        when_to_use=[
            "Agent needs available tags before creating or updating task payloads.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "resolve tag id for assignment update",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_tag_discovery",
            }
        ],
    ),
)
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


@router.get(
    "/boards/{board_id}/webhooks/{webhook_id}/payloads/{payload_id}",
    response_model=BoardWebhookPayloadRead,
    tags=AGENT_BOARD_TAGS,
)
async def get_webhook_payload(
    webhook_id: UUID,
    payload_id: UUID,
    max_chars: int | None = Query(default=None, ge=1, le=1_000_000),
    board: Board = BOARD_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> BoardWebhookPayloadRead:
    """Fetch a stored webhook payload (agent-accessible, read-only).

    This enables lead agents to backfill dropped webhook events and enforce
    idempotency by inspecting previously received payloads.

    If `max_chars` is provided and the serialized payload exceeds the limit,
    the response payload is returned as a truncated string preview.
    """

    _guard_board_access(agent_ctx, board)

    payload = (
        await session.exec(
            select(BoardWebhookPayload)
            .where(col(BoardWebhookPayload.id) == payload_id)
            .where(col(BoardWebhookPayload.board_id) == board.id)
            .where(col(BoardWebhookPayload.webhook_id) == webhook_id),
        )
    ).first()
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    response = BoardWebhookPayloadRead.model_validate(payload, from_attributes=True)
    if max_chars is not None and response.payload is not None:
        import json

        try:
            raw = json.dumps(response.payload, ensure_ascii=True)
        except TypeError:
            raw = str(response.payload)
        if len(raw) > max_chars:
            if max_chars <= 3:
                response.payload = raw[:max_chars]
            else:
                response.payload = f"{raw[: max_chars - 3]}..."

    return response


@router.post(
    "/boards/{board_id}/tasks",
    response_model=TaskRead,
    tags=AGENT_LEAD_TAGS,
    summary="Create and assign a new board task as a lead agent",
    description=(
        "Create a new task on a board and persist lead metadata.\n\n"
        "Use when a lead needs to introduce new work, create dependencies, "
        "or directly assign ownership.\n"
        "Do not use for task updates or comments; those are separate endpoints."
    ),
    operation_id="agent_lead_create_task",
    responses={
        200: {"description": "Task created and persisted"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller is not board lead",
        },
        404: {"model": LLMErrorResponse, "description": "Assigned target agent does not exist"},
        409: {
            "model": LLMErrorResponse,
            "description": "Dependency or assignment validation failed",
        },
        422: {"model": LLMErrorResponse, "description": "Payload validation failed"},
    },
    openapi_extra={
        "x-llm-intent": "delegate_work",
        "x-when-to-use": [
            "Lead needs to create a new backlog item for the board",
            "Lead must set dependencies before work execution starts",
            "Lead wants to assign an owner and notify another agent",
        ],
        "x-when-not-to-use": [
            "Updating an existing task",
            "Adding progress comment",
            "Pushing non-governed automation updates",
        ],
        "x-required-actor": "board_lead",
        "x-prerequisites": [
            "Authenticated lead token",
            "board_id must be visible to lead",
            "Optional tag/dependency IDs must exist",
        ],
        "x-side-effects": [
            "Creates a new task row",
            "Creates dependency links",
            "Writes tag/custom field entries",
            "Rejects creation if dependency/assignment invariants fail",
        ],
        "x-negative-guidance": [
            "Do not call when updating an existing task or comment.",
            "Do not mix owner reassignment with unknown dependency IDs.",
        ],
        "x-routing-policy": [
            "Lead-only routing: use this when converting a new board item into a task.",
            "Fallback routing: use task update endpoints when the task already exists.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "lead wants to create a new issue with a new assignee",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_create_task",
            },
            {
                "input": {
                    "intent": "existing task needs edits after creation",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_boards_task_update",
            },
        ],
    },
)
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
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_task_update",
        when_to_use=[
            "Task state, ownership, dependencies, or inline status changes are needed.",
            "Board member needs to publish progress updates to an existing task.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "worker updates task status and notes",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_task_update",
            },
            {
                "input": {
                    "intent": "lead reassigns ownership for load balancing",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_task_update",
            },
        ],
    ),
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


@router.delete(
    "/boards/{board_id}/tasks/{task_id}",
    response_model=OkResponse,
    tags=AGENT_BOARD_TAGS,
    summary="Delete a task as board lead",
    description=(
        "Delete a board task and related records.\n\n"
        "This action is restricted to board lead agents."
    ),
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_task_delete",
        when_to_use=[
            "Board lead needs to permanently remove an obsolete, duplicate, or invalid task.",
        ],
        when_not_to_use=[
            "Use task updates when status changes or reassignment is sufficient.",
        ],
        required_actor="board_lead",
        side_effects=[
            "Deletes task comments, dependencies, tags, custom field values, and linked records.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "lead removes a duplicate task",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_task_delete",
            }
        ],
    ),
)
async def delete_task(
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> OkResponse:
    """Delete a task after board-lead authorization checks."""
    _guard_task_access(agent_ctx, task)
    _require_board_lead(agent_ctx)
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    await tasks_api.delete_task_and_related_records(session, task=task)
    return OkResponse()


@router.get(
    "/boards/{board_id}/tasks/{task_id}/comments",
    response_model=DefaultLimitOffsetPage[TaskCommentRead],
    tags=AGENT_BOARD_TAGS,
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_task_comment_discovery",
        when_to_use=[
            "Review prior discussion before posting or modifying task comments.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "read collaboration history before sending updates",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_task_comment_discovery",
            }
        ],
    ),
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
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_task_comment_create",
        when_to_use=[
            "Worker or lead needs to log progress, blockers, or coordination notes.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "add progress update comment",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_task_comment_create",
            }
        ],
    ),
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
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_memory_discovery",
        when_to_use=[
            "Agent needs board memory context before planning or status updates.",
            "Agent needs to inspect durable context for coordination continuity.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "load board context before work planning",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_memory_discovery",
            }
        ],
    ),
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


@router.post(
    "/boards/{board_id}/memory",
    response_model=BoardMemoryRead,
    tags=AGENT_BOARD_TAGS,
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_memory_record",
        when_to_use=[
            "Persist board-level context, decision, or handoff notes.",
            "Archive chat-like coordination context for cross-agent continuity.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "record decision context for future turns",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_memory_record",
            }
        ],
        side_effects=["Creates a board memory entry"],
        routing_policy=["Use when new board context should be persisted."],
    ),
)
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
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_approval_discovery",
        when_to_use=[
            "Agent needs to inspect outstanding approvals before acting on risky work.",
            "Lead needs to monitor unresolved approvals on board operations.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "check pending approvals for a task",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_approval_discovery",
            }
        ],
    ),
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


@router.post(
    "/boards/{board_id}/approvals",
    response_model=ApprovalRead,
    tags=AGENT_BOARD_TAGS,
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_approval_request",
        when_to_use=[
            "Agent needs formal approval before unsafe or high-risk actions.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "request guardrail before risky execution",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_approval_request",
            }
        ],
        required_actor="any_agent",
    ),
)
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
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_onboarding_update",
        when_to_use=[
            "Initialize or refresh agent onboarding state for board workflows.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "record onboarding signal during workflow handoff",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_board_onboarding_update",
            }
        ],
    ),
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


@router.post(
    "/agents",
    response_model=AgentRead,
    tags=AGENT_LEAD_TAGS,
    summary="Create a board agent as lead",
    description=(
        "Register a new board agent and attach it to the lead's board.\n\n"
        "The target board is derived from the caller identity and cannot be "
        "changed in payload."
    ),
    operation_id="agent_lead_create_agent",
    responses={
        200: {"description": "Agent provisioned"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller is not board lead",
        },
        409: {"model": LLMErrorResponse, "description": "Agent creation conflict"},
        422: {"model": LLMErrorResponse, "description": "Payload validation failed"},
    },
    openapi_extra={
        "x-llm-intent": "agent_management",
        "x-when-to-use": [
            "Need a new specialist for a board task flow",
            "Scaling workforce with role-based agents",
        ],
        "x-when-not-to-use": [
            "Updating an existing agent",
            "Creating non-board global actors",
        ],
        "x-required-actor": "board_lead",
        "x-prerequisites": [
            "Authenticated board lead",
            "Valid AgentCreate payload",
        ],
        "x-side-effects": [
            "Creates agent row",
            "Initializes lifecycle metadata",
            "May trigger downstream provisioning",
        ],
        "x-negative-guidance": [
            "Do not use for modifying existing agents.",
            "Do not create non-board agents through this endpoint.",
        ],
        "x-routing-policy": [
            "Use for first-time board agent onboarding and specialist expansion.",
            "Use agent update endpoint for profile changes on an existing actor.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "board lead needs a new specialist agent",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_create_agent",
            },
            {
                "input": {
                    "intent": "agent needs profile patch only",
                    "required_privilege": "board_lead",
                },
                "decision": "agent update payload path",
            },
        ],
    },
)
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
    summary="Nudge an agent on a board",
    description=(
        "Send a direct coordination message to a specific board agent.\n\n"
        "Use this when a lead sees stalled, idle, or misaligned work."
    ),
    operation_id="agent_lead_nudge_agent",
    responses={
        200: {"description": "Nudge dispatched"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller is not board lead",
        },
        404: {
            "model": LLMErrorResponse,
            "description": "Target agent does not exist",
        },
        422: {
            "model": LLMErrorResponse,
            "description": "Target agent cannot be reached",
        },
        502: {
            "model": LLMErrorResponse,
            "description": "Gateway dispatch failed",
        },
    },
    openapi_extra={
        "x-llm-intent": "agent_coordination",
        "x-when-to-use": [
            "Need to re-engage a worker quickly",
            "Clarify expected output with a targeted nudge",
        ],
        "x-when-not-to-use": [
            "Mass notification to all agents",
            "Escalation requiring human confirmation",
        ],
        "x-required-actor": "board_lead",
        "x-prerequisites": [
            "Authenticated board lead",
            "Target agent on same board",
            "nudge message content present",
        ],
        "x-side-effects": [
            "Emits coordination event",
            "Persists nudge correlation for audit",
        ],
        "x-negative-guidance": [
            "Do not use for broadcast messages.",
            "Do not use when no explicit target and no follow-up is required.",
        ],
        "x-routing-policy": [
            "Use for individual stalled or idle agent re-engagement.",
            "Use broadcast route when multiple leads need synchronized coordination.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "one worker is idle on an assigned task",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_nudge_agent",
            },
            {
                "input": {
                    "intent": "many leads need same instruction",
                    "required_privilege": "main_agent",
                },
                "decision": "agent_main_broadcast_lead_message",
            },
        ],
    },
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


@router.post(
    "/heartbeat",
    response_model=AgentRead,
    tags=AGENT_ALL_ROLE_TAGS,
    summary="Upsert agent heartbeat",
    description=(
        "Record liveness for the authenticated agent.\n\n"
        "Use this when the agent heartbeat loop checks in."
    ),
    openapi_extra={
        "x-llm-intent": "agent_heartbeat",
        "x-when-to-use": [
            "Agents should periodically update heartbeat to reflect liveness",
            "Report transient status transitions for monitoring and routing",
        ],
        "x-when-not-to-use": [
            "Do not use for user-facing notifications.",
            "Do not call with another agent identifier (agent is inferred).",
        ],
        "x-required-actor": "any_agent",
        "x-prerequisites": [
            "Authenticated agent token",
            "No request payload required",
        ],
        "x-side-effects": [
            "Updates agent heartbeat and status metadata",
            "May emit activity for monitoring consumers",
        ],
        "x-negative-guidance": [
            "Do not send heartbeat updates at excessive frequencies.",
            "Do not use heartbeat as task assignment signal.",
        ],
        "x-routing-policy": [
            "Use for periodic lifecycle status telemetry.",
            "Do not use when the same actor needs a task-specific action.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "agent is returning from busy/idle status change",
                    "required_privilege": "any_agent",
                },
                "decision": "agent_heartbeat",
            },
            {
                "input": {
                    "intent": "agent needs to escalate stalled task",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_nudge_agent",
            },
        ],
    },
)
async def agent_heartbeat(
    session: AsyncSession = SESSION_DEP,
    agent_ctx: AgentAuthContext = AGENT_CTX_DEP,
) -> AgentRead:
    """Record heartbeat status for the authenticated agent.

    Heartbeats are identity-bound to the token's agent id.
    """
    # Heartbeats must apply to the authenticated agent; agent names are not unique.
    return await agents_api.heartbeat_agent(
        agent_id=str(agent_ctx.agent.id),
        payload=AgentHeartbeat(),
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get(
    "/boards/{board_id}/agents/{agent_id}/soul",
    response_model=str,
    tags=AGENT_BOARD_TAGS,
    openapi_extra=_agent_board_openapi_hints(
        intent="agent_board_soul_lookup",
        when_to_use=[
            "Need an agent's SOUL guidance before deciding task instructions.",
            "Lead or same-agent needs current role instructions for coordination.",
        ],
        routing_examples=[
            {
                "input": {
                    "intent": "read actor behavior guidance",
                    "required_privilege": "board_lead_or_same_actor",
                },
                "decision": "agent_board_soul_lookup",
            }
        ],
        side_effects=["No persisted side effects"],
        routing_policy=[
            "Use for read-only retrieval of agent instruction sources.",
            "Use task-specific channels for temporary guidance instead of stored SOUL.",
        ],
    ),
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
    summary="Update an agent's SOUL template",
    description=(
        "Write SOUL.md content for a board agent and persist it for reprovisioning.\n\n"
        "Use this when role instructions or behavior guardrails need updates."
    ),
    operation_id="agent_lead_update_agent_soul",
    responses={
        200: {"description": "SOUL updated"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller is not board lead",
        },
        404: {
            "model": LLMErrorResponse,
            "description": "Board or target agent not found",
        },
        422: {
            "model": LLMErrorResponse,
            "description": "SOUL content is invalid or empty",
        },
        502: {
            "model": LLMErrorResponse,
            "description": "Gateway sync failed",
        },
    },
    openapi_extra={
        "x-llm-intent": "agent_knowledge_authoring",
        "x-when-to-use": [
            "Updating role behavior and recurring instructions",
            "Changing runbook or policy defaults for an agent",
        ],
        "x-when-not-to-use": [
            "Posting transient task-specific guidance",
            "Requesting human answer (use gateway ask-user)",
        ],
        "x-required-actor": "board_lead",
        "x-prerequisites": [
            "Authenticated board lead",
            "Non-empty SOUL content",
            "Target agent scoped to board",
        ],
        "x-side-effects": [
            "Updates soul_template in persistence",
            "Syncs gateway-visible SOUL content",
            "Creates coordination trace",
        ],
        "x-negative-guidance": [
            "Do not use for short, one-off task guidance.",
            "Do not use for transient playbook snippets; use task comments instead.",
        ],
        "x-routing-policy": [
            "Use when updating recurring role behavior or runbook defaults.",
            "Use task or gateway messages when scope is transient.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "lead wants to permanently change agent guardrails",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_update_agent_soul",
            },
            {
                "input": {
                    "intent": "temporary note for current task",
                    "required_privilege": "board_lead",
                },
                "decision": "task comment creation endpoint",
            },
        ],
    },
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
    summary="Delete a board agent as lead",
    description=(
        "Permanently remove a board agent and tear down associated lifecycle state.\n\n"
        "Use sparingly; prefer reassignment for continuity-sensitive teams."
    ),
    operation_id="agent_lead_delete_board_agent",
    responses={
        200: {"description": "Agent deleted"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller is not board lead",
        },
        404: {
            "model": LLMErrorResponse,
            "description": "Board agent not found",
        },
    },
    openapi_extra={
        "x-llm-intent": "agent_lifecycle",
        "x-when-to-use": [
            "Removing duplicates or decommissioning temporary agents",
            "Cleaning up after phase completion",
        ],
        "x-when-not-to-use": [
            "Temporary pausing (use status controls)",
            "Migrating data ownership without actor removal",
        ],
        "x-required-actor": "board_lead",
        "x-prerequisites": [
            "Authenticated board lead",
            "Agent scoped to same board",
        ],
        "x-side-effects": [
            "Deletes agent row and lifecycle state",
            "Potentially revokes in-flight actions for deleted actor",
        ],
        "x-negative-guidance": [
            "Do not delete when temporary suspension is sufficient.",
            "Do not use as an ownership transfer mechanism.",
        ],
        "x-routing-policy": [
            "Use only for permanent removal or decommission completion.",
            "Use status updates for pause/enable workflows.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "agent role is no longer needed and should be removed",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_delete_board_agent",
            },
            {
                "input": {
                    "intent": "agent needs temporary stop",
                    "required_privilege": "board_lead",
                },
                "decision": "agent status/assignment update",
            },
        ],
    },
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
    summary="Ask the human via gateway-main",
    description=(
        "Escalate a high-impact decision or ambiguity through the "
        "gateway-main interaction channel.\n\n"
        "Use when lead-level context needs human confirmation or consent."
    ),
    operation_id="agent_lead_ask_user_via_gateway_main",
    responses={
        200: {"description": "Escalation accepted"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller is not board lead",
        },
        404: {
            "model": LLMErrorResponse,
            "description": "Board context missing",
        },
        502: {
            "model": LLMErrorResponse,
            "description": "Gateway main handoff failed",
        },
    },
    openapi_extra={
        "x-llm-intent": "human_escalation",
        "x-when-to-use": [
            "Need explicit user confirmation",
            "Blocking ambiguity requires human preference input",
        ],
        "x-when-not-to-use": [
            "Routine status notes",
            "Low-signal alerts without action required",
        ],
        "x-required-actor": "board_lead",
        "x-prerequisites": [
            "Authenticated board lead",
            "Configured gateway-main routing",
        ],
        "x-side-effects": [
            "Sends user-facing ask",
            "Records escalation metadata",
        ],
        "x-negative-guidance": [
            "Do not use this for operational routing to another board lead.",
            "Do not use when there is no blocking ambiguity or consent requirement.",
        ],
        "x-routing-policy": [
            "Use when user permission or preference is required.",
            "Use lead-message route when you need an agent-to-lead control handoff.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "human consent required for permission-sensitive change",
                    "required_privilege": "board_lead",
                },
                "decision": "agent_lead_ask_user_via_gateway_main",
            },
            {
                "input": {
                    "intent": "lead needs coordination from main, no user permission required",
                    "required_privilege": "agent_main",
                },
                "decision": "agent_main_message_board_lead",
            },
        ],
    },
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
    summary="Message board lead via gateway-main",
    description=(
        "Route a direct lead handoff or question from an agent to the board lead.\n\n"
        "Use when a lead requires explicit, board-scoped routing."
    ),
    operation_id="agent_main_message_board_lead",
    responses={
        200: {"description": "Lead message sent"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller cannot message board lead",
        },
        404: {
            "model": LLMErrorResponse,
            "description": "Board or gateway binding not found",
        },
        422: {
            "model": LLMErrorResponse,
            "description": "Gateway configuration missing or invalid",
        },
        502: {
            "model": LLMErrorResponse,
            "description": "Gateway dispatch failed",
        },
    },
    openapi_extra={
        "x-llm-intent": "lead_direct_routing",
        "x-when-to-use": [
            "Need a single lead response for a specific board",
            "Need a routed handoff that is not user-facing",
        ],
        "x-when-not-to-use": [
            "Broadcast message to multiple board leads",
            "Human consent loops (use ask-user route)",
        ],
        "x-required-actor": "agent_main",
        "x-prerequisites": [
            "Board lead destination available",
            "Valid GatewayLeadMessageRequest payload",
        ],
        "x-side-effects": [
            "Creates direct lead routing dispatch",
            "Records correlation and status",
        ],
        "x-negative-guidance": [
            "Do not use when your request must fan out to many leads.",
            "Do not use for human permission questions.",
        ],
        "x-routing-policy": [
            "Use for single-board lead communication with direct follow-up.",
            "Use broadcast route only when multi-board or multi-lead fan-out is needed.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "agent needs one lead review for board-specific blocker",
                    "required_privilege": "agent_main",
                },
                "decision": "agent_main_message_board_lead",
            },
            {
                "input": {
                    "intent": "same notice needed across many leads",
                    "required_privilege": "agent_main",
                },
                "decision": "agent_main_broadcast_lead_message",
            },
        ],
    },
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
    summary="Broadcast a message to board leads via gateway-main",
    description=(
        "Send a shared coordination request to multiple board leads.\n\n"
        "Use for urgent cross-board or multi-lead fan-out patterns."
    ),
    operation_id="agent_main_broadcast_lead_message",
    openapi_extra={
        "x-llm-intent": "lead_broadcast_routing",
        "x-when-to-use": [
            "Need to notify many leads with same context",
            "Need aligned action across multiple board leads",
        ],
        "x-when-not-to-use": [
            "Single lead interaction is required",
            "Human-facing consent request",
        ],
        "x-required-actor": "agent_main",
        "x-prerequisites": [
            "Gateway-main routing identity available",
            "GatewayLeadBroadcastRequest payload",
        ],
        "x-side-effects": [
            "Creates multi-recipient dispatch",
            "Returns per-board status result entries",
        ],
        "x-negative-guidance": [
            "Do not use for sensitive single-lead tactical prompts.",
            "Do not use for consent flows requiring explicit end-user input.",
        ],
        "x-routing-policy": [
            "Use when intent spans multiple board leads or operational domains.",
            "Use single-lead message route for board-specific point-to-point communication.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {
                    "intent": "urgent incident notice required for multiple leads",
                    "required_privilege": "agent_main",
                },
                "decision": "agent_main_broadcast_lead_message",
            },
            {
                "input": {
                    "intent": "single lead requires clarification before continuing",
                    "required_privilege": "agent_main",
                },
                "decision": "agent_main_message_board_lead",
            },
        ],
    },
    responses={
        200: {"description": "Broadcast completed"},
        403: {
            "model": LLMErrorResponse,
            "description": "Caller cannot broadcast via gateway-main",
        },
        404: {
            "model": LLMErrorResponse,
            "description": "Gateway binding not found",
        },
        422: {
            "model": LLMErrorResponse,
            "description": "Gateway configuration missing or invalid",
        },
        502: {
            "model": LLMErrorResponse,
            "description": "Gateway dispatch partially failed",
        },
    },
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
