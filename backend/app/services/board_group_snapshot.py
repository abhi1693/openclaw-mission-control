"""Helpers for assembling board-group snapshot view models."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import case, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.board_groups import BoardGroup
from app.models.boards import Board
from app.models.tasks import Task
from app.schemas.board_groups import BoardGroupRead
from app.schemas.boards import BoardRead
from app.schemas.view_models import (
    BoardGroupBoardSnapshot,
    BoardGroupSnapshot,
    BoardGroupTaskSummary,
)
from app.services.tags import TagState, load_tag_state

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

_STATUS_ORDER = {"in_progress": 0, "review": 1, "inbox": 2, "done": 3}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_RUNTIME_TYPE_REFERENCES = (UUID, AsyncSession)


def _status_weight_expr() -> ColumnElement[int]:
    """Return a SQL expression that sorts task statuses by configured order."""
    whens = [(col(Task.status) == key, weight) for key, weight in _STATUS_ORDER.items()]
    return case(*whens, else_=99)


def _priority_weight_expr() -> ColumnElement[int]:
    """Return a SQL expression that sorts task priorities by configured order."""
    whens = [(col(Task.priority) == key, weight) for key, weight in _PRIORITY_ORDER.items()]
    return case(*whens, else_=99)


async def _boards_for_group(
    session: AsyncSession,
    *,
    group_id: UUID,
    exclude_board_id: UUID | None = None,
) -> list[Board]:
    """Return boards belonging to a board group with optional exclusion."""
    statement = Board.objects.filter_by(board_group_id=group_id).statement
    if exclude_board_id is not None:
        statement = statement.where(col(Board.id) != exclude_board_id)
    return list(
        await session.exec(
            statement.order_by(func.lower(col(Board.name)).asc()),
        ),
    )


async def _task_counts_by_board(
    session: AsyncSession,
    board_ids: list[UUID],
) -> dict[UUID, dict[str, int]]:
    """Return per-board task counts keyed by task status."""
    task_counts: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for board_id, status_value, total in list(
        await session.exec(
            select(col(Task.board_id), col(Task.status), func.count(col(Task.id)))
            .where(col(Task.board_id).in_(board_ids))
            .group_by(col(Task.board_id), col(Task.status)),
        ),
    ):
        if board_id is None:
            continue
        task_counts[board_id][str(status_value)] = int(total or 0)
    return task_counts


async def _ordered_tasks_for_boards(
    session: AsyncSession,
    board_ids: list[UUID],
    *,
    include_done: bool,
) -> list[Task]:
    """Return sorted tasks for boards, optionally excluding completed tasks."""
    task_statement = select(Task).where(col(Task.board_id).in_(board_ids))
    if not include_done:
        task_statement = task_statement.where(col(Task.status) != "done")
    task_statement = task_statement.order_by(
        col(Task.board_id).asc(),
        _status_weight_expr().asc(),
        _priority_weight_expr().asc(),
        col(Task.updated_at).desc(),
        col(Task.created_at).desc(),
    )
    return list(await session.exec(task_statement))


async def _agent_names(
    session: AsyncSession,
    tasks: list[Task],
) -> dict[UUID, str]:
    """Return agent names keyed by assigned agent ids in the provided tasks."""
    assigned_ids = {task.assigned_agent_id for task in tasks if task.assigned_agent_id is not None}
    if not assigned_ids:
        return {}
    return dict(
        list(
            await session.exec(
                select(col(Agent.id), col(Agent.name)).where(
                    col(Agent.id).in_(assigned_ids),
                ),
            ),
        ),
    )


def _task_summaries_by_board(
    *,
    boards_by_id: dict[UUID, Board],
    tasks: list[Task],
    agent_name_by_id: dict[UUID, str],
    tag_state_by_task_id: dict[UUID, TagState],
    per_board_task_limit: int,
) -> dict[UUID, list[BoardGroupTaskSummary]]:
    """Build limited per-board task summary lists."""
    tasks_by_board: dict[UUID, list[BoardGroupTaskSummary]] = defaultdict(list)
    if per_board_task_limit <= 0:
        return tasks_by_board
    for task in tasks:
        if task.board_id is None:
            continue
        current = tasks_by_board[task.board_id]
        if len(current) >= per_board_task_limit:
            continue
        board = boards_by_id.get(task.board_id)
        if board is None:
            continue
        current.append(
            # Include tags so cross-board snapshots can be grouped quickly in the UI.
            BoardGroupTaskSummary(
                id=task.id,
                board_id=task.board_id,
                board_name=board.name,
                title=task.title,
                status=task.status,
                priority=task.priority,
                assigned_agent_id=task.assigned_agent_id,
                assignee=(
                    agent_name_by_id.get(task.assigned_agent_id)
                    if task.assigned_agent_id is not None
                    else None
                ),
                due_at=task.due_at,
                in_progress_at=task.in_progress_at,
                tags=tag_state_by_task_id.get(task.id, TagState()).tags,
                created_at=task.created_at,
                updated_at=task.updated_at,
            ),
        )
    return tasks_by_board


async def build_group_snapshot(
    session: AsyncSession,
    *,
    group: BoardGroup,
    exclude_board_id: UUID | None = None,
    include_done: bool = False,
    per_board_task_limit: int = 5,
) -> BoardGroupSnapshot:
    """Build a board-group snapshot with board/task summaries."""
    boards = await _boards_for_group(
        session,
        group_id=group.id,
        exclude_board_id=exclude_board_id,
    )
    if not boards:
        return BoardGroupSnapshot(
            group=BoardGroupRead.model_validate(group, from_attributes=True),
        )
    boards_by_id = {board.id: board for board in boards}
    board_ids = list(boards_by_id.keys())
    task_counts = await _task_counts_by_board(session, board_ids)
    tasks = await _ordered_tasks_for_boards(
        session,
        board_ids,
        include_done=include_done,
    )
    agent_name_by_id = await _agent_names(session, tasks)
    tag_state_by_task_id = await load_tag_state(
        session,
        task_ids=[task.id for task in tasks],
    )
    tasks_by_board = _task_summaries_by_board(
        boards_by_id=boards_by_id,
        tasks=tasks,
        agent_name_by_id=agent_name_by_id,
        tag_state_by_task_id=tag_state_by_task_id,
        per_board_task_limit=per_board_task_limit,
    )
    snapshots = [
        BoardGroupBoardSnapshot(
            board=BoardRead.model_validate(board, from_attributes=True),
            task_counts=dict(task_counts.get(board.id, {})),
            tasks=tasks_by_board.get(board.id, []),
        )
        for board in boards
    ]
    return BoardGroupSnapshot(
        group=BoardGroupRead.model_validate(group, from_attributes=True),
        boards=snapshots,
    )


async def build_board_group_snapshot(
    session: AsyncSession,
    *,
    board: Board,
    include_self: bool = False,
    include_done: bool = False,
    per_board_task_limit: int = 5,
) -> BoardGroupSnapshot:
    """Build a board-group snapshot anchored to a board context."""
    if not board.board_group_id:
        return BoardGroupSnapshot(group=None, boards=[])
    group = await BoardGroup.objects.by_id(board.board_group_id).first(session)
    if group is None:
        return BoardGroupSnapshot(group=None, boards=[])
    return await build_group_snapshot(
        session,
        group=group,
        exclude_board_id=None if include_self else board.id,
        include_done=include_done,
        per_board_task_limit=per_board_task_limit,
    )
