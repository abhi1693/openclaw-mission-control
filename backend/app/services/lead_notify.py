"""Lead-wake notification helpers.

Centralizes the "ping the board lead via gateway dispatch" pattern that
several event paths need (Blocker resolve, auto-resolve, etc.). Without
this module the helper would duplicate across api modules and drift
silently — codex 2026-05-03 review caught the auto-resolve paths
silently bypassing the wake hook in api/blockers.py.
"""

from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task
from app.services.openclaw.gateway_dispatch import GatewayDispatchService

logger = get_logger(__name__)


async def _send_agent_wake(
    *,
    session: AsyncSession,
    board_id,
    agent: Agent,
    message: str,
) -> bool:
    """Send a wake message to a specific agent. Returns True iff
    dispatched. No-op (returns False) when session_key, board, or
    gateway config is missing.
    """
    if not agent.openclaw_session_id:
        return False
    dispatch = GatewayDispatchService(session)
    board = await session.get(Board, board_id)
    if board is None:
        return False
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return False
    await dispatch.try_send_agent_message(
        session_key=agent.openclaw_session_id,
        config=config,
        agent_name=agent.name,
        message=message,
        deliver=True,
    )
    return True


async def _send_lead_wake(
    *,
    session: AsyncSession,
    task: Task,
    message: str,
) -> None:
    if task.board_id is None:
        return
    lead = (
        await Agent.objects.filter_by(board_id=task.board_id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None:
        return
    await _send_agent_wake(
        session=session,
        board_id=task.board_id,
        agent=lead,
        message=message,
    )


async def notify_lead_after_blocker_resolved(
    *,
    session: AsyncSession,
    task: Task,
) -> None:
    """Wake the board lead after the last open Blocker on a task resolves.

    Best-effort: dispatch failures are swallowed. Caller must have
    committed — the helper does not rollback. Caller is responsible
    for idempotency (only call when this resolve actually closed the
    last open Blocker).
    """
    message = (
        f"BLOCKER_RESOLVED: task {task.title} ({task.id}) is now actionable.\n"
        f"Status: {task.status}. All open Blockers cleared.\n"
        f"Route per lead-next-action skill."
    )
    try:
        await _send_lead_wake(session=session, task=task, message=message)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "blocker-resolve notify suppressed: %s (task=%s)",
            exc,
            task.id,
        )


async def send_agent_wake(
    *,
    session: AsyncSession,
    board_id,
    agent: Agent,
    message: str,
) -> bool:
    """Public alias for _send_agent_wake — used by the next-reviewer
    auto-wake path."""
    return await _send_agent_wake(
        session=session,
        board_id=board_id,
        agent=agent,
        message=message,
    )


async def notify_lead_after_dependency_cleared(
    *,
    session: AsyncSession,
    task: Task,
    dependency_task: Task,
) -> None:
    """Wake the board lead when the last unresolved dependency clears.

    Symmetric to ``notify_lead_after_blocker_resolved``. Caller is
    responsible for idempotency (only call when the dep transition
    actually cleared the LAST unresolved dep, with no open Blockers
    and a non-terminal status on the dependent).
    """
    message = (
        f"DEPENDENCY_CLEARED: task {task.title} ({task.id}) is now actionable.\n"
        f"Cleared by: {dependency_task.title} ({dependency_task.id}) -> done.\n"
        f"Status: {task.status}. No remaining open dependencies or Blockers.\n"
        f"Route per lead-next-action skill."
    )
    try:
        await _send_lead_wake(session=session, task=task, message=message)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dependency-clear notify suppressed: %s (task=%s)",
            exc,
            task.id,
        )
