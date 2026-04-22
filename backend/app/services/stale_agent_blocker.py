"""Part D.2: auto-file operator Blocker on stale-agent-session rejection.

OpenClaw 2026.4.20 narrowed gateway session lifecycle — sessions
scoped to an agent whose entry has been removed from the gateway
config now reject with ``PAIRING_REQUIRED`` or a stale-session error.
Pre-Phase-VI that surfaced as an ambient HTTP error. §I1 wants
routing state to be structured: convert the ambient error into a
routable ``Blocker`` row so the operator sees it in the dashboard,
can act on the remediation hint, and can resolve it when the agent
is re-provisioned.

See docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md
Part D.2 for the plan.
"""

from __future__ import annotations

import re
from enum import StrEnum
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.models.blockers import Blocker
from app.models.boards import Board
from app.schemas.blockers import BlockerCategory
from app.schemas.boards import (
    STRUCTURED_BLOCKERS_V1_FLAG,
    board_rollout_flag_enabled,
)
from app.services.openclaw.gateway_rpc import OpenClawGatewayError

logger = get_logger(__name__)

_CATEGORY_OPERATOR: BlockerCategory = "operator"


class StaleAgentGatewayReason(StrEnum):
    """Which gateway-error flavour we're mapping to a Blocker."""

    PAIRING_REQUIRED = "pairing_required"
    STALE_SESSION = "stale_session"


# Regex so minor gateway-wording drift (space/dash/underscore
# separators, CamelCase → lowercase via the ``.lower()`` pre-match)
# doesn't silently defeat the hook. Tested against
# ``PAIRING_REQUIRED``, ``pairing required``, ``pairing-required``,
# ``PairingRequired``.
_PAIRING_PATTERN = re.compile(r"pairing[ _\-]*required|pairingrequired")
_STALE_SESSION_MARKERS = (
    # Keep these narrow so the classifier doesn't false-positive on
    # unrelated failures (a typo in a dispatch payload, a deleted-
    # mid-request row, etc.). The markers here are all gateway-
    # authored phrasings that specifically identify "this agent's
    # session/pairing is no longer valid because config changed."
    "stale agent session",
    "agent session is stale",
    "session no longer valid",
    "unknown agent",
    "agent removed from config",
)


def classify_gateway_error(
    exc: OpenClawGatewayError,
) -> StaleAgentGatewayReason | None:
    """Return the §I1-routable error classification, or None if the
    error is something else (e.g. transient network failure)."""

    msg = str(exc).lower()
    if _PAIRING_PATTERN.search(msg):
        return StaleAgentGatewayReason.PAIRING_REQUIRED
    if any(marker in msg for marker in _STALE_SESSION_MARKERS):
        return StaleAgentGatewayReason.STALE_SESSION
    return None


def _citation_for(reason: StaleAgentGatewayReason, raw_message: str) -> str:
    # 4.20+ gateways emit reason-specific remediation hints; 4.19 and
    # below return a generic message. Preserve whatever the gateway
    # said so operators see the most-specific text available without
    # needing to cross-reference logs.
    truncated = raw_message.strip()
    if len(truncated) > 512:
        truncated = truncated[:512] + "…"
    return truncated or f"Gateway returned {reason.value} without a remediation hint."


async def _open_stale_agent_blocker_exists(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    agent_name: str,
) -> bool:
    """Dedupe: if there's already an open stale-agent Blocker for this
    (task, agent) the retry-loop should not stamp another one. The
    key deliberately uses the ``required_artifact`` string — whoever
    mutates :func:`_required_artifact_for` must update the dedupe
    test alongside the template."""

    required_artifact = _required_artifact_for(agent_name)
    existing = await session.scalar(
        select(Blocker.id)
        .where(col(Blocker.board_id) == board_id)
        .where(col(Blocker.task_id) == task_id)
        .where(col(Blocker.category) == _CATEGORY_OPERATOR)
        .where(col(Blocker.required_artifact) == required_artifact)
        .where(col(Blocker.resolved_at).is_(None))
        .limit(1)
    )
    return existing is not None


def _required_artifact_for(agent_name: str) -> str:
    return f"agent `{agent_name}` missing from gateway config"


async def file_stale_agent_blocker_if_configured(
    session: AsyncSession,
    *,
    board: Board,
    task_id: UUID,
    agent_name: str,
    exc: OpenClawGatewayError,
) -> UUID | None:
    """File an operator-category ``Blocker`` if the board has opted
    into structured blockers AND no open blocker already exists for
    this (task, agent) pair.

    Returns the Blocker id on a fresh file, None if gated out, already
    open, or the error isn't a stale-agent flavour.

    **Commits the session.** The caller must not invoke this inside
    an outer transaction with other uncommitted state — the embedded
    commit would prematurely persist it. Today's callers in
    ``_notify_agent_on_task_assign`` / ``_rework`` commit their own
    state first, so nothing is at risk.
    """

    reason = classify_gateway_error(exc)
    if reason is None:
        return None

    if not board_rollout_flag_enabled(
        board.rollout_flags, STRUCTURED_BLOCKERS_V1_FLAG
    ):
        return None

    if await _open_stale_agent_blocker_exists(
        session,
        board_id=board.id,
        task_id=task_id,
        agent_name=agent_name,
    ):
        return None

    blocker = Blocker(
        board_id=board.id,
        task_id=task_id,
        category=_CATEGORY_OPERATOR,
        owner_role="operator",
        required_artifact=_required_artifact_for(agent_name),
        reopen_condition=(
            "re-add agent to openclaw.json and confirm provision"
        ),
        citation=_citation_for(reason, str(exc)),
    )
    # Blocker.id is a Python-side ``default_factory=uuid4``, so it's
    # populated on construction. No server-computed fields need a
    # refresh-round-trip before the caller reads ``blocker.id``.
    session.add(blocker)
    try:
        await session.commit()
    except IntegrityError:
        # Lost the race against another worker — the unique index
        # ``uq_blockers_operator_artifact_open`` caught it. Roll back
        # and return None: the other worker's row is already the open
        # state the caller wanted.
        await session.rollback()
        logger.info(
            "stale_agent_blocker.dedupe_lost_race task_id=%s agent=%s",
            task_id,
            agent_name,
        )
        return None
    logger.info(
        "stale_agent_blocker.filed task_id=%s agent=%s reason=%s blocker_id=%s",
        task_id,
        agent_name,
        reason.value,
        blocker.id,
    )
    return blocker.id
