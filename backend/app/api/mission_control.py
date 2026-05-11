from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.boards import Board
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import openclaw_call

logger = get_logger(__name__)


async def _get_gateway_config_for_board(
    session: AsyncSession, board_id: UUID
) -> GatewayClientConfig | None:
    """Get gateway config for a board, with fallback URL if gateway has no URL configured."""
    from app.models.gateways import Gateway
    from app.services.openclaw.gateway_dispatch import GatewayDispatchService

    board = (await session.exec(select(Board).where(col(Board.id) == board_id))).first()
    logger.info(
        "pause/resume: board=%s gateway_id=%s", board_id, board.gateway_id if board else None
    )
    if not board or not board.gateway_id:
        logger.warning("pause/resume: no board or gateway_id")
        return None

    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    logger.info("pause/resume: dispatch.config=%s", config)

    # Fallback: if gateway has no URL configured, use the known gateway URL
    if config is None:
        gateway = (
            await session.exec(select(Gateway).where(col(Gateway.id) == board.gateway_id))
        ).first()
        logger.info(
            "pause/resume: gateway=%s url=%s token=%s",
            gateway.id if gateway else None,
            gateway.url if gateway else None,
            gateway.token[:10] if gateway and gateway.token else None,
        )
        if gateway:
            cfg = GatewayClientConfig(
                url="ws://192.168.2.60:18789",
                token=gateway.token or None,
                allow_insecure_tls=True,
            )
            logger.info("pause/resume: using fallback config")
            return cfg

    return config


router = APIRouter(prefix="/api/mission-control", tags=["metrics"])


def _heartbeat_enabled(agent: Agent) -> bool:
    cfg = agent.heartbeat_config or {}
    every = str(cfg.get("every") or "").strip().lower()
    return bool(every and every != "0m")


@router.get("/heartbeats")
async def mission_control_heartbeats() -> dict[str, Any]:
    now = utcnow()
    async with async_session_maker() as session:
        agents = (await session.exec(select(Agent).order_by(col(Agent.name).asc()))).all()
        board_ids = {a.board_id for a in agents if a.board_id is not None}
        boards: dict[UUID, Board] = {}
        if board_ids:
            board_rows = (
                await session.exec(select(Board).where(col(Board.id).in_(board_ids)))
            ).all()
            boards = {b.id: b for b in board_rows}

    monitored = []
    for agent in agents:
        if not _heartbeat_enabled(agent):
            continue
        deadline = agent.checkin_deadline_at
        monitored.append(
            {
                "agent_id": str(agent.id),
                "name": agent.name,
                "board_id": str(agent.board_id) if agent.board_id else None,
                "board_name": (boards[agent.board_id].name if agent.board_id in boards else None),
                "status": agent.status,
                "enabled": True,
                "last_seen_at": (
                    agent.last_seen_at.isoformat() + "Z" if agent.last_seen_at else None
                ),
                "checkin_deadline_at": deadline.isoformat() + "Z" if deadline else None,
                "wake_attempts": agent.wake_attempts,
                "last_wake_sent_at": (
                    agent.last_wake_sent_at.isoformat() + "Z" if agent.last_wake_sent_at else None
                ),
                "seconds_until_deadline": (
                    int((deadline - now).total_seconds()) if deadline else None
                ),
                "overdue": bool(deadline and deadline < now),
                "is_board_lead": bool(agent.is_board_lead),
            }
        )

    monitored.sort(key=lambda item: ((not item["overdue"]), item["name"]))
    return {
        "ok": True,
        "generated_at": now.isoformat() + "Z",
        "agents_monitored": len(monitored),
        "agents": monitored,
    }


# ---------------------------------------------------------------------------
# Board pause/resume endpoints
# ---------------------------------------------------------------------------


