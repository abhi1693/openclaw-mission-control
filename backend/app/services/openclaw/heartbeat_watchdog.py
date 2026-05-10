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
from sqlalchemy import update as sa_update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.durations import parse_every_to_seconds
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agent_heartbeat_repair_events import AgentHeartbeatRepairEvent
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.services.openclaw.constants import (
    CHECKIN_DEADLINE_AFTER_WAKE,
    HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
    OFFLINE_AFTER,
)
from app.services.openclaw.gateway_resolver import optional_gateway_client_config
from app.services.openclaw.gateway_rpc import models_auth_status
from app.services.openclaw.provisioning import _is_disabled_heartbeat_every

logger = get_logger(__name__)

WATCHDOG_INTERVAL_SECONDS = 60
REPEAT_REPAIR_ALERT_WINDOW = timedelta(hours=1)
REPEAT_REPAIR_ALERT_THRESHOLD = 3
# Part E.1 safety cap: ``openclaw_call`` has no end-to-end RPC timeout
# (only a 2s connect handshake), so an unresponsive gateway would
# otherwise block the 60s sweep forever. Auth-status is purely
# observability — 5s is plenty for any healthy gateway and keeps the
# sweep on schedule when one isn't.
_AUTH_STATUS_FETCH_TIMEOUT_SECONDS = 5


class RepairReason(StrEnum):
    """Categorized cause of a watchdog repair. Stored in the forensic log."""

    NULL_DEADLINE_ON_ONLINE = "null_deadline_on_online"


def _is_heartbeat_enabled(agent: Agent) -> bool:
    """True when the agent's config asks for periodic heartbeats.

    Disabled spellings ("0m", "off", "none", "disabled", "<= 0 numeric")
    are recognised via the canonical helper; the watchdog must not fabricate
    deadlines for agents that were configured to have none.
    """

    cfg = agent.heartbeat_config
    if not isinstance(cfg, dict):
        return True  # no config == default heartbeat is enabled
    return not _is_disabled_heartbeat_every(cfg.get("every"))


def _null_deadline_is_suspicious(agent: Agent, *, now: datetime) -> bool:
    """True when the null deadline has persisted past a healthy checkin window.

    Legitimate lifecycle writes (``wake=False`` template syncs,
    ``lifecycle_orchestrator.py:293``) briefly leave ``checkin_deadline_at``
    null until the agent's next natural heartbeat reinstates it. Waiting
    for ``OFFLINE_AFTER`` since the last seen-time (or since the last update
    if never seen) distinguishes that legitimate transient from a persistent
    writer-bug drop.
    """

    reference = agent.last_seen_at if agent.last_seen_at is not None else agent.updated_at
    if reference is None:
        return False
    return (now - reference) >= OFFLINE_AFTER


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
                interval = timedelta(seconds=seconds) + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL
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


