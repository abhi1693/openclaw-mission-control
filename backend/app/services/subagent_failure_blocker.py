"""Auto-file a ``runtime``-category ``Blocker`` from a 4.20+
subagent-failure payload (Part D.1).

Dedupe is enforced in two layers:

1. ``_open_subagent_runtime_blocker_exists`` EXISTS pre-check — the
   common-case fast path that avoids the INSERT when a row is already
   open.
2. Partial unique index ``uq_blockers_runtime_owner_open`` — closes
   the race window between EXISTS and INSERT. If two workers race
   past step 1, the second INSERT fails with ``IntegrityError`` and
   the filer rolls back + returns None so the caller sees the same
   "already filed" answer the pre-check would have produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists as sql_exists
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

logger = get_logger(__name__)

_CATEGORY_RUNTIME: BlockerCategory = "runtime"

# ``Blocker.owner_role`` is ``VARCHAR(64)`` in Postgres; cap parser
# output below that to fail closed on payload-level malformation rather
# than at commit time (Postgres raises, SQLite silently truncates).
_MAX_ROLE_LENGTH = 64
# One week in ms — any subagent that claims to have run longer is
# payload corruption. Also keeps ``str(runtime_ms)`` well below CPython's
# ``sys.int_info.str_digits_check_threshold`` (4300 by default), which
# otherwise raises ``ValueError`` on monster ints in the citation builder.
_MAX_RUNTIME_MS = 7 * 24 * 60 * 60 * 1000
# Match the D.2 stale-agent blocker's citation cap so operator dashboards
# see one bounded shape across feeders.
_MAX_CITATION_LENGTH = 512


@dataclass(frozen=True, slots=True)
class SubagentFailurePayload:
    """Validated subagent-failure payload from gateway 4.20+."""

    requested_role: str
    runtime_ms: int
    error_class: str
    parent_turn_id: str | None = None


def parse_subagent_failure_payload(
    raw: object,
) -> SubagentFailurePayload | None:
    """Validate a gateway payload into :class:`SubagentFailurePayload`.

    Returns None (and WARN-logs) on missing/mistyped fields so events
    from 4.19 or earlier (missing ``requested_role``/``runtime_ms``)
    degrade to a no-op rather than filing a half-populated row the
    operator can't route. The per-field WARN prefixes are deliberately
    granular — operator debugging of gateway-version skew keys off
    them.
    """

    if not isinstance(raw, dict):
        logger.warning(
            "subagent_failure_blocker.payload_not_dict type=%s", type(raw).__name__
        )
        return None
    requested_role = raw.get("requested_role")
    runtime_ms = raw.get("runtime_ms")
    error_class = raw.get("error_class")
    role_clean = requested_role.strip() if isinstance(requested_role, str) else ""
    if (
        not isinstance(requested_role, str)
        or not role_clean
        or len(role_clean) > _MAX_ROLE_LENGTH
    ):
        logger.warning(
            "subagent_failure_blocker.missing_requested_role raw_keys=%s",
            _safe_key_list(raw),
        )
        return None
    # ``bool`` is an ``int`` subclass in Python, and a gateway payload
    # that encodes ``True``/``False`` for runtime_ms is clearly wrong —
    # reject explicitly rather than accepting ``True`` as ``1`` ms.
    if (
        isinstance(runtime_ms, bool)
        or not isinstance(runtime_ms, int)
        or runtime_ms < 0
        or runtime_ms > _MAX_RUNTIME_MS
    ):
        logger.warning(
            "subagent_failure_blocker.missing_or_invalid_runtime_ms value=%r",
            runtime_ms,
        )
        return None
    error_clean = error_class.strip() if isinstance(error_class, str) else ""
    if not isinstance(error_class, str) or not error_clean:
        logger.warning(
            "subagent_failure_blocker.missing_error_class raw_keys=%s",
            _safe_key_list(raw),
        )
        return None
    parent_turn_id_raw = raw.get("parent_turn_id")
    parent_turn_id = (
        parent_turn_id_raw
        if isinstance(parent_turn_id_raw, str) and parent_turn_id_raw.strip()
        else None
    )
    return SubagentFailurePayload(
        requested_role=role_clean,
        runtime_ms=runtime_ms,
        error_class=error_clean,
        parent_turn_id=parent_turn_id,
    )


def _safe_key_list(raw: dict[object, object]) -> list[str]:
    """``sorted(raw.keys())`` raises ``TypeError`` on dicts with mixed
    key types (e.g. ``{"a": 1, 2: "b"}``). Coerce to string first so the
    WARN path never itself crashes on adversarial payloads."""

    return sorted(str(key) for key in raw.keys())


def _citation_for(payload: SubagentFailurePayload) -> str:
    citation = (
        f"subagent {payload.requested_role} failed after "
        f"{payload.runtime_ms}ms: {payload.error_class}"
    )
    if len(citation) > _MAX_CITATION_LENGTH:
        citation = citation[: _MAX_CITATION_LENGTH - 1] + "…"
    return citation


async def _open_subagent_runtime_blocker_exists(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    requested_role: str,
) -> bool:
    """Key on ``owner_role == requested_role`` so retries with wording
    drift (different runtime_ms, different error_class) collapse onto
    one row."""

    return bool(
        await session.scalar(
            select(
                sql_exists()
                .where(col(Blocker.board_id) == board_id)
                .where(col(Blocker.task_id) == task_id)
                .where(col(Blocker.category) == _CATEGORY_RUNTIME)
                .where(col(Blocker.owner_role) == requested_role)
                .where(col(Blocker.resolved_at).is_(None))
            )
        )
    )


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

    **Commits the session.** The caller must not invoke this inside an
    outer transaction with other uncommitted state — the embedded
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
        category=_CATEGORY_RUNTIME,
        owner_role=payload.requested_role,
        required_artifact=None,
        citation=_citation_for(payload),
        created_by_agent_id=parent_agent_id,
    )
    session.add(blocker)
    try:
        await session.commit()
    except IntegrityError:
        # Lost the race against another worker — the unique index
        # ``uq_blockers_runtime_owner_open`` caught it. Roll back the
        # failed insert and return None: the other worker's row is
        # already the open state the caller wanted.
        await session.rollback()
        logger.info(
            "subagent_failure_blocker.dedupe_lost_race task_id=%s role=%s",
            task_id,
            payload.requested_role,
        )
        return None
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
