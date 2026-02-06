from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import agents as agents_api
from app.api import approvals as approvals_api
from app.api import board_memory as board_memory_api
from app.api import board_onboarding as onboarding_api
from app.api import tasks as tasks_api
from app.api.deps import ActorContext, get_board_or_404, get_task_or_404
from app.core.agent_auth import AgentAuthContext, get_agent_auth_context
from app.db.pagination import paginate
from app.db.session import get_session
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, ensure_session, send_message
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.board_memory import BoardMemory
from app.models.board_onboarding import BoardOnboardingSession
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.tasks import Task
from app.schemas.agents import AgentCreate, AgentHeartbeat, AgentHeartbeatCreate, AgentNudge, AgentRead
from app.schemas.approvals import ApprovalCreate, ApprovalRead, ApprovalStatus
from app.schemas.board_memory import BoardMemoryCreate, BoardMemoryRead
from app.schemas.board_onboarding import BoardOnboardingAgentUpdate, BoardOnboardingRead
from app.schemas.boards import BoardRead
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.tasks import TaskCommentCreate, TaskCommentRead, TaskCreate, TaskRead, TaskUpdate
from app.services.activity_log import record_activity

router = APIRouter(prefix="/agent", tags=["agent"])


def _actor(agent_ctx: AgentAuthContext) -> ActorContext:
    return ActorContext(actor_type="agent", agent=agent_ctx.agent)


def _guard_board_access(agent_ctx: AgentAuthContext, board: Board) -> None:
    if agent_ctx.agent.board_id and agent_ctx.agent.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


async def _gateway_config(session: AsyncSession, board: Board) -> GatewayClientConfig:
    if not board.gateway_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    gateway = await session.get(Gateway, board.gateway_id)
    if gateway is None or not gateway.url:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return GatewayClientConfig(url=gateway.url, token=gateway.token)


