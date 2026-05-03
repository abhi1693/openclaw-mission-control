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


async def notify_lead_after_blocker_resolved(
    *,
    session: AsyncSession,
    task: Task,
) -> None:
    """Wake the board lead after the last open Blocker on a task resolves.

    Best-effort: dispatch failures are swallowed with ``logger.warning``
    so the caller's commit path never fails on notification issues.
    Does NOT rollback on dispatch failure — callers commit before
    invoking this helper, so there is no pending DB state to discard.

    Idempotency is the caller's responsibility: only call when the
    most recent resolve actually closed the last open Blocker on the
    task. Otherwise the lead wakes for nothing.
    """
    try:
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
        message = (
            f"BLOCKER_RESOLVED: task {task.title} ({task.id}) is now actionable.\n"
            f"Status: {task.status}. All open Blockers cleared.\n"
            f"Route per lead-next-action skill."
        )
        await dispatch.try_send_agent_message(
            session_key=lead.openclaw_session_id,
            config=config,
            agent_name=lead.name,
            message=message,
            deliver=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "blocker-resolve notify suppressed: %s (task=%s)",
            exc, task.id,
        )
