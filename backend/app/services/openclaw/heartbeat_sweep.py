"""Periodic heartbeat sweep loop for stale agents and stuck tasks."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta

from sqlmodel import col, select

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.tasks import Task
from app.services.openclaw.constants import MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError, openclaw_call
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.provisioning import reconcile_agent_heartbeat_enabled_flags
from app.services.task_dependencies import blocked_by_for_task

logger = get_logger(__name__)
SWEEP_INTERVAL_SECONDS = 300
_RECONCILE_TIMEOUT_SECONDS = 60.0

# Tasks in_progress longer than this get a nudge to the assigned agent.
# The Supervisor's health scan has 30-min and 60-min thresholds; this
# backend sweep is a backup that catches cases where the Supervisor
# itself is stuck, offline, or behind on heartbeats.
STUCK_TASK_THRESHOLD = timedelta(minutes=60)
# Don't re-nudge the same task within the cooldown window.
# Maps task_id → last nudge timestamp. Pruned each cycle.
NUDGE_COOLDOWN = timedelta(minutes=60)
from datetime import datetime as _datetime_type
_recently_nudged_tasks: dict[str, _datetime_type] = {}


def _stuck_task_nudge_candidate(
    task: Task,
    *,
    attempted_agent_ids: set[str],
    blocked_by_task_ids: list[object],
) -> bool:
    if task.operator_decision_required:
        return False
    if blocked_by_task_ids:
        return False
    if task.assigned_agent_id is None:
        return False
    return str(task.assigned_agent_id) not in attempted_agent_ids


async def _send_stuck_task_execution_nudge(
    *,
    dispatch: GatewayDispatchService,
    session_key: str,
    config: GatewayClientConfig,
    agent_name: str,
    message: str,
) -> OpenClawGatewayError | None:
    """Reset stale context before delivering the stuck-task nudge."""
    try:
        await openclaw_call("sessions.reset", {"key": session_key}, config=config)
    except OpenClawGatewayError as exc:
        return exc
    logger.info(
        "heartbeat_sweep.stuck_task_session_reset session_key=%s agent_name=%s",
        session_key,
        agent_name,
    )
    return await dispatch.try_send_agent_message(
        session_key=session_key,
        config=config,
        agent_name=agent_name,
        message=message,
        deliver=True,
    )


def _heartbeat_enabled(agent: Agent) -> bool:
    cfg = agent.heartbeat_config or {}
    every = str(cfg.get("every") or "").strip().lower()
    return bool(every and every != "0m")


async def _try_deliver_heartbeat_wake(
    *,
    session,
    gateway: Gateway,
    agent: Agent,
    board: Board | None,
) -> bool:
    orchestrator = AgentLifecycleOrchestrator(session)
    try:
        result = await asyncio.wait_for(
            orchestrator.run_lifecycle(
                gateway=gateway,
                agent_id=agent.id,
                board=board,
                user=None,
                action="update",
                auth_token=None,
                force_bootstrap=False,
                reset_session=True,
                wake=True,
                deliver_wakeup=True,
                wakeup_verb="updated",
                clear_confirm_token=True,
                raise_gateway_errors=False,
            ),
            timeout=_RECONCILE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "heartbeat_sweep.wake_failed agent_id=%s name=%s error=%s",
            agent.id,
            agent.name,
            exc,
        )
        return False

    if getattr(result, "last_provision_error", None):
        logger.warning(
            "heartbeat_sweep.wake_not_delivered agent_id=%s name=%s error=%s",
            agent.id,
            agent.name,
            result.last_provision_error,
        )
        return False
    return True


async def sweep_once() -> dict[str, int]:
    now = utcnow()
    scanned = 0
    overdue = 0
    woke = 0
    offline = 0

    async with async_session_maker() as session:
        agents = (
            await session.exec(
                select(Agent).where(Agent.checkin_deadline_at.is_not(None))
            )
        ).all()

        for agent in agents:
            if not _heartbeat_enabled(agent):
                continue
            scanned += 1
            deadline = agent.checkin_deadline_at
            if deadline is None or deadline > now:
                continue
            overdue += 1

            if agent.last_seen_at is not None and agent.last_seen_at >= deadline:
                continue

            if agent.wake_attempts >= MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN:
                agent.status = "offline"
                agent.checkin_deadline_at = None
                agent.last_provision_error = "Heartbeat sweep marked agent offline after max wake attempts"
                agent.updated_at = now
                session.add(agent)
                await session.commit()
                offline += 1
                logger.warning(
                    "heartbeat_sweep.offline agent_id=%s name=%s wake_attempts=%s",
                    agent.id,
                    agent.name,
                    agent.wake_attempts,
                )
                continue

            gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
            if gateway is None:
                logger.warning(
                    "heartbeat_sweep.skip_missing_gateway agent_id=%s gateway_id=%s",
                    agent.id,
                    agent.gateway_id,
                )
                continue

            board = None
            if agent.board_id is not None:
                board = await Board.objects.by_id(agent.board_id).first(session)
                if board is None:
                    logger.warning(
                        "heartbeat_sweep.skip_missing_board agent_id=%s board_id=%s",
                        agent.id,
                        agent.board_id,
                    )
                    continue

            logger.info(
                "heartbeat_sweep.wake agent_id=%s name=%s deadline=%s wake_attempts=%s",
                agent.id,
                agent.name,
                deadline.isoformat(),
                agent.wake_attempts,
            )
            if await _try_deliver_heartbeat_wake(
                session=session,
                gateway=gateway,
                agent=agent,
                board=board,
            ):
                woke += 1

    logger.info(
        "heartbeat_sweep.summary scanned=%s overdue=%s woke=%s offline=%s",
        scanned,
        overdue,
        woke,
        offline,
    )
    return {"scanned": scanned, "overdue": overdue, "woke": woke, "offline": offline}


async def sweep_stuck_tasks() -> dict[str, int]:
    """Detect tasks stuck in ``in_progress`` longer than
    ``STUCK_TASK_THRESHOLD`` and nudge the assigned agent.

    This is a backup for the Supervisor's health-scan nudge thresholds.
    If the Supervisor is offline, stuck, or behind on heartbeats, this
    sweep catches the gap. It does NOT replace the Supervisor — it only
    fires when the Supervisor hasn't already handled the situation.
    """
    global _recently_nudged_tasks
    now = utcnow()
    cutoff = now - STUCK_TASK_THRESHOLD
    scanned = 0
    nudged = 0
    attempted_agent_ids: set[str] = set()

    async with async_session_maker() as session:
        stuck_tasks = (
            await session.exec(
                select(Task)
                .where(col(Task.status) == "in_progress")
                .where(col(Task.updated_at) < cutoff)
                .where(col(Task.assigned_agent_id).is_not(None))
                .where(col(Task.operator_decision_required).is_(False))
            )
        ).all()

        for task in stuck_tasks:
            scanned += 1
            task_key = str(task.id)

            # Don't re-nudge within cooldown window (default 60 min).
            last_nudge = _recently_nudged_tasks.get(task_key)
            if last_nudge and (now - last_nudge) < NUDGE_COOLDOWN:
                continue
            blocked_by_task_ids = []
            if task.board_id is not None:
                blocked_by_task_ids = await blocked_by_for_task(
                    session,
                    board_id=task.board_id,
                    task_id=task.id,
                )
            if not _stuck_task_nudge_candidate(
                task,
                attempted_agent_ids=attempted_agent_ids,
                blocked_by_task_ids=blocked_by_task_ids,
            ):
                continue
            attempted_agent_ids.add(str(task.assigned_agent_id))

            agent = await session.get(Agent, task.assigned_agent_id)
            if agent is None or agent.status != "online":
                continue
            if not agent.openclaw_session_id:
                continue

            board = None
            if agent.board_id is not None:
                board = await Board.objects.by_id(agent.board_id).first(session)
            gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
            if gateway is None or not gateway.url:
                continue

            age_min = int((now - task.updated_at).total_seconds() / 60)
            nudge_message = (
                f"SWEEP: Task \"{task.title}\" ({task.id}) has been in_progress "
                f"for {age_min} min with no status update. "
                f"Post a progress comment or report a blocker. @lead"
            )

            config = GatewayClientConfig(
                url=gateway.url,
                token=gateway.token,
                allow_insecure_tls=gateway.allow_insecure_tls,
                disable_device_pairing=gateway.disable_device_pairing,
            )
            dispatch = GatewayDispatchService(session)
            error = await _send_stuck_task_execution_nudge(
                dispatch=dispatch,
                session_key=agent.openclaw_session_id,
                config=config,
                agent_name=agent.name,
                message=nudge_message,
            )
            if error is None:
                nudged += 1
                _recently_nudged_tasks[task_key] = now
                logger.info(
                    "heartbeat_sweep.stuck_task_nudge task_id=%s title=%s "
                    "agent_id=%s agent_name=%s age_min=%s",
                    task.id,
                    task.title[:40],
                    agent.id,
                    agent.name,
                    age_min,
                )
            else:
                logger.warning(
                    "heartbeat_sweep.stuck_task_nudge_failed task_id=%s "
                    "agent_id=%s error=%s",
                    task.id,
                    agent.id,
                    str(error),
                )

    # Prune entries older than the cooldown so they can be re-nudged.
    _recently_nudged_tasks.update({
        k: v for k, v in list(_recently_nudged_tasks.items())
        if (now - v) < NUDGE_COOLDOWN
    })
    # Remove expired entries
    for k in list(_recently_nudged_tasks):
        if (now - _recently_nudged_tasks[k]) >= NUDGE_COOLDOWN:
            del _recently_nudged_tasks[k]

    if scanned > 0:
        logger.info(
            "heartbeat_sweep.stuck_tasks scanned=%s nudged=%s",
            scanned,
            nudged,
        )
    return {"scanned": scanned, "nudged": nudged}


async def heartbeat_sweep_loop(stop_event: asyncio.Event) -> None:
    logger.info("heartbeat_sweep.loop_started interval_seconds=%s", SWEEP_INTERVAL_SECONDS)
    try:
        while not stop_event.is_set():
            try:
                reconcile_result = await reconcile_agent_heartbeat_enabled_flags()
                logger.info(
                    "heartbeat_sweep.reconcile enabled=%s disabled=%s updated=%s",
                    reconcile_result.get("enabled_agents", 0),
                    reconcile_result.get("disabled_agents", 0),
                    reconcile_result.get("updated_agents", 0),
                )
                await sweep_once()
                await sweep_stuck_tasks()
            except Exception:
                logger.exception("heartbeat_sweep.iteration_failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=SWEEP_INTERVAL_SECONDS)
            except TimeoutError:
                continue
    finally:
        logger.info("heartbeat_sweep.loop_stopped")


async def stop_heartbeat_sweep(task: asyncio.Task[None] | None, stop_event: asyncio.Event) -> None:
    stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
