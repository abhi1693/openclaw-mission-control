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
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.durations import parse_every_to_seconds
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.agents import Agent
from app.services.openclaw.constants import (
    CHECKIN_DEADLINE_AFTER_WAKE,
    HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
)

logger = get_logger(__name__)

WATCHDOG_INTERVAL_SECONDS = 60
REPEAT_REPAIR_ALERT_WINDOW = timedelta(hours=1)
REPEAT_REPAIR_ALERT_THRESHOLD = 3


class RepairReason(StrEnum):
    """Categorized cause of a watchdog repair. Stored in the forensic log."""

    NULL_DEADLINE_ON_ONLINE = "null_deadline_on_online"


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


def compute_repair_deadline(agent: Agent, *, now: datetime) -> datetime:
    """Derive a replacement deadline for a null-deadline online agent.

    Uses the agent's ``heartbeat_config.every`` when parseable, falling
    back to ``CHECKIN_DEADLINE_AFTER_WAKE`` — the same conservative horizon
    used for newly-provisioned agents — when the config is absent, empty,
    disabled, or malformed.

    Note: ``AgentLifecycleService._next_heartbeat_deadline`` computes a
    similar value during normal lifecycle transitions but returns ``None``
    for disabled heartbeats. The watchdog must always return a concrete
    deadline (the whole point is avoiding the null-deadline state), so the
    two code paths diverge intentionally. Consolidation is deferred until
    a third caller appears.
    """

    interval = CHECKIN_DEADLINE_AFTER_WAKE
    cfg = agent.heartbeat_config
    if isinstance(cfg, dict):
        every = cfg.get("every")
        if isinstance(every, str) and every.strip():
            with suppress(ValueError):
                seconds = parse_every_to_seconds(every)
                interval = (
                    timedelta(seconds=seconds) + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL
                )
    return now + interval


async def _count_recent_repairs_by_agent(
    session: AsyncSession, *, since: datetime
) -> dict[UUID, int]:
    """Return repair count per agent within the alert window, in one query."""

    statement = (
        select(AgentHeartbeatRepairEvent.agent_id, func.count())
        .where(col(AgentHeartbeatRepairEvent.created_at) >= since)
        .group_by(col(AgentHeartbeatRepairEvent.agent_id))
    )
    result = await session.exec(statement)
    return {row[0]: int(row[1]) for row in result.all()}


async def sweep_null_deadlines_once(session: AsyncSession) -> SweepReport:
    """Run one watchdog pass against the given session.

    All repaired agents are batched into a single ``session.commit()`` at
    the end, and the 1h-window repeat count is fetched once up-front via
    a GROUP BY query rather than per-agent round trips. Under a stuck-
    writer storm this keeps sweep cost at 2 round trips regardless of how
    many agents are being repaired.
    """

    now = utcnow()
    alert_since = now - REPEAT_REPAIR_ALERT_WINDOW
    candidates = (
        await session.exec(
            select(Agent).where(
                and_(
                    col(Agent.status) == "online",
                    col(Agent.checkin_deadline_at).is_(None),
                )
            )
        )
    ).all()
    report = SweepReport(total_scanned=len(candidates))
    if not candidates:
        return report

    prior_counts = await _count_recent_repairs_by_agent(session, since=alert_since)
    new_this_sweep: dict[UUID, int] = {}

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
            repair_reason=RepairReason.NULL_DEADLINE_ON_ONLINE,
            new_deadline=new_deadline,
        )
        session.add(event)
        agent.checkin_deadline_at = new_deadline
        session.add(agent)

        new_this_sweep[agent.id] = new_this_sweep.get(agent.id, 0) + 1
        repeat_count = (
            prior_counts.get(agent.id, 0) + new_this_sweep[agent.id]
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

    if report.repaired:
        await session.commit()

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
