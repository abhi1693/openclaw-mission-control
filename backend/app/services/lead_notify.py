"""Lead-wake notification helpers.

Centralizes the "ping the board lead via gateway dispatch" pattern that
several event paths need (Blocker resolve, auto-resolve, etc.). Without
this module the helper would duplicate across api modules and drift
silently — codex 2026-05-03 review caught the auto-resolve paths
silently bypassing the wake hook in api/blockers.py.
"""

from __future__ import annotations

import logging

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task
from app.services.openclaw.gateway_dispatch import GatewayDispatchService

logger = logging.getLogger(__name__)


async def _send_lead_wake(
    *,
    session: AsyncSession,
    task: Task,
    message: str,
) -> None:
    """Send a wake message to the board lead. Caller wraps in try/except."""
    if task.board_id is None:
        return
    lead = (
        await Agent.objects.filter_by(board_id=task.board_id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    board = await session.get(Board, task.board_id)
    if board is None:
        return
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    await dispatch.try_send_agent_message(
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=message,
        deliver=True,
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
            "blocker-resolve notify suppressed: %s (task=%s)", exc, task.id,
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
            "dependency-clear notify suppressed: %s (task=%s)", exc, task.id,
        )
