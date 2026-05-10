"""Phase VI §I6 blocked-lane comment suppression.

Once a task has any acknowledged open blocker, comments from non-
owner agents are suppressed unless:

- the commenter is the task owner (``task.assigned_agent_id``),
- the commenter is a human operator (``ActorContext.actor_type ==
  "user"``),
- the board has not yet graduated past the legacy behaviour
  (``rollout_flags["structured_blockers_v1"]`` is absent / False).

The rule stops the "duplicate FAIL under a known blocker" noise
pattern that drove the original incident. It does not replace the
Phase I comment-classifier filter — that one hides rows from reads;
this one rejects the write altogether.

Refinements deferred to follow-up commits:
- "blocker owner posts canonical summary once" exception
- "blocker record changed since commenter's last turn" exception
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.blockers import Blocker
from app.models.boards import Board
from app.models.tasks import Task
from app.schemas.boards import (
    STRUCTURED_BLOCKERS_V1_FLAG,
    board_rollout_flag_enabled,
)


async def should_suppress_comment_for_blocked_lane(
    session: AsyncSession,
    *,
    task: Task,
    author_agent_id: UUID | None,
) -> bool:
    """Return True when the comment should be rejected under §I6.

    The rule:

    1. Board has ``structured_blockers_v1`` rollout_flag set True.
       Otherwise the lane quieting is not yet active for this board.
    2. Task has at least one open, *acknowledged* ``Blocker`` row.
       Acknowledgement is the operator signal that "the routing has
       been received" — unacknowledged blockers still need traffic
       so the owner can pick them up.
    3. Comment author is an agent (``author_agent_id`` is not None).
       User-token callers (operators) are exempt; humans can always
       comment on a blocked lane.
    4. Comment author is NOT the task's assigned owner. The owner is
       the one party that may legitimately post progress / resolve
       updates while the lane is otherwise quiet.
    """

    if task.board_id is None:
        return False

    board_flags = await session.scalar(select(Board.rollout_flags).where(Board.id == task.board_id))
    if not board_rollout_flag_enabled(board_flags, STRUCTURED_BLOCKERS_V1_FLAG):
        return False

    if author_agent_id is None:
        return False

    if task.assigned_agent_id is not None and author_agent_id == task.assigned_agent_id:
        return False

    has_acked_blocker = await session.scalar(
        select(
            exists()
            .where(col(Blocker.task_id) == task.id)
            .where(col(Blocker.board_id) == task.board_id)
            .where(col(Blocker.resolved_at).is_(None))
            .where(col(Blocker.acknowledged_at).is_not(None))
        )
    )
    return bool(has_acked_blocker)
