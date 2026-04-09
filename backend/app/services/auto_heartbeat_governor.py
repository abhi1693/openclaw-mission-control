"""Auto-idle heartbeat governor.

Goal: reduce background model usage by dynamically backing off agent heartbeats when boards are idle,
while keeping agents responsive when there is activity.

Design notes:
- Runs periodically (every N seconds) from the backend process.
- Uses a DB advisory lock to ensure only one governor instance runs at a time.
- Activity trigger (per Tes spec): ANY new board chat counts as activity.
- Leads never go fully off; they cap at 1h.
- "Fully off" is implemented by unsetting the agent heartbeat in the gateway config (not by using
  an invalid value like every="disabled").

This module only decides and applies desired heartbeats. It does not wake sessions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.provisioning import (
    OpenClawGatewayControlPlane,
    _workspace_path,
)

logger = get_logger(__name__)

# Governor defaults; board policy may override backoff behaviour.
DEFAULT_ACTIVE_EVERY = "5m"
DEFAULT_LADDER: list[str] = ["10m", "30m", "1h", "3h", "6h"]
DEFAULT_LEAD_CAP_EVERY = "1h"
ACTIVE_WINDOW = timedelta(minutes=60)

# Postgres advisory lock key (2x int32). Keep stable.
_ADVISORY_LOCK_KEY_1 = 424242
_ADVISORY_LOCK_KEY_2 = 1701


@dataclass(frozen=True)
class DesiredHeartbeat:
    every: str | None  # None means "off" (unset heartbeat in gateway config)
    step: int
    off: bool


def _is_active(*, now: datetime, last_chat_at: datetime | None, has_work: bool) -> bool:
    if has_work:
        return True
    if last_chat_at is None:
        return False
    return (now - last_chat_at) <= ACTIVE_WINDOW


def compute_desired_heartbeat(
    *,
    is_lead: bool,
    active: bool,
    step: int,
    active_every: str = DEFAULT_ACTIVE_EVERY,
    ladder: list[str] | None = None,
    lead_cap_every: str = DEFAULT_LEAD_CAP_EVERY,
) -> DesiredHeartbeat:
    """Return desired heartbeat for an agent.

    step: governor-managed backoff index.
      0 means just became active.
      1..len(LADDER) means ladder index-1.
      len(LADDER)+1 means off (for non-leads).
    """

    ladder = list(ladder or DEFAULT_LADDER)

    if active:
        return DesiredHeartbeat(every=active_every, step=0, off=False)

    # If idle, advance one rung.
    next_step = max(1, int(step) + 1)

    if is_lead:
        # Leads never go fully off; cap at lead_cap_every.
        if next_step <= len(ladder):
            next_every = ladder[next_step - 1]
        else:
            next_every = lead_cap_every
        return DesiredHeartbeat(every=next_every, step=min(next_step, len(ladder)), off=False)

    # Non-leads can go fully off after max backoff.
    if next_step <= len(ladder):
        return DesiredHeartbeat(every=ladder[next_step - 1], step=next_step, off=False)

    return DesiredHeartbeat(every=None, step=len(ladder) + 1, off=True)


async def _acquire_lock(session: AsyncSession) -> bool:
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:k1, :k2)"),
        params={"k1": _ADVISORY_LOCK_KEY_1, "k2": _ADVISORY_LOCK_KEY_2},
    )
    row = result.first()
    return bool(row and row[0])


async def _release_lock(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_unlock(:k1, :k2)"),
        params={"k1": _ADVISORY_LOCK_KEY_1, "k2": _ADVISORY_LOCK_KEY_2},
    )


async def _latest_chat_by_board(session: AsyncSession) -> dict[UUID, datetime]:
    # Only chat memory items.
    rows = await session.execute(
        text(
            """
            SELECT board_id, MAX(created_at) AS last_chat_at
            FROM board_memory
            WHERE is_chat = true
            GROUP BY board_id
            """,
        ),
    )
    result: dict[UUID, datetime] = {}
    for board_id, last_chat_at in rows.all():
        if board_id and last_chat_at:
            result[board_id] = last_chat_at
    return result


async def _has_work_map(session: AsyncSession) -> dict[UUID, bool]:
    # Work = tasks assigned to the agent that are in_progress or review.
    # Map by agent_id.
    rows = await session.execute(
        text(
            """
            SELECT assigned_agent_id, COUNT(*)
            FROM tasks
            WHERE assigned_agent_id IS NOT NULL
              AND status IN ('in_progress', 'review')
            GROUP BY assigned_agent_id
            """,
        ),
    )
    result: dict[UUID, bool] = {}
    for agent_id, count in rows.all():
        if agent_id:
            result[agent_id] = bool(count and int(count) > 0)
    return result


def _merge_heartbeat_config(agent: Agent, every: str) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "every": every,
        "target": "last",
        "includeReasoning": False,
    }
    if isinstance(agent.heartbeat_config, dict):
        merged.update({k: v for k, v in agent.heartbeat_config.items() if k != "every"})
        merged["every"] = every
    return merged


async def _patch_gateway(
    *,
    gateway: Gateway,
    agent_entries: list[tuple[str, str, dict[str, Any] | None]],
) -> None:
    control_plane = OpenClawGatewayControlPlane(
        GatewayClientConfig(url=gateway.url or "", token=gateway.token),
    )
    # patch_agent_heartbeats supports None heartbeat entries after our patch.
    await control_plane.patch_agent_heartbeats(agent_entries)


async def run_governor_once() -> None:
    if not getattr(settings, "auto_heartbeat_governor_enabled", False):
        return

    async with async_session_maker() as session:
        locked = await _acquire_lock(session)
        if not locked:
            logger.debug("auto_heartbeat.skip_locked")
            return

        try:
            now = utcnow()
            agents = (
                await session.exec(
                    select(Agent).where(
                        col(Agent.auto_heartbeat_enabled).is_(True),
                        col(Agent.gateway_id).is_not(None),
                    ),
                )
            ).all()
            if not agents:
                return

            # Batch compute activity signals.
            chat_by_board = await _latest_chat_by_board(session)
            has_work_by_agent = await _has_work_map(session)

            # Load board policies referenced by these agents.
            board_ids = {a.board_id for a in agents if a.board_id}
            boards = (
                (await session.exec(select(Board).where(col(Board.id).in_(board_ids)))).all()
                if board_ids
                else []
            )
            board_by_id = {b.id: b for b in boards}

            # Load gateways referenced by these agents.
            gateway_ids = {a.gateway_id for a in agents if a.gateway_id}
            gateways = (
                await session.exec(select(Gateway).where(col(Gateway.id).in_(gateway_ids)))
            ).all()
            gateway_by_id = {g.id: g for g in gateways}

            # Group patches per gateway.
            patches_by_gateway: dict[UUID, list[tuple[str, str, dict[str, Any] | None]]] = {}
            changed = 0

            for agent in agents:
                if not agent.auto_heartbeat_enabled:
                    continue
                gateway = gateway_by_id.get(agent.gateway_id)
                if gateway is None or not gateway.url or not gateway.workspace_root:
                    continue

                board = board_by_id.get(agent.board_id) if agent.board_id else None
                if board is not None and not bool(board.auto_heartbeat_governor_enabled):
                    continue

                last_chat_at = None
                if agent.board_id:
                    last_chat_at = chat_by_board.get(agent.board_id)

                has_work = has_work_by_agent.get(agent.id, False)
                trigger = (
                    str(getattr(board, "auto_heartbeat_governor_activity_trigger_type", "B"))
                    if board is not None
                    else "B"
                )
                active = _is_active(
                    now=now,
                    last_chat_at=last_chat_at,
                    has_work=(has_work if trigger != "A" else False),
                )

                ladder = (
                    list(getattr(board, "auto_heartbeat_governor_ladder", None) or [])
                    if board is not None
                    else None
                )
                if not ladder:
                    ladder = None
                lead_cap = (
                    str(
                        getattr(
                            board, "auto_heartbeat_governor_lead_cap_every", DEFAULT_LEAD_CAP_EVERY
                        )
                    )
                    if board is not None
                    else DEFAULT_LEAD_CAP_EVERY
                )

                desired = compute_desired_heartbeat(
                    is_lead=bool(agent.is_board_lead),
                    active=active,
                    step=int(agent.auto_heartbeat_step or 0),
                    ladder=ladder,
                    lead_cap_every=lead_cap,
                )

                # Determine if we need to update DB state.
                needs_db = (
                    bool(agent.auto_heartbeat_off) != desired.off
                    or int(agent.auto_heartbeat_step or 0) != desired.step
                )

                # Determine desired heartbeat payload.
                agent_id = _agent_key(agent)
                workspace_path = _workspace_path(agent, gateway.workspace_root)

                heartbeat_payload: dict[str, Any] | None
                if desired.every is None:
                    heartbeat_payload = None
                else:
                    heartbeat_payload = _merge_heartbeat_config(agent, desired.every)

                # Compare with current (only best-effort; gateway patch is idempotent).
                # If agent is off, patch regardless (None removes heartbeat).
                if desired.every is None:
                    patches_by_gateway.setdefault(gateway.id, []).append(
                        (agent_id, workspace_path, None),
                    )
                else:
                    # Only patch when 'every' differs or we were previously off.
                    current_every = None
                    if isinstance(agent.heartbeat_config, dict):
                        current_every = agent.heartbeat_config.get("every")
                    if current_every != desired.every or bool(agent.auto_heartbeat_off):
                        patches_by_gateway.setdefault(gateway.id, []).append(
                            (agent_id, workspace_path, heartbeat_payload),
                        )

                # Keep heartbeat_config in sync for non-off entries.
                needs_heartbeat_config_update = (
                    desired.every is not None and agent.heartbeat_config != heartbeat_payload
                )

                if needs_db or needs_heartbeat_config_update:
                    agent.auto_heartbeat_step = desired.step
                    agent.auto_heartbeat_off = desired.off
                    if active and needs_db:
                        agent.auto_heartbeat_last_active_at = now
                    if needs_heartbeat_config_update:
                        agent.heartbeat_config = heartbeat_payload
                    agent.updated_at = now
                    session.add(agent)
                    changed += 1

            if changed:
                await session.commit()

            # Apply patches gateway-by-gateway.
            for gateway_id, entries in patches_by_gateway.items():
                gateway = gateway_by_id.get(gateway_id)
                if gateway is None:
                    continue
                try:
                    await _patch_gateway(gateway=gateway, agent_entries=entries)
                except Exception as exc:
                    logger.warning(
                        "auto_heartbeat.patch_failed",
                        extra={"gateway_id": str(gateway_id), "error": str(exc)},
                    )

            logger.info(
                "auto_heartbeat.run_complete",
                extra={
                    "agents": len(agents),
                    "db_changed": changed,
                    "gateways": len(patches_by_gateway),
                },
            )
        finally:
            try:
                await _release_lock(session)
            except Exception:
                logger.exception("auto_heartbeat.unlock_failed")


async def governor_loop() -> None:
    """Run the governor forever."""
    interval = getattr(settings, "auto_heartbeat_governor_interval_seconds", 300)
    interval = max(30, int(interval))
    logger.info(
        "auto_heartbeat.loop_start",
        extra={"interval_seconds": interval},
    )
    while True:
        try:
            await run_governor_once()
        except Exception:
            logger.exception("auto_heartbeat.loop_error")
        await asyncio.sleep(interval)
