"""Part D.1: auto-file runtime Blocker from a subagent-failure payload.

4.20 extended subagent failure payloads with ``requested_role`` and
``runtime_ms`` so parent agents can correlate failed/timed-out child
work (changelog: *"Agents/subagents: include requested role and
runtime timing on subagent failure payloads so parent agents can
correlate failed or timed-out child work"*). §I1's "no blocked work
without a blocker object" invariant depends on structured rows;
runtime failures today fall through as free-text "blocked on timeout"
comments — exactly the footgun the invariant exists to prevent.

This service maps a validated payload into a ``Blocker`` row so the
Supervisor sees the routable runtime-category object instead of
reading prose.

Ingest wiring follow-up: as of this commit MC has no client
subscription to the gateway's activity stream, so nothing calls this
filer yet. When a push/subscribe path lands (agent POST webhook or
outbound SSE subscription), wire through ``parse_subagent_failure_payload``
+ ``file_subagent_failure_blocker_if_configured``.

See docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md
Part D.1 for the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.models.blockers import Blocker
from app.models.boards import Board
from app.schemas.boards import (
    STRUCTURED_BLOCKERS_V1_FLAG,
    board_rollout_flag_enabled,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SubagentFailurePayload:
    """Validated subagent-failure payload from gateway 4.20+.

    ``parent_turn_id`` is optional — the plan lists it but older 4.20
    builds may omit it; treat it as metadata, not a load-bearing
    routing key.
    """

    requested_role: str
    runtime_ms: int
    error_class: str
    parent_turn_id: str | None = None


def parse_subagent_failure_payload(
    raw: object,
) -> SubagentFailurePayload | None:
    """Validate a gateway payload into :class:`SubagentFailurePayload`.

    Return None (and WARN-log) when required fields are missing or
    mistyped. Older gateways (4.19 and earlier) emit subagent-failure
    events without ``requested_role``/``runtime_ms`` — the correct
    behaviour per the plan is to degrade to a no-op, not to file a
    half-populated blocker the operator can't route.
    """

    if not isinstance(raw, dict):
        logger.warning(
            "subagent_failure_blocker.payload_not_dict type=%s", type(raw).__name__
        )
        return None
    requested_role = raw.get("requested_role")
    runtime_ms = raw.get("runtime_ms")
    error_class = raw.get("error_class")
    if not isinstance(requested_role, str) or not requested_role.strip():
        logger.warning(
            "subagent_failure_blocker.missing_requested_role raw_keys=%s",
            sorted(raw.keys()),
        )
        return None
    if not isinstance(runtime_ms, int) or runtime_ms < 0:
        logger.warning(
            "subagent_failure_blocker.missing_or_invalid_runtime_ms value=%r",
            runtime_ms,
        )
        return None
    if not isinstance(error_class, str) or not error_class.strip():
        logger.warning(
            "subagent_failure_blocker.missing_error_class raw_keys=%s",
            sorted(raw.keys()),
        )
        return None
    parent_turn_id_raw = raw.get("parent_turn_id")
    parent_turn_id = (
        parent_turn_id_raw
        if isinstance(parent_turn_id_raw, str) and parent_turn_id_raw.strip()
        else None
    )
    return SubagentFailurePayload(
        requested_role=requested_role.strip(),
        runtime_ms=runtime_ms,
        error_class=error_class.strip(),
        parent_turn_id=parent_turn_id,
    )


def _citation_for(payload: SubagentFailurePayload) -> str:
    return (
        f"subagent {payload.requested_role} failed after "
        f"{payload.runtime_ms}ms: {payload.error_class}"
    )


async def _open_subagent_runtime_blocker_exists(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    requested_role: str,
) -> bool:
    """Dedupe key: open ``runtime`` blocker for the same (task,
    requested_role). A retry storm for the same child-agent class must
    not stamp a new row on every attempt — the existing open row is
    still the operator's routable surface.

    We key on ``owner_role == requested_role`` rather than the free-
    form citation string so the dedupe survives minor wording drift
    (different runtime_ms, different error_class) on retries.
    """

    existing = await session.scalar(
        select(Blocker.id)
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id) == task_id)
        .where(col(Blocker.category) == "runtime")
        .where(col(Blocker.owner_role) == requested_role)
        .where(col(Blocker.resolved_at).is_(None))
        .limit(1)
    )
    return existing is not None


async def file_subagent_failure_blocker_if_configured(
    session: AsyncSession,
    *,
    board: Board,
    task_id: UUID,
    parent_agent_id: UUID | None,
    payload: SubagentFailurePayload,
) -> UUID | None:
    """File a ``runtime``-category ``Blocker`` when the board has opted
    into structured blockers AND no open runtime blocker already
    exists for this (task, requested_role) pair.

    Returns the Blocker id on a fresh file, None if gated out or
    already open.

    **Commits the session.** The caller must not invoke this inside
    an outer transaction with other uncommitted state — the embedded
    commit would prematurely persist it. Mirrors
    :func:`file_stale_agent_blocker_if_configured`'s contract.
    """

    if not board_rollout_flag_enabled(
        board.rollout_flags, STRUCTURED_BLOCKERS_V1_FLAG
    ):
        return None

    if await _open_subagent_runtime_blocker_exists(
        session,
        board_id=board.id,
        task_id=task_id,
        requested_role=payload.requested_role,
    ):
        return None

    blocker = Blocker(
        board_id=board.id,
        task_id=task_id,
        category="runtime",
        owner_role=payload.requested_role,
        required_artifact=None,
        citation=_citation_for(payload),
        created_by_agent_id=parent_agent_id,
    )
    session.add(blocker)
    await session.commit()
    logger.info(
        "subagent_failure_blocker.filed task_id=%s role=%s runtime_ms=%d "
        "error=%s blocker_id=%s",
        task_id,
        payload.requested_role,
        payload.runtime_ms,
        payload.error_class,
        blocker.id,
    )
    return blocker.id