async def _fetch_auth_status_by_gateway(
    session: AsyncSession, *, gateway_ids: set[UUID]
) -> dict[UUID, dict[str, Any] | None]:
    """Part E.1: fetch ``models.authStatus`` once per gateway per sweep.

    Best-effort. Any gateway whose RPC call fails (4.14 and earlier
    don't support the method; transport errors, permission issues,
    hung WS) maps to ``None``; the repair path still persists. Shared
    across the sweep's repair rows so a burst of same-gateway repairs
    pays the round-trip once.

    Each per-gateway RPC is wrapped in ``asyncio.wait_for`` — the
    underlying ``openclaw_call`` has no end-to-end response timeout
    after connect+send (only a 2s connect-handshake timeout), so a
    non-responsive gateway could otherwise stall the 60s watchdog
    sweep indefinitely. The cap is short (5s) because this is pure
    observability; an unreachable gateway reduces to ``None`` and
    repair still happens immediately.
    """

    if not gateway_ids:
        return {}
    gateways = (await session.exec(select(Gateway).where(col(Gateway.id).in_(gateway_ids)))).all()
    snapshots: dict[UUID, dict[str, Any] | None] = {}
    for gateway in gateways:
        config = optional_gateway_client_config(gateway)
        if config is None:
            snapshots[gateway.id] = None
            continue
        try:
            snapshots[gateway.id] = await asyncio.wait_for(
                models_auth_status(config=config),
                timeout=_AUTH_STATUS_FETCH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.info(
                "heartbeat_watchdog.auth_status_fetch_timeout gateway_id=%s",
                gateway.id,
            )
            snapshots[gateway.id] = None
    return snapshots


async def sweep_null_deadlines_once(session: AsyncSession) -> SweepReport:
    """Run one watchdog pass against the given session.

    Skips agents whose heartbeat is disabled and agents whose null state
    has not yet persisted past ``OFFLINE_AFTER`` (both are legitimate
    transient/resting states, not bugs). Uses a conditional UPDATE so a
    concurrent heartbeat commit races cleanly: only rows still null when
    the UPDATE fires get a new deadline. Logs and alerts fire AFTER the
    commit so downstream consumers never see repairs that didn't persist.
    """

    now = utcnow()
    alert_since = now - REPEAT_REPAIR_ALERT_WINDOW
    raw_candidates = (
        await session.exec(
            select(Agent).where(
                and_(
                    col(Agent.status) == "online",
                    col(Agent.checkin_deadline_at).is_(None),
                )
            )
        )
    ).all()

    candidates = [
        agent
        for agent in raw_candidates
        if _is_heartbeat_enabled(agent) and _null_deadline_is_suspicious(agent, now=now)
    ]
    report = SweepReport(total_scanned=len(candidates))
    if not candidates:
        return report

    prior_counts = await _count_recent_repairs_by_agent(session, since=alert_since)
    # Part E.1: one authStatus fetch per unique gateway in this sweep,
    # cached here and stamped on every repair row. Older gateways
    # (pre-4.15) return None via the helper's best-effort wrapper.
    gateway_ids = {agent.gateway_id for agent in candidates if agent.gateway_id is not None}
    auth_status_by_gateway = await _fetch_auth_status_by_gateway(session, gateway_ids=gateway_ids)
    pending_logs: list[tuple[RepairOutcome, bool]] = []
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
            logger.exception("heartbeat_watchdog.compute_failed agent_id=%s", agent.id)
            continue

        # Compare-and-swap: only repair if the deadline is still null. A
        # concurrent heartbeat/lifecycle write that beat us here wins;
        # rowcount==0 means "someone else handled it, skip".
        result = await session.exec(
            sa_update(Agent)
            .where(
                and_(
                    col(Agent.id) == agent.id,
                    col(Agent.checkin_deadline_at).is_(None),
                )
            )
            .values(checkin_deadline_at=new_deadline)
        )
        if getattr(result, "rowcount", 0) != 1:
            report.outcomes.append(
                RepairOutcome(
                    agent_id=str(agent.id),
                    agent_name=agent.name,
                    action="skipped",
                    prev_deadline=None,
                    new_deadline=None,
                    reason="concurrent-write-won",
                )
            )
            continue

        elapsed = (
            (now - agent.last_seen_at).total_seconds() if agent.last_seen_at is not None else None
        )
        event = AgentHeartbeatRepairEvent(
            agent_id=agent.id,
            prev_deadline=None,
            last_seen_at=agent.last_seen_at,
            wake_attempts=agent.wake_attempts or 0,
            elapsed_since_last_seen_seconds=elapsed,
            repair_reason=RepairReason.NULL_DEADLINE_ON_ONLINE,
            new_deadline=new_deadline,
            auth_status_snapshot=(
                auth_status_by_gateway.get(agent.gateway_id)
                if agent.gateway_id is not None
                else None
            ),
        )
        session.add(event)

        new_this_sweep[agent.id] = new_this_sweep.get(agent.id, 0) + 1
        repeat_count = prior_counts.get(agent.id, 0) + new_this_sweep[agent.id]
        alert_triggered = repeat_count >= REPEAT_REPAIR_ALERT_THRESHOLD
        if alert_triggered:
            report.alerts += 1
        report.repaired += 1
        outcome = RepairOutcome(
            agent_id=str(agent.id),
            agent_name=agent.name,
            action="repaired",
            prev_deadline=None,
            new_deadline=new_deadline.isoformat(),
            repeat_count_1h=repeat_count,
            alert_triggered=alert_triggered,
        )
        report.outcomes.append(outcome)
        pending_logs.append((outcome, alert_triggered))

    if report.repaired:
        await session.commit()
        # Log only after durable commit so alert consumers never see
        # repairs that rolled back.
        for outcome, alert_triggered in pending_logs:
            if alert_triggered:
                logger.warning(
                    "heartbeat_watchdog.repeat_repair_alert "
                    "agent_id=%s agent_name=%s repair_count_1h=%d window_seconds=%d "
                    "threshold=%d",
                    outcome.agent_id,
                    outcome.agent_name,
                    outcome.repeat_count_1h,
                    int(REPEAT_REPAIR_ALERT_WINDOW.total_seconds()),
                    REPEAT_REPAIR_ALERT_THRESHOLD,
                )
            else:
                logger.info(
                    "heartbeat_watchdog.repaired "
                    "agent_id=%s agent_name=%s new_deadline=%s repair_count_1h=%d",
                    outcome.agent_id,
                    outcome.agent_name,
                    outcome.new_deadline,
                    outcome.repeat_count_1h,
                )

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
                await asyncio.wait_for(stop_event.wait(), timeout=WATCHDOG_INTERVAL_SECONDS)
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