@router.post("/boards/{board_id}/pause", status_code=200)
async def api_pause_board(board_id: str) -> dict[str, Any]:
    """Mark a board as paused — heartbeat monitor will skip nudge/wake for its agents.

    Also disables agent heartbeats in the gateway by calling set-heartbeats RPC
    for all agents assigned to this board.
    """
    if not board_id or len(board_id) > 256:
        raise HTTPException(status_code=422, detail="Invalid board_id")
    try:
        bid = uuid.UUID(board_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid board_id format")

    now = utcnow()
    async with async_session_maker() as session:
        await session.execute(text("""
            INSERT INTO board_pause_states (board_id, is_paused, paused_at, paused_by)
            VALUES (:board_id, TRUE, :paused_at, 'human')
            ON CONFLICT(board_id) DO UPDATE SET
                is_paused = TRUE, paused_at = EXCLUDED.paused_at, paused_by = 'human'
        """).bindparams(board_id=bid, paused_at=now))

        # Upsert heartbeat rows for all board agents and disable them (PostgreSQL state)
        await session.execute(text("""
            INSERT INTO agent_heartbeats (agent_id, enabled, last_status)
            SELECT id, FALSE, 'idle'
            FROM agents WHERE board_id = :board_id
            ON CONFLICT(agent_id) DO UPDATE SET enabled = FALSE, last_status = 'idle'
        """).bindparams(board_id=bid))

        # Get gateway config while session is still open
        config = await _get_gateway_config_for_board(session, bid)

        await session.commit()

    # Gateway `set-heartbeats` is global per gateway, not per-agent.
    logger.info("pause: calling gateway RPC once globally config=%s", config)
    if config is not None:
        try:
            result = await openclaw_call(
                "set-heartbeats",
                {"enabled": False},
                config=config,
            )
            logger.info("pause: set-heartbeats success enabled=False result=%s", result)
        except Exception as exc:
            logger.warning(
                "pause_board.set_heartbeats_failed board_id=%s enabled=False error=%s",
                board_id,
                str(exc),
                exc_info=True,
            )

    logger.info("board %s paused (global heartbeats disabled on gateway)", board_id)
    return {"ok": True, "board_id": board_id, "is_paused": True, "paused_at": now}


@router.post("/boards/{board_id}/resume", status_code=200)
async def api_resume_board(board_id: str) -> dict[str, Any]:
    """Mark a board as resumed — heartbeat monitor resumes normal nudge/wake behaviour.

    Also re-enables agent heartbeats in the gateway by calling set-heartbeats RPC
    for all agents assigned to this board.
    """
    if not board_id or len(board_id) > 256:
        raise HTTPException(status_code=422, detail="Invalid board_id")
    try:
        bid = uuid.UUID(board_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid board_id format")

    async with async_session_maker() as session:
        await session.execute(text("""
            INSERT INTO board_pause_states (board_id, is_paused, paused_at, paused_by)
            VALUES (:board_id, FALSE, NULL, NULL)
            ON CONFLICT(board_id) DO UPDATE SET
                is_paused = FALSE, paused_at = NULL, paused_by = NULL
        """).bindparams(board_id=bid))

        # Upsert heartbeat rows for all board agents and enable them (PostgreSQL state)
        await session.execute(text("""
            INSERT INTO agent_heartbeats (agent_id, enabled, last_status)
            SELECT id, TRUE, 'idle'
            FROM agents WHERE board_id = :board_id
            ON CONFLICT(agent_id) DO UPDATE SET enabled = TRUE, last_status = 'idle'
        """).bindparams(board_id=bid))

        # Fetch gateway config while session is still open
        config = await _get_gateway_config_for_board(session, bid)

        await session.commit()

    # Gateway `set-heartbeats` is global per gateway, not per-agent.
    if config is not None:
        try:
            result = await openclaw_call(
                "set-heartbeats",
                {"enabled": True},
                config=config,
            )
            logger.info("resume: set-heartbeats success enabled=True result=%s", result)
        except Exception as exc:
            logger.warning(
                "resume_board.set_heartbeats_failed board_id=%s enabled=True error=%s",
                board_id,
                str(exc),
                exc_info=True,
            )

    logger.info("board %s resumed (global heartbeats re-enabled on gateway)", board_id)
    return {"ok": True, "board_id": board_id, "is_paused": False}


@router.get("/boards/{board_id}/pause", status_code=200)
async def api_get_board_pause_state(board_id: str) -> dict[str, Any]:
    """Return the current pause state for a board."""
    if not board_id or len(board_id) > 256:
        raise HTTPException(status_code=422, detail="Invalid board_id")
    try:
        bid = uuid.UUID(board_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid board_id format")

    async with async_session_maker() as session:
        result = await session.execute(text("""
            SELECT is_paused, paused_at, paused_by FROM board_pause_states WHERE board_id = :board_id
        """).bindparams(board_id=bid))
        row = result.first()

    if row is None:
        return {"board_id": board_id, "is_paused": False, "paused_at": None, "paused_by": None}
    return {
        "board_id": board_id,
        "is_paused": bool(row[0]),
        "paused_at": row[1],
        "paused_by": row[2],
    }