@router.get("/boards", response_model=DefaultLimitOffsetPage[BoardRead])
async def list_boards(
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> DefaultLimitOffsetPage[BoardRead]:
    statement = select(Board)
    if agent_ctx.agent.board_id:
        statement = statement.where(col(Board.id) == agent_ctx.agent.board_id)
    statement = statement.order_by(col(Board.created_at).desc())
    return await paginate(session, statement)


@router.get("/boards/{board_id}", response_model=BoardRead)
def get_board(
    board: Board = Depends(get_board_or_404),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> Board:
    _guard_board_access(agent_ctx, board)
    return board


@router.get("/agents", response_model=DefaultLimitOffsetPage[AgentRead])
async def list_agents(
    board_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> DefaultLimitOffsetPage[AgentRead]:
    statement = select(Agent)
    if agent_ctx.agent.board_id:
        if board_id and board_id != agent_ctx.agent.board_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        statement = statement.where(Agent.board_id == agent_ctx.agent.board_id)
    elif board_id:
        statement = statement.where(Agent.board_id == board_id)
    main_session_keys = await agents_api._get_gateway_main_session_keys(session)
    statement = statement.order_by(col(Agent.created_at).desc())

    def _transform(items: Sequence[Any]) -> Sequence[Any]:
        agents = cast(Sequence[Agent], items)
        return [
            agents_api._to_agent_read(agents_api._with_computed_status(agent), main_session_keys)
            for agent in agents
        ]

    return await paginate(session, statement, transformer=_transform)


@router.get("/boards/{board_id}/tasks", response_model=DefaultLimitOffsetPage[TaskRead])
async def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    assigned_agent_id: UUID | None = None,
    unassigned: bool | None = None,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> DefaultLimitOffsetPage[TaskRead]:
    _guard_board_access(agent_ctx, board)
    return await tasks_api.list_tasks(
        status_filter=status_filter,
        assigned_agent_id=assigned_agent_id,
        unassigned=unassigned,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/tasks", response_model=TaskRead)
async def create_task(
    payload: TaskCreate,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> Task:
    _guard_board_access(agent_ctx, board)
    if not agent_ctx.agent.is_board_lead:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    task = Task.model_validate(payload)
    task.board_id = board.id
    task.auto_created = True
    task.auto_reason = f"lead_agent:{agent_ctx.agent.id}"
    if task.assigned_agent_id:
        agent = await session.get(Agent, task.assigned_agent_id)
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
        assigned_agent = await session.get(Agent, task.assigned_agent_id)
        if assigned_agent:
            await tasks_api._notify_agent_on_task_assign(
                session=session,
                board=board,
                task=task,
                agent=assigned_agent,
            )
    return task


@router.patch("/boards/{board_id}/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    payload: TaskUpdate,
    task: Task = Depends(get_task_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> Task:
    if agent_ctx.agent.board_id and task.board_id and agent_ctx.agent.board_id != task.board_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return await tasks_api.update_task(
        payload=payload,
        task=task,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get(
    "/boards/{board_id}/tasks/{task_id}/comments",
    response_model=DefaultLimitOffsetPage[TaskCommentRead],
)
async def list_task_comments(
    task: Task = Depends(get_task_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> DefaultLimitOffsetPage[TaskCommentRead]:
    if agent_ctx.agent.board_id and task.board_id and agent_ctx.agent.board_id != task.board_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return await tasks_api.list_task_comments(
        task=task,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/tasks/{task_id}/comments", response_model=TaskCommentRead)
async def create_task_comment(
    payload: TaskCommentCreate,
    task: Task = Depends(get_task_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> ActivityEvent:
    if agent_ctx.agent.board_id and task.board_id and agent_ctx.agent.board_id != task.board_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return await tasks_api.create_task_comment(
        payload=payload,
        task=task,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.get("/boards/{board_id}/memory", response_model=DefaultLimitOffsetPage[BoardMemoryRead])
async def list_board_memory(
    is_chat: bool | None = Query(default=None),
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> DefaultLimitOffsetPage[BoardMemoryRead]:
    _guard_board_access(agent_ctx, board)
    return await board_memory_api.list_board_memory(
        is_chat=is_chat,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/memory", response_model=BoardMemoryRead)
async def create_board_memory(
    payload: BoardMemoryCreate,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> BoardMemory:
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
)
async def list_approvals(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> DefaultLimitOffsetPage[ApprovalRead]:
    _guard_board_access(agent_ctx, board)
    return await approvals_api.list_approvals(
        status_filter=status_filter,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/approvals", response_model=ApprovalRead)
async def create_approval(
    payload: ApprovalCreate,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> Approval:
    _guard_board_access(agent_ctx, board)
    return await approvals_api.create_approval(
        payload=payload,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/onboarding", response_model=BoardOnboardingRead)
async def update_onboarding(
    payload: BoardOnboardingAgentUpdate,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> BoardOnboardingSession:
    _guard_board_access(agent_ctx, board)
    return await onboarding_api.agent_onboarding_update(
        payload=payload,
        board=board,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/agents", response_model=AgentRead)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> AgentRead:
    if not agent_ctx.agent.is_board_lead:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if not agent_ctx.agent.board_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    payload = AgentCreate(**{**payload.model_dump(), "board_id": agent_ctx.agent.board_id})
    return await agents_api.create_agent(
        payload=payload,
        session=session,
        actor=_actor(agent_ctx),
    )


@router.post("/boards/{board_id}/agents/{agent_id}/nudge", response_model=OkResponse)
async def nudge_agent(
    payload: AgentNudge,
    agent_id: str,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> OkResponse:
    _guard_board_access(agent_ctx, board)
    if not agent_ctx.agent.is_board_lead:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    target = await session.get(Agent, agent_id)
    if target is None or (target.board_id and target.board_id != board.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not target.openclaw_session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Target agent has no session key",
        )
    message = payload.message
    config = await _gateway_config(session, board)
    try:
        await ensure_session(target.openclaw_session_id, config=config, label=target.name)
        await send_message(
            message,
            session_key=target.openclaw_session_id,
            config=config,
            deliver=True,
        )
    except OpenClawGatewayError as exc:
        record_activity(
            session,
            event_type="agent.nudge.failed",
            message=f"Nudge failed for {target.name}: {exc}",
            agent_id=agent_ctx.agent.id,
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    record_activity(
        session,
        event_type="agent.nudge.sent",
        message=f"Nudge sent to {target.name}.",
        agent_id=agent_ctx.agent.id,
    )
    await session.commit()
    return OkResponse()


@router.post("/heartbeat", response_model=AgentRead)
async def agent_heartbeat(
    payload: AgentHeartbeatCreate,
    session: AsyncSession = Depends(get_session),
    agent_ctx: AgentAuthContext = Depends(get_agent_auth_context),
) -> AgentRead:
    # Heartbeats must apply to the authenticated agent; agent names are not unique.
    return await agents_api.heartbeat_agent(
        agent_id=str(agent_ctx.agent.id),
        payload=AgentHeartbeat(status=payload.status),
        session=session,
        actor=_actor(agent_ctx),
    )
