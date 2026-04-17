"""Heartbeat deadline watchdog (invariant I7).

Implements the Phase 0 §A.1/§A.6 contract from
``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``:

- Every 60 seconds, scan for agents in ``status='online'`` with
  ``checkin_deadline_at IS NULL``.
- Before repair, write a forensic ``AgentHeartbeatRepairEvent`` capturing
  the pre-repair state (prev deadline, last_seen, wake_attempts, elapsed
  time since last-seen). This preserves the evidence that a writer-path
  bug dropped the deadline.
- Auto-repair the deadline to ``now + heartbeat_interval + grace``.
- Emit a WARN alert when the same agent is repaired 3+ times within the
  last hour — that pattern indicates a persistent writer-bug, not a
  one-off glitch. Operator-alert routing (e.g., WhatsApp/Baileys) is a
  downstream concern; this module emits the log line and the table row,
  which any alert pipeline can consume.

The watchdog is independent of the existing ``heartbeat_sweep_loop``,
which handles agents with *expired* deadlines. Null-deadline online
agents are a separate class — the sweep skips them because its
``checkin_deadline_at is_not(None)`` filter excludes them by design.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.agents import Agent
from app.services.openclaw.constants import (
    CHECKIN_DEADLINE_AFTER_WAKE,
    DEFAULT_HEARTBEAT_CONFIG,
    HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
)

logger = get_logger(__name__)

WATCHDOG_INTERVAL_SECONDS = 60
REPEAT_REPAIR_ALERT_WINDOW = timedelta(hours=1)
REPEAT_REPAIR_ALERT_THRESHOLD = 3
REPAIR_REASON_NULL_DEADLINE = "null_deadline_on_online"


@dataclass(frozen=True)
class RepairOutcome:
    """Per-agent result of a single watchdog repair."""

    agent_id: str
    agent_name: str
    action: str  # "repaired" | "failed"
    prev_deadline: str | None
    new_deadline: str | None
    repeat_count_1h: int = 0
    alert_triggered: bool = False
    reason: str | None = None


@dataclass
class SweepReport:
    total_scanned: int = 0
    repaired: int = 0
    failed: int = 0
    alerts: int = 0
    outcomes: list[RepairOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "repaired": self.repaired,
            "failed": self.failed,
            "alerts": self.alerts,
        }


def _parse_heartbeat_interval(every: str | None) -> timedelta:
    """Translate an ``every`` config value to a timedelta.

    Accepted: ``"10m"``, ``"60s"``, ``"1h"``. Anything unparseable falls
    back to the DEFAULT_HEARTBEAT_CONFIG value. Returns ``timedelta(0)``
    only when the config explicitly asks for no heartbeat (``"0m"``), so
    callers can treat that as "watchdog cannot set a deadline".
    """

    unit_seconds = {"s": 1, "m": 60, "h": 3600}
    default = str(DEFAULT_HEARTBEAT_CONFIG["every"])
    candidate = (every if isinstance(every, str) and every.strip() else default).strip().lower()
    if len(candidate) < 2 or candidate[-1] not in unit_seconds:
        return _parse_heartbeat_interval(default) if candidate != default else timedelta(minutes=10)
    try:
        amount = int(candidate[:-1])
    except ValueError:
        return _parse_heartbeat_interval(default) if candidate != default else timedelta(minutes=10)
    return timedelta(seconds=amount * unit_seconds[candidate[-1]])


def compute_repair_deadline(agent: Agent, *, now: datetime) -> datetime:
    """Derive a replacement deadline for a null-deadline online agent.

    Priority:
      1. If ``heartbeat_config.every`` is set, use ``now + every + grace``.
      2. Fall back to ``now + CHECKIN_DEADLINE_AFTER_WAKE`` — the same
         conservative horizon used for newly-provisioned agents.
    """

    interval = CHECKIN_DEADLINE_AFTER_WAKE
    cfg = agent.heartbeat_config
    if isinstance(cfg, dict):
        every = cfg.get("every")
        parsed = _parse_heartbeat_interval(every if isinstance(every, str) else None)
        # Treat disabled heartbeat (0m) as "use the provisioning fallback".
        if parsed > timedelta(0):
            interval = parsed + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL
    return now + interval


async def _count_recent_repairs(
    session: AsyncSession, *, agent_id: Any, since: datetime
) -> int:
    """Count ``AgentHeartbeatRepairEvent`` rows for an agent since ``since``."""

    statement = select(func.count()).select_from(AgentHeartbeatRepairEvent).where(
        and_(
            col(AgentHeartbeatRepairEvent.agent_id) == agent_id,
            col(AgentHeartbeatRepairEvent.created_at) >= since,
        )
    )
    result = await session.exec(statement)
    value = result.one()
    return int(value or 0)


async def sweep_null_deadlines_once(session: AsyncSession) -> SweepReport:
    """Run one watchdog pass against the given session.

    Each repaired agent gets a forensic row in
    ``agent_heartbeat_repair_events`` and an updated
    ``checkin_deadline_at``. Repeat-repair alerts are logged at WARN with
    a structured signal that downstream operator-alert routing can match.
    """

    now = utcnow()
    statement = select(Agent).where(
        and_(
            col(Agent.status) == "online",
            col(Agent.checkin_deadline_at).is_(None),
        )
    )
    candidates = (await session.exec(statement)).all()
    report = SweepReport(total_scanned=len(candidates))

    alert_since = now - REPEAT_REPAIR_ALERT_WINDOW

    for agent in candidates:
        try:
            new_deadline = compute_repair_deadline(agent, now=now)
        except Exception as exc:  # pragma: no cover - defensive
            report.failed += 1
            report.outcomes.append(
                RepairOutcome(
                    agent_id=str(agent.id),
                    agent_name=agent.name,
                    action="failed",
                    prev_deadline=None,
                    new_deadline=None,
                    reason=f"deadline-compute-error: {exc!r}",
                )
            )
            logger.exception(
                "heartbeat_watchdog.compute_failed agent_id=%s", agent.id
            )
            continue

        elapsed = (
            (now - agent.last_seen_at).total_seconds()
            if agent.last_seen_at is not None
            else None
        )
        event = AgentHeartbeatRepairEvent(
            agent_id=agent.id,
            prev_deadline=None,
            last_seen_at=agent.last_seen_at,
            wake_attempts=agent.wake_attempts or 0,
            elapsed_since_last_seen_seconds=elapsed,
            repair_reason=REPAIR_REASON_NULL_DEADLINE,
            new_deadline=new_deadline,
        )
        session.add(event)
        agent.checkin_deadline_at = new_deadline
        session.add(agent)
        await session.commit()

        # The newly-written event now counts toward the 1h window.
        repeat_count = await _count_recent_repairs(
            session, agent_id=agent.id, since=alert_since
        )
        alert_triggered = repeat_count >= REPEAT_REPAIR_ALERT_THRESHOLD
        if alert_triggered:
            report.alerts += 1
            logger.warning(
                "heartbeat_watchdog.repeat_repair_alert "
                "agent_id=%s agent_name=%s repair_count_1h=%d window_seconds=%d "
                "threshold=%d",
                agent.id,
                agent.name,
                repeat_count,
                int(REPEAT_REPAIR_ALERT_WINDOW.total_seconds()),
                REPEAT_REPAIR_ALERT_THRESHOLD,
            )
        else:
            logger.info(
                "heartbeat_watchdog.repaired "
                "agent_id=%s agent_name=%s new_deadline=%s repair_count_1h=%d",
                agent.id,
                agent.name,
                new_deadline.isoformat(),
                repeat_count,
            )

        report.repaired += 1
        report.outcomes.append(
            RepairOutcome(
                agent_id=str(agent.id),
                agent_name=agent.name,
                action="repaired",
                prev_deadline=None,
                new_deadline=new_deadline.isoformat(),
                repeat_count_1h=repeat_count,
                alert_triggered=alert_triggered,
            )
        )

    if report.total_scanned > 0:
        logger.info(
            "heartbeat_watchdog.sweep_complete scanned=%d repaired=%d failed=%d alerts=%d",
            report.total_scanned,
            report.repaired,
            report.failed,
            report.alerts,
        )
    return report


async def heartbeat_watchdog_loop(stop_event: asyncio.Event) -> None:
    """Long-running task: sweep at WATCHDOG_INTERVAL_SECONDS until stopped."""

    logger.info(
        "heartbeat_watchdog.loop_started interval_seconds=%s",
        WATCHDOG_INTERVAL_SECONDS,
    )
    try:
        while not stop_event.is_set():
            try:
                async with async_session_maker() as session:
                    await sweep_null_deadlines_once(session)
            except Exception:
                logger.exception("heartbeat_watchdog.iteration_failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=WATCHDOG_INTERVAL_SECONDS
                )
            except TimeoutError:
                continue
    finally:
        logger.info("heartbeat_watchdog.loop_stopped")


async def stop_heartbeat_watchdog(
    task: asyncio.Task[None] | None, stop_event: asyncio.Event
) -> None:
    """Graceful shutdown for the watchdog loop."""

    stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
