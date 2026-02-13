"""Helpers for assembling denormalized board snapshot response payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import col, select

from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.board_memory import BoardMemory
from app.models.tasks import Task
from app.schemas.approvals import ApprovalRead
from app.schemas.board_memory import BoardMemoryRead
from app.schemas.boards import BoardRead
from app.schemas.view_models import BoardSnapshot, TaskCardRead
from app.services.approval_task_links import load_task_ids_by_approval, task_counts_for_board
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.services.tags import TagState, load_tag_state
from app.services.task_dependencies import (
    blocked_by_dependency_ids,
    dependency_ids_by_task_id,
    dependency_status_by_id,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board


def _memory_to_read(memory: BoardMemory) -> BoardMemoryRead:
    return BoardMemoryRead.model_validate(memory, from_attributes=True)


def _approval_to_read(
    approval: Approval,
    *,
    task_ids: list[UUID],
    task_titles: list[str],
) -> ApprovalRead:
    model = ApprovalRead.model_validate(approval, from_attributes=True)
    primary_task_id = task_ids[0] if task_ids else None
    return model.model_copy(
        update={
            "task_id": primary_task_id,
            "task_ids": task_ids,
            "task_titles": task_titles,
        },
    )


def _task_to_card(
    task: Task,
    *,
    agent_name_by_id: dict[UUID, str],
    counts_by_task_id: dict[UUID, tuple[int, int]],
    deps_by_task_id: dict[UUID, list[UUID]],
    dependency_status_by_id_map: dict[UUID, str],
    tag_state_by_task_id: dict[UUID, TagState],
) -> TaskCardRead:
    card = TaskCardRead.model_validate(task, from_attributes=True)
    approvals_count, approvals_pending_count = counts_by_task_id.get(task.id, (0, 0))
    assignee = agent_name_by_id.get(task.assigned_agent_id) if task.assigned_agent_id else None
    depends_on_task_ids = deps_by_task_id.get(task.id, [])
    tag_state = tag_state_by_task_id.get(task.id, TagState())
    blocked_by_task_ids = blocked_by_dependency_ids(
        dependency_ids=depends_on_task_ids,
        status_by_id=dependency_status_by_id_map,
    )
    if task.status == "done":
        blocked_by_task_ids = []
    return card.model_copy(
        update={
            "assignee": assignee,
            "approvals_count": approvals_count,
            "approvals_pending_count": approvals_pending_count,
            "depends_on_task_ids": depends_on_task_ids,
            "tag_ids": tag_state.tag_ids,
            "tags": tag_state.tags,
            "blocked_by_task_ids": blocked_by_task_ids,
            "is_blocked": bool(blocked_by_task_ids),
        },
    )


async def build_board_snapshot(session: AsyncSession, board: Board) -> BoardSnapshot:
    """Build a board snapshot with tasks, agents, approvals, and chat history."""
    board_read = BoardRead.model_validate(board, from_attributes=True)

    tasks = list(
        await Task.objects.filter_by(board_id=board.id)
        .order_by(col(Task.created_at).desc())
        .all(session),
    )
    task_ids = [task.id for task in tasks]
    tag_state_by_task_id = await load_tag_state(
        session,
        task_ids=task_ids,
    )

    deps_by_task_id = await dependency_ids_by_task_id(
        session,
        board_id=board.id,
        task_ids=task_ids,
    )
    all_dependency_ids: list[UUID] = []
    for values in deps_by_task_id.values():
        all_dependency_ids.extend(values)
    dependency_status_by_id_map = await dependency_status_by_id(
        session,
        board_id=board.id,
        dependency_ids=list({*all_dependency_ids}),
    )

    agents = (
        await Agent.objects.filter_by(board_id=board.id)
        .order_by(col(Agent.created_at).desc())
        .all(session)
    )
    agent_reads = [
        AgentLifecycleService.to_agent_read(AgentLifecycleService.with_computed_status(agent))
        for agent in agents
    ]
    agent_name_by_id = {agent.id: agent.name for agent in agents}

    pending_approvals_count = int(
        (
            await session.exec(
                select(func.count(col(Approval.id)))
                .where(col(Approval.board_id) == board.id)
                .where(col(Approval.status) == "pending"),
            )
        ).one(),
    )

    approvals = (
        await Approval.objects.filter_by(board_id=board.id)
        .order_by(col(Approval.created_at).desc())
        .limit(200)
        .all(session)
    )
    approval_ids = [approval.id for approval in approvals]
    task_ids_by_approval = await load_task_ids_by_approval(
        session,
        approval_ids=approval_ids,
    )
    task_title_by_id = {task.id: task.title for task in tasks}
    # Hydrate each approval with linked task metadata, falling back to legacy
    # single-task fields so older rows still render complete approval cards.
    approval_reads = [
        _approval_to_read(
            approval,
            task_ids=(
                linked_task_ids := task_ids_by_approval.get(
                    approval.id,
                    [approval.task_id] if approval.task_id is not None else [],
                )
            ),
            task_titles=[
                task_title_by_id[task_id]
                for task_id in linked_task_ids
                if task_id in task_title_by_id
            ],
        )
        for approval in approvals
    ]

    counts_by_task_id = await task_counts_for_board(session, board_id=board.id)

    task_cards = [
        _task_to_card(
            task,
            agent_name_by_id=agent_name_by_id,
            counts_by_task_id=counts_by_task_id,
            deps_by_task_id=deps_by_task_id,
            dependency_status_by_id_map=dependency_status_by_id_map,
            tag_state_by_task_id=tag_state_by_task_id,
        )
        for task in tasks
    ]

    chat_messages = (
        await BoardMemory.objects.filter_by(board_id=board.id)
        .filter(col(BoardMemory.is_chat).is_(True))
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardMemory.content))) > 0)
        .order_by(col(BoardMemory.created_at).desc())
        .limit(200)
        .all(session)
    )
    chat_messages.sort(key=lambda item: item.created_at)
    chat_reads = [_memory_to_read(memory) for memory in chat_messages]

    return BoardSnapshot(
        board=board_read,
        tasks=task_cards,
        agents=agent_reads,
        approvals=approval_reads,
        chat_messages=chat_reads,
        pending_approvals_count=pending_approvals_count,
    )
