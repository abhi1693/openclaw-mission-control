"""Task API routes for listing, streaming, and mutating board tasks."""

from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import asc, desc, or_
from sqlmodel import col, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_user_write,
    get_task_or_404,
    require_user_auth,
    require_user_or_agent,
)
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approval_task_links import ApprovalTaskLink
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.tag_assignments import TagAssignment
from app.models.task_custom_fields import (
    BoardTaskCustomField,
    TaskCustomFieldDefinition,
    TaskCustomFieldValue,
)
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.task_review_events import TaskReviewEvent
from app.models.tasks import Task
from app.schemas.activity_events import ActivityEventRead
from app.schemas.approvals import DONE_APPROVAL_ACTION_TYPES
from app.schemas.common import OkResponse
from app.schemas.errors import BlockedTaskError
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.task_custom_fields import (
    TaskCustomFieldType,
    TaskCustomFieldValues,
    validate_custom_field_value,
)
from app.schemas.task_pipeline_events import (
    TaskPipelineEventCreate,
    TaskPipelineEventRead,
    TaskPipelineStateRead,
)
from app.schemas.task_review_events import (
    TaskReviewEventCreate,
    TaskReviewEventRead,
    TaskReviewReadinessRead,
)
from app.schemas.tasks import (
    STATUS_GATES,
    TaskCommentCreate,
    TaskCommentRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    actionability_missing_fields,
)
from app.services.activity_log import record_activity
from app.services.approval_task_links import (
    load_task_ids_by_approval,
    pending_approval_conflicts_by_task,
)
from app.services.mentions import extract_mentions, matches_agent_mention
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.stale_agent_blocker import (
    file_stale_agent_blocker_if_configured,
)
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.core.logging import get_logger
from app.services.comment_policy import apply_comment_signal_filter
from app.services.organizations import require_board_access
from app.services.background_emitter import BackgroundEmitter
from app.services.deploy_truth import (
    DeployTruthFetchError,
    fetch_build_metadata,
    packet_sha_matches_live,
)
from app.services.echo_guard import classify_for_echo
from app.services.lane_quieting import should_suppress_comment_for_blocked_lane
from app.services.shadow_metrics import (
    build_shadow_events_for_comment,
    emit_actionability_violation_metric,
    emit_deploy_validation_degraded_metric,
    emit_lane_quieting_suppressed_metric,
)

from app.services.tags import (
    TagState,
    load_tag_state,
    replace_tags,
    validate_tag_ids,
)
from app.services.blockers import (
    auto_resolve_pipeline_blockers_if_ready,
    open_blocker_summary_for_task,
    task_has_open_blocker,
    task_ids_with_open_blocker,
)
from app.services.operator_decisions import (
    task_has_pending_operator_decision,
    task_ids_with_pending_operator_decision,
)
from app.services.parent_cascade import (
    TERMINAL_STATUSES,
    maybe_cascade_umbrella_close,
    non_terminal_children_of,
    orphan_children_by_parent_id,
)
from app.services.task_dependencies import (
    blocked_by_dependency_ids,
    dependency_ids_by_task_id,
    dependency_status_by_id,
    dependent_task_ids,
    replace_task_dependencies,
    validate_dependency_update,
)
from app.services.lead_notify import notify_lead_after_blocker_resolved
from app.services.task_pipeline import (
    FRONTEND_REVIEW_PIPELINE_STATES,
    frontend_pipeline_required,
    latest_model_fallback_step,
    list_task_pipeline_events,
    pipeline_missing_required_fields,
    pipeline_missing_states,
    pipeline_present_states,
    require_frontend_pipeline_ready_for_review,
)
from app.services.task_review_events import (
    get_task_review_readiness,
    task_review_event_read,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import SelectOfScalar

    from app.core.auth import AuthContext
    from app.models.users import User


logger = get_logger(__name__)

router = APIRouter(prefix="/boards/{board_id}/tasks", tags=["tasks"])

ALLOWED_STATUSES = {"inbox", "in_progress", "review", "rework", "done", "cancelled"}

# Non-lead agent-path state machine. Only these (from, to) pairs are
# legitimate for an agent-token PATCH that changes status. The table
# enforces that workers go through `in_progress` before `review` — a
# task whose `in_progress_at` is null because it jumped inbox→review
# leaves the delivery-contract gate unable to compute cycle time or
# deploy-truth ordering downstream. Codex review 2026-04-24 confirmed
# the prior code accepted any target status without from-state checks,
# which created the cycle-1 inbox→review hole and the rework→review
# shortcut. ``(x, x)`` entries are no-op self-moves the caller may
# send when echoing current state — they're accepted but the
# side-effect branches below must not run.
#
# Why no equivalent ``_LEAD_PATH_VALID_TRANSITIONS`` / admin table:
# the lead path's inbox→in_progress shortcut is conditional on
# ``assigning_agent``, a side condition a pure allow-list table
# can't express. The lead path's inline validation in
# ``_lead_apply_status`` is already explicit, status-scoped, and
# covered by its own tests. The admin path is intentionally
# permissive (cancel/uncancel, migration scripts). A uniform table
# across all three roles would either lose information (drop the
# side conditions) or recreate the per-role logic anyway. Codex
# finding C (2026-04-24) considered and deferred on those grounds.
_AGENT_PATH_VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    # forward progress
    ("inbox", "in_progress"),
    ("rework", "in_progress"),
    ("in_progress", "review"),
    # completion — subject to downstream gates (require_review_before_done,
    # approval linkage, deploy-truth) that run AFTER this transition check
    ("in_progress", "done"),
    ("review", "done"),
    # agent-initiated backward / abandon
    ("in_progress", "inbox"),
    ("rework", "inbox"),
    ("in_progress", "rework"),
    # no-op self-moves
    ("inbox", "inbox"),
    ("in_progress", "in_progress"),
    ("review", "review"),
    ("rework", "rework"),
    ("done", "done"),
})
TASK_EVENT_TYPES = {
    "task.created",
    "task.updated",
    "task.status_changed",
    "task.comment",
}
SSE_SEEN_MAX = 2000
TASK_SNIPPET_MAX_LEN = 500
TASK_SNIPPET_TRUNCATED_LEN = 497
TASK_EVENT_ROW_LEN = 2
QA_VERDICT_PREFIX_RE = re.compile(r"^VERDICT:\s*(PASS|FAIL|INCONCLUSIVE|INFRA BLOCKED)\b")
REVIEW_PASS_VERDICT_RE = re.compile(
    r"^\s*(?:VERDICT|Verdict|Corrected verdict):\s*PASS\b",
    re.IGNORECASE | re.MULTILINE,
)
SOURCE_OR_BUNDLE_EVIDENCE_RE = re.compile(
    r"\b(?:bundle[- ]grep|source[- ]grep|source[- ]level|grep found|"
    r"found in (?:the )?(?:deployed )?bundle|bundle contains|source contains|"
    r"local code presence)\b",
    re.IGNORECASE,
)
BROWSER_RENDERED_EVIDENCE_RE = re.compile(
    r"\b(?:browser snapshot|dom snapshot|rendered dom|dom text dump|"
    r"getcomputedstyle|computed style|computed background-image|document\.querySelector|"
    r"playwright locator|locator\(|screenshot|pixel|visual diff)\b",
    re.IGNORECASE,
)
REWORK_ROUTING_CLAIM_RE = re.compile(
    r"\b(?:routing|route|return(?:ing)?|send(?:ing)?|move|moved)\s+(?:[^.!?\n]{0,40}\s+)?(?:to|into|for|back to)\s+rework\b"
    r"|"
    r"\breturn(?:ing)?\s+(?:to\s+)?PF\s+rework\b"
    r"|"
    r"\brework\s+(?:route|routing|return|handoff)\b",
    re.IGNORECASE,
)
REWORK_ROUTING_NEGATION_RE = re.compile(
    r"\b(?:do not|don't|dont|not|never|no)\s+"
    r"(?:routing|route|return(?:ing)?|send(?:ing)?|move|moved)\s+"
    r"(?:[^.!?\n]{0,40}\s+)?(?:to|into|for|back to)\s+rework\b",
    re.IGNORECASE,
)
FINAL_EVIDENCE_PACKET_RE = re.compile(r"^\s*FINAL_EVIDENCE_PACKET\b")
ACTIVE_BLOCKER_CLEARED_RE = re.compile(r"^\s*Active blocker cleared:\s*\S", re.IGNORECASE)
GIT_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
TASK_STATUS_CHANGED_RE = re.compile(r"^Task moved to ([a-z_]+):")
REVIEW_EVIDENCE_REQUIRED_PACKET_TYPES = frozenset(
    {"frontend_ui", "backend_api", "infra_ops", "mixed"},
)
BOARD_READ_DEP = Depends(get_board_for_actor_read)
ACTOR_DEP = Depends(require_user_or_agent)
SINCE_QUERY = Query(default=None)
STATUS_QUERY = Query(default=None, alias="status")
BOARD_WRITE_DEP = Depends(get_board_for_user_write)
SESSION_DEP = Depends(get_session)
USER_AUTH_DEP = Depends(require_user_auth)
TASK_DEP = Depends(get_task_or_404)


@dataclass(frozen=True, slots=True)
class _BoardCustomFieldDefinition:
    id: UUID
    field_key: str
    field_type: TaskCustomFieldType
    validation_regex: str | None
    required: bool
    default_value: object | None


def _comment_validation_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Comment is required.",
    )


def _qa_verdict_prefix_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": (
                "QA validation comments must start with "
                "`VERDICT: PASS`, `VERDICT: FAIL`, `VERDICT: INCONCLUSIVE`, "
                "or `VERDICT: INFRA BLOCKED`."
            ),
            "code": "qa_verdict_prefix_required",
        },
    )


def _rework_routing_comment_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                "A lead comment cannot claim rework routing while the task remains in review. "
                "PATCH the task to `status=rework` with the rework note so durable routing, "
                "assignment, and rework gates are applied."
            ),
            "code": "rework_routing_comment_requires_status_transition",
        },
    )


def _rendered_live_evidence_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                "PASS cannot cite source grep or bundle grep as rendered/live evidence. "
                "Use browser-rendered evidence such as DOM snapshot/text, computed styles "
                "or computed background-image for CSS data-URL SVGs, Playwright locator "
                "output, screenshot/pixel evidence, or an equivalent live browser observation."
            ),
            "code": "rendered_live_evidence_required",
        },
    )


def _review_evidence_packet_error(*, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": message,
            "code": code,
        },
    )


def _actor_is_qa_validation_agent(actor: ActorContext) -> bool:
    if actor.actor_type != "agent" or actor.agent is None:
        return False
    profile = actor.agent.identity_profile or {}
    return profile.get("validation_flow") == "qa_validation"


def _actor_is_review_only_agent(actor: ActorContext) -> bool:
    if actor.actor_type != "agent" or actor.agent is None:
        return False
    profile = actor.agent.identity_profile or {}
    return profile.get("dev_acp_flow") == "review_only"


def _actor_is_implementation_agent(actor: ActorContext) -> bool:
    if actor.actor_type != "agent" or actor.agent is None:
        return False
    if actor.agent.is_board_lead:
        return False
    return not _actor_is_qa_validation_agent(actor) and not _actor_is_review_only_agent(actor)


def _validate_task_comment_format_for_actor(message: str, actor: ActorContext) -> None:
    if not _actor_is_qa_validation_agent(actor):
        return
    stripped = message.lstrip()
    if not QA_VERDICT_PREFIX_RE.match(stripped):
        raise _qa_verdict_prefix_error()


def _require_rendered_live_pass_has_browser_evidence(message: str, actor: ActorContext) -> None:
    if not (_actor_is_qa_validation_agent(actor) or _actor_is_review_only_agent(actor)):
        return
    if not REVIEW_PASS_VERDICT_RE.search(message):
        return
    if not SOURCE_OR_BUNDLE_EVIDENCE_RE.search(message):
        return
    if BROWSER_RENDERED_EVIDENCE_RE.search(message):
        return
    raise _rendered_live_evidence_error()


def _require_comment_not_claim_unapplied_rework_routing(
    *,
    task: Task,
    message: str,
    actor: ActorContext,
) -> None:
    if actor.actor_type != "agent" or actor.agent is None or not actor.agent.is_board_lead:
        return
    if task.status != "review":
        return
    if REWORK_ROUTING_CLAIM_RE.search(message) and not REWORK_ROUTING_NEGATION_RE.search(message):
        raise _rework_routing_comment_error()


def _task_update_forbidden_error(*, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "message": message,
            "code": code,
        },
    )


def _blocked_task_error(blocked_by_task_ids: Sequence[UUID]) -> HTTPException:
    # NOTE: Keep this payload machine-readable; UI and automation rely on it.
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "Task is blocked by incomplete dependencies.",
            "code": "task_blocked_cannot_transition",
            "blocked_by_task_ids": [str(value) for value in blocked_by_task_ids],
        },
    )


def _open_blocker_block_error(
    open_blockers: Sequence[tuple[UUID, str | None]],
) -> HTTPException:
    """Reject forward status transitions when open structured Blockers exist.

    Forward = ``in_progress`` / ``review`` / ``done``. ``inbox`` /
    ``rework`` / ``cancelled`` remain reachable so the assignee can
    park, retry, or drop blocked work without first resolving every
    Blocker. Resolve each Blocker via
    ``PATCH /boards/{board_id}/tasks/{task_id}/blockers/{blocker_id}``
    with ``{"status_transition": "resolve"}`` before retrying the
    forward transition.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                "Task has open structured Blockers; resolve them before "
                "transitioning forward."
            ),
            "code": "task_blocked_open_blocker_cannot_transition",
            "open_blocker_ids": [str(blocker_id) for blocker_id, _ in open_blockers],
            "open_blocker_reason_codes": [
                reason_code for _, reason_code in open_blockers if reason_code is not None
            ],
        },
    )


def _invalid_parent_task_error(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": f"Invalid parent_task_id: {reason}.",
            "code": "task_parent_task_id_invalid",
        },
    )


async def _validate_parent_task_id(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    parent_task_id: UUID | None,
) -> None:
    """Reject self-parent and cross-board / unknown parent references.

    Cross-board parents would break the cascade (the orphan-detection
    sweep is board-scoped); self-parents would loop the cascade.
    """
    if parent_task_id is None:
        return
    if parent_task_id == task_id:
        raise _invalid_parent_task_error("a task cannot be its own parent")
    parent = await Task.objects.by_id(parent_task_id).first(session)
    if parent is None:
        raise _invalid_parent_task_error(f"parent task {parent_task_id} not found")
    if parent.board_id != board_id:
        raise _invalid_parent_task_error(
            "parent task belongs to a different board"
        )
    if parent.status in TERMINAL_STATUSES:
        raise _invalid_parent_task_error(
            f"parent task {parent_task_id} is already {parent.status}; "
            "child would be born orphaned"
        )


def _operator_decision_block_error(summary: str | None = None) -> HTTPException:
    message = "Task is blocked pending operator decision."
    if summary:
        message = f"{message} {summary}"
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": message,
            "code": "task_blocked_operator_decision_required",
            "blocked_by_task_ids": [],
            "operator_decision_required": True,
            "operator_decision_summary": summary,
        },
    )


def _legacy_operator_decision_active_task_error(
    summary: str | None = None,
) -> HTTPException:
    error = _operator_decision_block_error(summary)
    if isinstance(error.detail, dict):
        error.detail["message"] = (
            f"{error.detail['message']} File a structured Blocker for "
            "runtime/deploy/source/contract friction, or a first-class "
            "OperatorDecision for human/operator choices, instead of setting "
            "legacy operator_decision_required on active assigned work."
        )
    return error


ERROR_CODE_DELIVERY_CONTRACT_INCOMPLETE = "task_delivery_contract_incomplete"
ERROR_CODE_COMMENT_SUPPRESSED_BLOCKED_LANE = "comment_suppressed_blocked_lane"
ERROR_CODE_COMMENT_ECHOED_NO_OP = "comment_echoed_as_no_op"


def _echo_guard_suppressed_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                "Comment rejected as a no-op echo of your prior same-task "
                "comment. Post a message that references a task-state "
                "change, a new blocker, a concrete artifact (URL/SHA), or "
                "a specific action — or stay silent."
            ),
            "code": ERROR_CODE_COMMENT_ECHOED_NO_OP,
        },
    )


async def _require_echo_guard_allows_comment(
    session: "AsyncSession",
    *,
    task: Task,
    actor: "ActorContext",
    message: str,
) -> None:
    """Phase VII: reject comment writes that ECHO_SHAPE-classify AND
    have a recent same-author prior on the same task AND saw no
    state-delta since that prior. Agent actors only — user operators
    are exempt."""

    if actor.actor_type != "agent":
        return
    result = await classify_for_echo(
        session,
        task=task,
        agent_id=_comment_actor_id(actor),
        message=message,
    )
    if not result.should_suppress:
        return
    raise _echo_guard_suppressed_error()


def _lane_quieting_suppressed_error() -> HTTPException:
    # 403 — not 409 — because the comment is *forbidden* for this
    # actor, not a state conflict the caller can resolve by retrying.
    # Clients auto-retrying on 409 would loop.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "message": (
                "Task has an acknowledged blocker; only the owner or a "
                "human operator can comment until it's resolved."
            ),
            "code": ERROR_CODE_COMMENT_SUPPRESSED_BLOCKED_LANE,
        },
    )


async def _require_lane_quieting_allows_comment(
    session: "AsyncSession",
    *,
    task: Task,
    actor: "ActorContext",
) -> None:
    """Phase VI §I6: reject non-owner agent comments on a task with
    any open acknowledged blocker, per the board's rollout flag."""

    if actor.actor_type != "agent":
        return
    suppressed = await should_suppress_comment_for_blocked_lane(
        session,
        task=task,
        author_agent_id=_comment_actor_id(actor),
    )
    if not suppressed:
        return
    _lane_quieting_emitter.schedule(
        emit_lane_quieting_suppressed_metric(
            task_id=task.id,
            board_id=task.board_id,
            agent_id=_comment_actor_id(actor),
        ),
        log_key=str(task.id),
    )
    raise _lane_quieting_suppressed_error()
ERROR_CODE_DEPLOY_TRUTH_SHA_MISMATCH = "task_deploy_truth_sha_mismatch"
ERROR_CODE_DEPLOY_TRUTH_MISSING_PACKET_SHA = "task_deploy_truth_missing_packet_sha"
ERROR_CODE_DEPLOY_TRUTH_UNREACHABLE = "task_deploy_truth_target_unreachable"


def _deploy_truth_error(
    *,
    code: str,
    message: str,
    status_value: str,
    extra: dict[str, object] | None = None,
) -> HTTPException:
    detail: dict[str, object] = {
        "code": code,
        "message": message,
        "status": status_value,
    }
    if extra:
        detail.update(extra)
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    )


def _delivery_contract_incomplete_error(
    *,
    status_value: str,
    missing_fields: Sequence[str],
) -> HTTPException:
    # Phase IV §I2: when the assigned-owner check trips alongside (or
    # instead of) the packet-type triplet, the word "delivery contract"
    # is no longer accurate — surface "actionability" in the message
    # while keeping the wire ``code`` stable for existing clients.
    # The decision reads off the structural signal "is the owner among
    # the missing fields?" rather than a string-sniff on the message,
    # so adding a sibling field later (e.g. ``expected_completion_at``)
    # won't change the branch by accident.
    fields = list(missing_fields)
    owner_missing = "assigned_agent_id" in set(fields)
    message = (
        f"Task is not actionable for {status_value}; missing owner "
        "and/or delivery contract metadata."
        if owner_missing
        else f"Task is missing delivery contract metadata required for "
        f"{status_value}."
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": message,
            "code": ERROR_CODE_DELIVERY_CONTRACT_INCOMPLETE,
            "status": status_value,
            "missing_fields": fields,
        },
    )


def _approval_required_for_done_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": ("Task can only be marked done when a linked approval has been approved."),
            "blocked_by_task_ids": [],
        },
    )


def _review_required_for_done_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": ("Task can only be marked done from review when the board rule is enabled."),
            "blocked_by_task_ids": [],
        },
    )


def _pending_approval_blocks_status_change_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": ("Task status cannot be changed while a linked approval is pending."),
            "blocked_by_task_ids": [],
        },
    )


def _operator_only_cancel_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only operators can cancel or reopen cancelled tasks.",
    )


def _status_clears_blockers(status_value: str) -> bool:
    return status_value in TERMINAL_STATUSES


def _task_has_operator_decision_block(task: Task) -> bool:
    return bool(task.operator_decision_required) and not _status_clears_blockers(task.status)


def _task_is_blocked(
    task: Task,
    blocked_by_task_ids: Sequence[UUID],
    *,
    has_open_blocker: bool = False,
    has_pending_operator_decision: bool = False,
) -> bool:
    """True when the task should be treated as blocked.

    Sources, in precedence order: a terminal status clears blockers
    outright; otherwise any of:
    - an unresolved dependency (§I1 graph edge),
    - the legacy ``Task.operator_decision_required`` flag (§I3
      compatibility shim, preserved during migration),
    - an open ``Blocker`` sidecar row (§I1 structured object),
    - a pending ``OperatorDecision`` entity linked to the task (§I3
      first-class object).
    """

    if _status_clears_blockers(task.status):
        return False
    return (
        bool(blocked_by_task_ids)
        or _task_has_operator_decision_block(task)
        or has_open_blocker
        or has_pending_operator_decision
    )


async def _require_operator_decision_task_not_active(
    session: AsyncSession, task: Task
) -> None:
    """Transition guard for operator-decision-blocked tasks.

    Honours both the legacy ``Task.operator_decision_required`` flag
    AND the Phase III first-class ``OperatorDecision`` entity — any
    pending decision linked to the task has the same veto power as
    the legacy flag. Without this, the compatibility bridge would
    render ``is_blocked=true`` on reads while letting the PATCH path
    silently advance the task (advisory-only enforcement).
    """

    exempt_via_status = (
        task.assigned_agent_id is None
        and task.status in {"inbox", "done", "cancelled"}
    )
    if exempt_via_status:
        return
    if task.operator_decision_required:
        raise _operator_decision_block_error(task.operator_decision_summary)
    if task.board_id is not None and await task_has_pending_operator_decision(
        session, board_id=task.board_id, task_id=task.id
    ):
        raise _operator_decision_block_error()


def _require_delivery_contract_for_task_state(
    *,
    status_value: str,
    review_packet_type: str | None,
    validation_target: str | None,
    validation_target_kind: str | None,
    validation_target_scope: str | None,
) -> None:
    missing_fields = actionability_missing_fields(
        status=status_value,
        review_packet_type=review_packet_type,
        validation_target=validation_target,
        validation_target_kind=validation_target_kind,
        validation_target_scope=validation_target_scope,
        assigned_agent_id=None,
    )
    if missing_fields:
        raise _delivery_contract_incomplete_error(
            status_value=status_value,
            missing_fields=missing_fields,
        )


def _delivery_contract_missing_fields_for_task(task: Task) -> list[str]:
    """Pure check: return the missing actionability fields for the
    task's current state. Empty list means the state is actionable.

    Phase IV §I2 extends the Phase 0 "delivery contract" check to
    include the assigned-owner requirement. Active states
    (``in_progress`` / ``review`` / ``done``) must carry both a
    packet-type + validation-target triplet AND an owner.
    """

    return actionability_missing_fields(
        status=task.status,
        review_packet_type=task.review_packet_type,
        validation_target=task.validation_target,
        validation_target_kind=task.validation_target_kind,
        validation_target_scope=task.validation_target_scope,
        assigned_agent_id=task.assigned_agent_id,
    )


def _require_delivery_contract_with_metric(
    *,
    task: Task,
    actor_agent_id: UUID | None,
) -> None:
    """Per amendment §A.5: instrument the existing raise, don't duplicate
    the check. Reads fields off the task, calls the pure checker, and
    — if missing fields exist — emits the shadow metric in the
    background (fire-and-forget so a slow DB doesn't delay the 422)
    and raises the same HTTPException the validator would have raised.

    ``actor_agent_id`` is the agent UUID if the transition was agent-
    initiated, None for user/operator paths. User-initiated violations
    still emit (the failed transition is worth recording regardless of
    initiator); the agent_id column stays NULL.
    """

    missing_fields = _delivery_contract_missing_fields_for_task(task)
    if not missing_fields:
        return
    _schedule_actionability_violation_emit(
        task_id=task.id,
        board_id=task.board_id,
        agent_id=actor_agent_id,
        status_value=task.status,
        missing_fields=missing_fields,
    )
    raise _delivery_contract_incomplete_error(
        status_value=task.status,
        missing_fields=missing_fields,
    )


_DEPLOY_TRUTH_REQUIRED_STATUSES = STATUS_GATES["deploy_truth"]

_DEPLOY_TRUTH_PROJECTED_FIELDS = (
    "status",
    "validation_target",
    "packet_commit_sha",
    "supports_build_metadata",
)


def _projected_task(task: Task, updates: dict[str, object]) -> Task:
    """Return a detached ``Task`` copy with ``updates`` applied.

    Used by the deploy-truth gate so the SHA fetch runs against the
    PATCH's intended state without mutating the ORM row (which would
    mark it dirty + risk autoflush during the outbound HTTP call).
    Only the fields the gate reads are projected — the returned Task
    is a throwaway, never added to a session.
    """

    projected = Task(
        id=task.id,
        board_id=task.board_id,
        title=task.title,
        status=task.status,
        validation_target=task.validation_target,
        packet_commit_sha=task.packet_commit_sha,
        supports_build_metadata=task.supports_build_metadata,
    )
    for field in _DEPLOY_TRUTH_PROJECTED_FIELDS:
        if field in updates:
            setattr(projected, field, updates[field])
    return projected


def _validate_agent_transition(*, from_status: str, to_status: str) -> None:
    """Reject illegal source→target status moves on the non-lead agent path.

    Called before the branching side-effect logic so a 403 lands at the
    outer boundary with a clear message, rather than letting the code
    silently accept (say) ``inbox → review`` and stamp ``in_progress_at
    = null`` on a review-status task. See ``_AGENT_PATH_VALID_TRANSITIONS``
    for the full allow-list.
    """

    if (from_status, to_status) in _AGENT_PATH_VALID_TRANSITIONS:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Invalid status transition on agent path: `{from_status}` → "
            f"`{to_status}`. Use the proper predecessor status first "
            "(e.g. `in_progress` before `review`)."
        ),
    )


def _require_commit_sha_for_review(task: Task, updates: dict[str, object]) -> None:
    if updates.get("status", task.status) != "review":
        return
    projected_target = updates.get("validation_target", task.validation_target)
    if projected_target is not None:
        return
    if task.review_packet_type not in {"frontend_ui", "mixed"}:
        return
    projected_sha = updates.get("packet_commit_sha", task.packet_commit_sha)
    if projected_sha:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                "Cannot move to review without packet_commit_sha. "
                "Commit your changes, then include packet_commit_sha in the PATCH: "
                '{"status": "review", "packet_commit_sha": "<SHA>"}'
            ),
            "code": "review_missing_commit",
        },
    )


async def _resolve_rollout_flags(
    session: AsyncSession,
    *,
    board_id: UUID | None,
) -> dict[str, Any] | None:
    """Fetch ``Board.rollout_flags`` for gate decisions. Returns None when
    the task has no board (admin-only, out of board scope) so callers
    can fall through to the default-enforced path."""

    if board_id is None:
        return None
    flags = (
        await session.exec(
            select(col(Board.rollout_flags)).where(col(Board.id) == board_id),
        )
    ).first()
    if flags is None:
        return None
    return dict(flags) if isinstance(flags, dict) else None


async def _require_deploy_truth(
    task: Task,
    *,
    actor_agent_id: UUID | None,
    rollout_flags: dict[str, Any] | None = None,
) -> None:
    """Phase V §I8: enforce SHA comparison on review/done transitions.

    Three branches per the plan:

    - ``supports_build_metadata`` is ``True`` — fetch ``/__build`` and
      compare ``task.packet_commit_sha`` against the live SHA. Missing
      packet SHA, unreachable endpoint, or mismatched SHA all raise
      409 with a distinct error code so clients can render remediation
      text specific to the gap.
    - ``supports_build_metadata`` is ``False`` or ``None`` — emit the
      degraded-validation shadow metric and let the transition
      through. Burn-down is an operator dashboard concern.

    Runs only for target states ``review`` and ``done``; inbox /
    in_progress / cancelled / rework skip the gate outright.
    """

    if task.status not in _DEPLOY_TRUTH_REQUIRED_STATUSES:
        return
    if task.validation_target is None:
        # No target to fetch against — delivery-contract guard above
        # already rejected this for kinds that require a target. For
        # ``content_copy``/``review_only`` kinds the target is legit
        # null; deploy-truth has nothing to verify.
        return

    # Phase V §I8: honor the ``deploy_truth_v1`` rollout flag. Only
    # an EXPLICIT ``False`` opts a board out — a missing key means
    # "not yet recorded a preference", and prior behaviour
    # (pre-flag-wiring) was to enforce the gate unconditionally.
    # Defaulting missing-to-disabled would silently turn off
    # enforcement on every existing board (default
    # ``Board.rollout_flags={}`` per ``models/boards.py``). Codex
    # review 2026-04-24 caught this regression in the first
    # iteration of this gate. The flag existed in the schema
    # allowlist (``schemas/boards.py``) but had no consumer until
    # this commit.
    if rollout_flags is not None and rollout_flags.get("deploy_truth_v1") is False:
        _schedule_deploy_degraded_emit(
            task_id=task.id,
            board_id=task.board_id,
            agent_id=actor_agent_id,
            status_value=task.status,
            reason="deploy_truth_v1_disabled",
        )
        return

    if task.supports_build_metadata is not True:
        reason = (
            "supports_build_metadata_unknown"
            if task.supports_build_metadata is None
            else "supports_build_metadata_false"
        )
        _schedule_deploy_degraded_emit(
            task_id=task.id,
            board_id=task.board_id,
            agent_id=actor_agent_id,
            status_value=task.status,
            reason=reason,
        )
        return

    if task.packet_commit_sha is None:
        raise _deploy_truth_error(
            code=ERROR_CODE_DEPLOY_TRUTH_MISSING_PACKET_SHA,
            message=(
                f"Transition to {task.status} requires packet_commit_sha "
                "when the target supports build metadata."
            ),
            status_value=task.status,
        )

    try:
        metadata = await fetch_build_metadata(task.validation_target)
    except DeployTruthFetchError as exc:
        raise _deploy_truth_error(
            code=ERROR_CODE_DEPLOY_TRUTH_UNREACHABLE,
            message=(
                f"Target build endpoint unreachable: {exc}. Mark the "
                "target supports_build_metadata=false to opt into "
                "degraded validation."
            ),
            status_value=task.status,
        ) from exc

    if metadata.sha is None:
        raise _deploy_truth_error(
            code=ERROR_CODE_DEPLOY_TRUTH_UNREACHABLE,
            message=(
                "Target /__build responded without a SHA field. "
                "Downgrade the target's capability flag or fix the "
                "build-metadata endpoint."
            ),
            status_value=task.status,
        )

    if not packet_sha_matches_live(
        packet_sha=task.packet_commit_sha, live_sha=metadata.sha
    ):
        raise _deploy_truth_error(
            code=ERROR_CODE_DEPLOY_TRUTH_SHA_MISMATCH,
            message=(
                f"Packet SHA {task.packet_commit_sha} does not match "
                f"live build SHA {metadata.sha}."
            ),
            status_value=task.status,
            extra={
                "packet_commit_sha": task.packet_commit_sha,
                "live_sha": metadata.sha,
                "built_at": metadata.built_at,
                "branch": metadata.branch,
                "target": metadata.target,
            },
        )


_actionability_emitter = BackgroundEmitter(
    name="shadow_metrics.actionability_violation", max_pending=128
)
_deploy_degraded_emitter = BackgroundEmitter(
    name="shadow_metrics.deploy_validation_degraded", max_pending=128
)
_lane_quieting_emitter = BackgroundEmitter(
    name="shadow_metrics.comment_lane_quieting_suppressed", max_pending=128
)

# In-memory dedupe for the degraded-metric emit. Post-migration every
# task has ``supports_build_metadata=None`` until operators classify
# targets, so without dedupe every ``review``/``done`` PATCH would
# write a metric row — flooding ``shadow_metric_events`` against a
# table that's meant to track rare-ish signals. Dedupe key is
# ``(task_id, status, reason)``: a genuine re-transition from ``done``
# back to ``review`` and back to ``done`` still emits two rows (two
# status values); a chatty PATCH loop against the same state does not.
# Window is a plain set since process restarts naturally clear it and
# the signal is eventually-consistent.
_DEPLOY_DEGRADED_DEDUPE: set[tuple[UUID, str, str]] = set()
_DEPLOY_DEGRADED_DEDUPE_MAX = 4096


def _schedule_actionability_violation_emit(
    *,
    task_id: UUID,
    board_id: UUID | None,
    agent_id: UUID | None,
    status_value: str,
    missing_fields: list[str],
) -> None:
    """Fire-and-forget wrapper for emit_actionability_violation_metric."""

    _actionability_emitter.schedule(
        emit_actionability_violation_metric(
            task_id=task_id,
            board_id=board_id,
            agent_id=agent_id,
            status_value=status_value,
            missing_fields=missing_fields,
        ),
        log_key=str(task_id),
    )


async def drain_actionability_emit_tasks() -> None:
    await _actionability_emitter.drain()


def _schedule_deploy_degraded_emit(
    *,
    task_id: UUID,
    board_id: UUID | None,
    agent_id: UUID | None,
    status_value: str,
    reason: str,
) -> None:
    key = (task_id, status_value, reason)
    if key in _DEPLOY_DEGRADED_DEDUPE:
        return
    # Process-lifetime bound so the dedupe set can't grow forever on a
    # long-running gateway. When full, drop the oldest-added half —
    # good enough for a signal that operators burn down by hand.
    #
    # Known limitation: cross-worker runs share no state, so a task
    # seen on worker A and again on worker B emits twice. Also a
    # legitimate re-entry (``done → inbox → done`` with same reason)
    # emits only once per process. Cross-worker + TTL fixes belong
    # with the Phase VI dashboard work.
    if len(_DEPLOY_DEGRADED_DEDUPE) >= _DEPLOY_DEGRADED_DEDUPE_MAX:
        _DEPLOY_DEGRADED_DEDUPE.clear()
    enqueued = _deploy_degraded_emitter.schedule(
        emit_deploy_validation_degraded_metric(
            task_id=task_id,
            board_id=board_id,
            agent_id=agent_id,
            status_value=status_value,
            reason=reason,
        ),
        log_key=str(task_id),
    )
    if enqueued:
        # Only record the dedupe key when the emit actually ran —
        # otherwise a backlog-full drop would silently suppress the
        # next retry for the same (task, status, reason) triple.
        _DEPLOY_DEGRADED_DEDUPE.add(key)


async def drain_deploy_degraded_emit_tasks() -> None:
    await _deploy_degraded_emitter.drain()


async def drain_lane_quieting_emit_tasks() -> None:
    await _lane_quieting_emitter.drain()


async def _reject_pending_move_to_done_approvals_for_task(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> None:
    done_approval_action_types = DONE_APPROVAL_ACTION_TYPES
    linked_rows = list(
        await session.exec(
            select(Approval)
            .join(ApprovalTaskLink, col(ApprovalTaskLink.approval_id) == col(Approval.id))
            .where(col(Approval.board_id) == board_id)
            .where(col(Approval.status) == "pending")
            .where(col(Approval.action_type).in_(done_approval_action_types))
            .where(col(ApprovalTaskLink.task_id) == task_id),
        ),
    )
    direct_rows = list(
        await session.exec(
            select(Approval)
            .where(col(Approval.board_id) == board_id)
            .where(col(Approval.status) == "pending")
            .where(col(Approval.action_type).in_(done_approval_action_types))
            .where(col(Approval.task_id) == task_id),
        ),
    )
    approvals_by_id = {approval.id: approval for approval in [*linked_rows, *direct_rows]}
    if not approvals_by_id:
        return
    resolved_at = utcnow()
    for approval in approvals_by_id.values():
        approval.status = "rejected"
        approval.resolved_at = resolved_at
        session.add(approval)


async def _task_has_approved_linked_approval(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> bool:
    linked_approval_ids = select(col(ApprovalTaskLink.approval_id)).where(
        col(ApprovalTaskLink.task_id) == task_id,
    )
    statement = (
        select(col(Approval.id))
        .where(col(Approval.board_id) == board_id)
        .where(col(Approval.status) == "approved")
        .where(
            or_(
                col(Approval.task_id) == task_id,
                col(Approval.id).in_(linked_approval_ids),
            ),
        )
        .limit(1)
    )
    return (await session.exec(statement)).first() is not None


async def _task_has_pending_linked_approval(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> bool:
    conflicts = await pending_approval_conflicts_by_task(
        session,
        board_id=board_id,
        task_ids=[task_id],
    )
    return task_id in conflicts


async def _require_approved_linked_approval_for_done(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    previous_status: str,
    target_status: str,
) -> None:
    if previous_status == "done" or target_status != "done":
        return
    requires_approval = (
        await session.exec(
            select(col(Board.require_approval_for_done)).where(col(Board.id) == board_id),
        )
    ).first()
    if requires_approval is False:
        return
    if not await _task_has_approved_linked_approval(
        session,
        board_id=board_id,
        task_id=task_id,
    ):
        raise _approval_required_for_done_error()


async def _require_review_before_done_when_enabled(
    session: AsyncSession,
    *,
    board_id: UUID,
    previous_status: str,
    target_status: str,
) -> None:
    if previous_status == "done" or target_status != "done":
        return
    requires_review = (
        await session.exec(
            select(col(Board.require_review_before_done)).where(col(Board.id) == board_id),
        )
    ).first()
    if requires_review and previous_status != "review":
        raise _review_required_for_done_error()


async def _require_comment_for_review_when_enabled(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> bool:
    requires_comment = (
        await session.exec(
            select(col(Board.comment_required_for_review)).where(col(Board.id) == board_id),
        )
    ).first()
    return bool(requires_comment)


async def _require_no_pending_approval_for_status_change_when_enabled(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    previous_status: str,
    target_status: str,
    status_requested: bool,
) -> None:
    if not status_requested or previous_status == target_status:
        return
    blocks_status_change = (
        await session.exec(
            select(col(Board.block_status_changes_with_pending_approval)).where(
                col(Board.id) == board_id,
            ),
        )
    ).first()
    if not blocks_status_change:
        return
    if await _task_has_pending_linked_approval(
        session,
        board_id=board_id,
        task_id=task_id,
    ):
        raise _pending_approval_blocks_status_change_error()


def _truncate_snippet(value: str) -> str:
    text = value.strip()
    if len(text) <= TASK_SNIPPET_MAX_LEN:
        return text
    return f"{text[:TASK_SNIPPET_TRUNCATED_LEN]}..."


async def has_valid_recent_comment(
    session: AsyncSession,
    task: Task,
    agent_id: UUID | None,
    since: datetime | None,
) -> bool:
    """Check whether the task has a recent non-empty comment by the agent."""
    if agent_id is None or since is None:
        return False
    statement = (
        select(ActivityEvent)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.agent_id) == agent_id)
        .where(col(ActivityEvent.created_at) >= since)
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    event = (await session.exec(statement)).first()
    if event is None or event.message is None:
        return False
    return bool(event.message.strip())


async def _has_recent_task_comment_matching(
    session: AsyncSession,
    *,
    task: Task,
    agent_id: UUID | None,
    since: datetime | None,
    pattern: re.Pattern[str],
) -> bool:
    if agent_id is None or since is None:
        return False
    statement = (
        select(col(ActivityEvent.message))
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.agent_id) == agent_id)
        .where(col(ActivityEvent.created_at) >= since)
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    for message in await session.exec(statement):
        if message and pattern.match(message):
            return True
    return False


async def _latest_recent_task_comment_matching(
    session: AsyncSession,
    *,
    task: Task,
    agent_id: UUID | None,
    since: datetime | None,
    pattern: re.Pattern[str],
) -> str | None:
    if agent_id is None or since is None:
        return None
    statement = (
        select(col(ActivityEvent.message))
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.agent_id) == agent_id)
        .where(col(ActivityEvent.created_at) >= since)
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    for message in await session.exec(statement):
        if message and pattern.match(message):
            return message
    return None


async def _task_has_unresolved_rework_marker(
    session: AsyncSession,
    *,
    task_id: UUID,
) -> bool:
    statement = (
        select(col(ActivityEvent.message))
        .where(col(ActivityEvent.task_id) == task_id)
        .where(col(ActivityEvent.event_type) == "task.status_changed")
        .where(col(ActivityEvent.message).like("Task moved to %:%"))
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    for message in await session.exec(statement):
        if not message:
            continue
        match = TASK_STATUS_CHANGED_RE.match(message)
        if match is None:
            continue
        status_value = match.group(1)
        if status_value in ALLOWED_STATUSES:
            return status_value == "rework"
    return False


def _parse_since(value: str | None) -> datetime | None:
    """Parse an optional ISO-8601 timestamp into a naive UTC `datetime`.

    The API accepts either naive timestamps (treated as UTC) or timezone-aware values.
    Returning naive UTC simplifies SQLModel comparisons against stored naive UTC values.
    """

    if not value:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    # Allow common ISO-8601 `Z` suffix (UTC) even though `datetime.fromisoformat` expects `+00:00`.
    normalized = normalized.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)

    # No tzinfo: interpret as UTC for consistency with other API timestamps.
    return parsed


def _coerce_task_items(items: Sequence[object]) -> list[Task]:
    """Validate/convert paginated query results to a concrete `list[Task]`.

    SQLModel pagination helpers return `Sequence[object]`; we validate types early so the
    rest of the route logic can assume real `Task` instances.
    """

    tasks: list[Task] = []
    for item in items:
        if not isinstance(item, Task):
            msg = "Expected Task items from paginated query"
            raise TypeError(msg)
        tasks.append(item)
    return tasks


def _coerce_task_event_rows(
    items: Sequence[object],
) -> list[tuple[ActivityEvent, Task | None]]:
    """Normalize DB rows into `(ActivityEvent, Task | None)` tuples.

    Depending on the SQLAlchemy/SQLModel execution path, result rows may arrive as:
    - real Python tuples, or
    - row-like objects supporting `__len__` and `__getitem__`.

    This helper centralizes validation so SSE/event-stream logic can assume a stable shape.
    """

    rows: list[tuple[ActivityEvent, Task | None]] = []
    for item in items:
        first: object
        second: object

        if isinstance(item, tuple):
            if len(item) != TASK_EVENT_ROW_LEN:
                msg = "Expected (ActivityEvent, Task | None) rows"
                raise TypeError(msg)
            first, second = item
        else:
            try:
                row_len = len(item)  # type: ignore[arg-type]
                first = item[0]  # type: ignore[index]
                second = item[1]  # type: ignore[index]
            except (IndexError, KeyError, TypeError):
                msg = "Expected (ActivityEvent, Task | None) rows"
                raise TypeError(msg) from None
            if row_len != TASK_EVENT_ROW_LEN:
                msg = "Expected (ActivityEvent, Task | None) rows"
                raise TypeError(msg)

        if isinstance(first, ActivityEvent) and (isinstance(second, Task) or second is None):
            rows.append((first, second))
            continue

        msg = "Expected (ActivityEvent, Task | None) rows"
        raise TypeError(msg)
    return rows


async def _lead_was_mentioned(
    session: AsyncSession,
    task: Task,
    lead: Agent,
) -> bool:
    """Return `True` if the lead agent is mentioned in any comment on the task.

    This is used to avoid redundant lead pings (especially in auto-created tasks) while still
    ensuring escalation happens when explicitly requested.
    """

    statement = (
        select(ActivityEvent.message)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    for message in await session.exec(statement):
        if not message:
            continue
        mentions = extract_mentions(message)
        if matches_agent_mention(lead, mentions):
            return True
    return False


def _lead_created_task(task: Task, lead: Agent) -> bool:
    """Return `True` if `task` was auto-created by the lead agent."""

    if not task.auto_created or not task.auto_reason:
        return False
    return task.auto_reason == f"lead_agent:{lead.id}"


async def _reconcile_dependents_for_dependency_toggle(
    session: AsyncSession,
    *,
    board_id: UUID,
    dependency_task: Task,
    previous_status: str,
    actor_agent_id: UUID | None,
) -> None:
    """Apply dependency side-effects when a dependency task toggles done/undone.

    The UI models dependencies as a DAG: when a dependency is reopened, dependents that were
    previously marked done may need to be reopened or flagged. This helper keeps dependent state
    consistent with the dependency graph without duplicating logic across endpoints.
    """

    done_toggled = (previous_status == "done") != (dependency_task.status == "done")
    if not done_toggled:
        return

    dependent_ids = await dependent_task_ids(
        session,
        board_id=board_id,
        dependency_task_id=dependency_task.id,
    )
    if not dependent_ids:
        return

    dependents = list(
        await session.exec(
            select(Task)
            .where(col(Task.board_id) == board_id)
            .where(col(Task.id).in_(dependent_ids)),
        ),
    )
    reopened = previous_status == "done" and dependency_task.status != "done"

    for dependent in dependents:
        if dependent.status == "done":
            continue
        if reopened:
            should_reset = (
                dependent.status != "inbox"
                or dependent.assigned_agent_id is not None
                or dependent.in_progress_at is not None
            )
            if should_reset:
                dependent.status = "inbox"
                dependent.assigned_agent_id = None
                dependent.in_progress_at = None
                dependent.updated_at = utcnow()
                session.add(dependent)
                record_activity(
                    session,
                    event_type="task.status_changed",
                    task_id=dependent.id,
                    message=(
                        "Task returned to inbox: dependency reopened " f"({dependency_task.title})."
                    ),
                    agent_id=actor_agent_id,
                    board_id=dependent.board_id,
                )
            else:
                record_activity(
                    session,
                    event_type="task.updated",
                    task_id=dependent.id,
                    message=f"Dependency completion changed: {dependency_task.title}.",
                    agent_id=actor_agent_id,
                    board_id=dependent.board_id,
                )
        else:
            record_activity(
                session,
                event_type="task.updated",
                task_id=dependent.id,
                message=f"Dependency completion changed: {dependency_task.title}.",
                agent_id=actor_agent_id,
                board_id=dependent.board_id,
            )


async def _fetch_task_events(
    session: AsyncSession,
    board_id: UUID,
    since: datetime,
) -> list[tuple[ActivityEvent, Task | None]]:
    task_ids = list(
        await session.exec(select(Task.id).where(col(Task.board_id) == board_id)),
    )
    if not task_ids:
        return []
    statement = (
        select(ActivityEvent, Task)
        .outerjoin(Task, col(ActivityEvent.task_id) == col(Task.id))
        .where(col(ActivityEvent.task_id).in_(task_ids))
        .where(col(ActivityEvent.event_type).in_(TASK_EVENT_TYPES))
        .where(col(ActivityEvent.created_at) >= since)
        .order_by(asc(col(ActivityEvent.created_at)))
    )
    result = await session.execute(statement)
    return _coerce_task_event_rows(list(result.tuples().all()))


def _serialize_comment(event: ActivityEvent) -> dict[str, object]:
    return TaskCommentRead.model_validate(event).model_dump(mode="json")


async def _send_lead_task_message(
    *,
    dispatch: GatewayDispatchService,
    session_key: str,
    config: GatewayClientConfig,
    agent_name: str,
    message: str,
) -> OpenClawGatewayError | None:
    return await dispatch.try_send_agent_message(
        session_key=session_key,
        config=config,
        agent_name=agent_name,
        message=message,
        deliver=False,
    )


async def _send_agent_task_message(
    *,
    dispatch: GatewayDispatchService,
    session_key: str,
    config: GatewayClientConfig,
    agent_name: str,
    message: str,
) -> OpenClawGatewayError | None:
    return await dispatch.try_send_agent_message(
        session_key=session_key,
        config=config,
        agent_name=agent_name,
        message=message,
        deliver=False,
    )


def _assignment_notification_message(*, board: Board, task: Task, agent: Agent) -> str:
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    if task.status == "review" and agent.is_board_lead:
        action = (
            "Take action: review the deliverables now. "
            "Approve by moving to done or return to inbox with clear feedback."
        )
        return "TASK READY FOR LEAD REVIEW\n" + "\n".join(details) + f"\n\n{action}"
    return (
        "TASK ASSIGNED\n"
        + "\n".join(details)
        + ("\n\nTake action: open the task and begin work. " "Post updates as task comments.")
    )


def _rework_notification_message(
    *,
    board: Board,
    task: Task,
    feedback: str | None,
) -> str:
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    requested_changes = (
        _truncate_snippet(feedback)
        if feedback and feedback.strip()
        else "Lead requested changes. Review latest task comments for exact required updates."
    )
    return (
        "CHANGES REQUESTED\n"
        + "\n".join(details)
        + "\n\nRequested changes:\n"
        + requested_changes
        + "\n\nTake action: address the requested changes, then move the task back to review."
    )


async def _latest_task_comment_by_agent(
    session: AsyncSession,
    *,
    task_id: UUID,
    agent_id: UUID,
) -> str | None:
    statement = (
        select(col(ActivityEvent.message))
        .where(col(ActivityEvent.task_id) == task_id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .where(col(ActivityEvent.agent_id) == agent_id)
        .order_by(desc(col(ActivityEvent.created_at)))
        .limit(1)
    )
    return (await session.exec(statement)).first()


async def _wake_agent_online_for_task(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
    reason: str,
) -> None:
    if not agent.openclaw_session_id:
        return
    service = AgentLifecycleService(session)
    try:
        await service.commit_heartbeat(agent=agent, status_value="online")
        record_activity(
            session,
            event_type="task.assignee_woken",
            message=(f"Assignee heartbeat set online ({reason}): {agent.name}."),
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
    except Exception as exc:  # pragma: no cover - best effort wake path
        record_activity(
            session,
            event_type="task.assignee_wake_failed",
            message=(f"Assignee wake failed ({reason}): {agent.name}. Error: {exc!s}"),
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
    await session.commit()


async def _notify_agent_on_task_assign(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
    wake_assignee: bool = True,
) -> None:
    if not agent.openclaw_session_id:
        return
    if wake_assignee:
        await _wake_agent_online_for_task(
            session=session,
            board=board,
            task=task,
            agent=agent,
            reason="assignment",
        )
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    message = _assignment_notification_message(board=board, task=task, agent=agent)
    error = await _send_agent_task_message(
        dispatch=dispatch,
        session_key=agent.openclaw_session_id,
        config=config,
        agent_name=agent.name,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.assignee_notified",
            message=f"Agent notified for assignment: {agent.name}.",
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.assignee_notify_failed",
            message=f"Assignee notify failed: {error}",
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
        # Part D.2: if the dispatch failed because the agent's gateway
        # session is stale or pairing was revoked, materialise that
        # as a structured operator Blocker (per the board's
        # ``structured_blockers_v1`` rollout flag). The ambient
        # activity event above still records the failure; this adds
        # the routable structured state §I1 wants.
        await file_stale_agent_blocker_if_configured(
            session,
            board=board,
            task_id=task.id,
            agent_name=agent.name,
            exc=error,
        )


async def _notify_agent_on_task_rework(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
    lead: Agent,
) -> None:
    if not agent.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    feedback = await _latest_task_comment_by_agent(
        session,
        task_id=task.id,
        agent_id=lead.id,
    )
    message = _rework_notification_message(
        board=board,
        task=task,
        feedback=feedback,
    )
    error = await _send_agent_task_message(
        dispatch=dispatch,
        session_key=agent.openclaw_session_id,
        config=config,
        agent_name=agent.name,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.rework_notified",
            message=f"Assignee notified about requested changes: {agent.name}.",
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.rework_notify_failed",
            message=f"Rework notify failed: {error}",
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
        # Part D.2 parity with _notify_agent_on_task_assign: rework
        # notification hits the same ``_send_agent_task_message``
        # surface, so a stale-agent-session error here also routes
        # into a structured operator Blocker.
        await file_stale_agent_blocker_if_configured(
            session,
            board=board,
            task_id=task.id,
            agent_name=agent.name,
            exc=error,
        )


async def notify_agent_on_task_assign(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
) -> None:
    """Notify an assignee via gateway after task assignment."""
    await _notify_agent_on_task_assign(
        session=session,
        board=board,
        task=task,
        agent=agent,
    )


async def _notify_lead_on_task_create(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
) -> None:
    lead = (
        await Agent.objects.filter_by(board_id=board.id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    message = (
        "NEW TASK ADDED\n"
        + "\n".join(details)
        + "\n\nTake action: triage, assign, or plan next steps."
    )
    error = await _send_lead_task_message(
        dispatch=dispatch,
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.lead_notified",
            message=f"Lead agent notified for task: {task.title}.",
            agent_id=lead.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.lead_notify_failed",
            message=f"Lead notify failed: {error}",
            agent_id=lead.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()


async def _notify_lead_on_task_unassigned(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
) -> None:
    lead = (
        await Agent.objects.filter_by(board_id=board.id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return
    description = _truncate_snippet(task.description or "")
    details = [
        f"Board: {board.name}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
    ]
    if description:
        details.append(f"Description: {description}")
    message = (
        "TASK BACK IN INBOX\n"
        + "\n".join(details)
        + "\n\nTake action: assign a new owner or adjust the plan."
    )
    error = await _send_lead_task_message(
        dispatch=dispatch,
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=message,
    )
    if error is None:
        record_activity(
            session,
            event_type="task.lead_unassigned_notified",
            message=f"Lead notified task returned to inbox: {task.title}.",
            agent_id=lead.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
    else:
        record_activity(
            session,
            event_type="task.lead_unassigned_notify_failed",
            message=f"Lead notify failed: {error}",
            agent_id=lead.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()



async def _notify_lead_on_end_work_event(
    *,
    session: AsyncSession,
    task: Task,
    reason: str,
) -> None:
    """Wake the board lead when an agent finishes work that needs lead action.

    Fires on status transitions to review (worker finished), review
    event creation (reviewer finished), and rework resubmission.
    Uses ``deliver=True`` so the Supervisor acts immediately instead
    of waiting for the next scheduled heartbeat.

    Best-effort: exceptions are caught so the caller (review event
    creation, task status update) never fails due to a notification
    issue.
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
            f"END_WORK: {reason}\n"
            f"Task: {task.title} ({task.id})\n"
            f"Status: {task.status}\n"
            f"Route per lead-review-routing skill."
        )
        error = await dispatch.try_send_agent_message(
            session_key=lead.openclaw_session_id,
            config=config,
            agent_name=lead.name,
            message=message,
            deliver=True,
        )
        if error:
            record_activity(
                session,
                event_type="task.end_work_notify_failed",
                task_id=task.id,
                message=f"Failed to notify lead on end-work event ({reason}): {error}",
                agent_id=lead.id,
            )
            await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "end-work notify suppressed: %s (task=%s reason=%s)",
            exc, task.id, reason,
        )


def _status_values(status_filter: str | None) -> list[str]:
    if not status_filter:
        return []
    values = [s.strip() for s in status_filter.split(",") if s.strip()]
    if any(value not in ALLOWED_STATUSES for value in values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported task status filter.",
        )
    return values


async def _organization_custom_field_definitions_for_board(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> dict[str, _BoardCustomFieldDefinition]:
    organization_id = (
        await session.exec(
            select(Board.organization_id).where(col(Board.id) == board_id),
        )
    ).first()
    if organization_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    definitions = list(
        await session.exec(
            select(TaskCustomFieldDefinition)
            .join(
                BoardTaskCustomField,
                col(BoardTaskCustomField.task_custom_field_definition_id)
                == col(TaskCustomFieldDefinition.id),
            )
            .where(
                col(BoardTaskCustomField.board_id) == board_id,
                col(TaskCustomFieldDefinition.organization_id) == organization_id,
            ),
        ),
    )
    return {
        definition.field_key: _BoardCustomFieldDefinition(
            id=definition.id,
            field_key=definition.field_key,
            field_type=cast(TaskCustomFieldType, definition.field_type),
            validation_regex=definition.validation_regex,
            required=definition.required,
            default_value=definition.default_value,
        )
        for definition in definitions
    }


def _reject_unknown_custom_field_keys(
    *,
    custom_field_values: TaskCustomFieldValues,
    definitions_by_key: dict[str, _BoardCustomFieldDefinition],
) -> None:
    unknown_field_keys = sorted(set(custom_field_values) - set(definitions_by_key))
    if not unknown_field_keys:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": "Unknown custom field keys for this board.",
            "unknown_field_keys": unknown_field_keys,
        },
    )


def _reject_missing_required_custom_field_keys(
    *,
    effective_values: TaskCustomFieldValues,
    definitions_by_key: dict[str, _BoardCustomFieldDefinition],
) -> None:
    missing_field_keys = [
        definition.field_key
        for definition in definitions_by_key.values()
        if definition.required and effective_values.get(definition.field_key) is None
    ]
    if not missing_field_keys:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": "Required custom fields must have values.",
            "missing_field_keys": sorted(missing_field_keys),
        },
    )


def _reject_invalid_custom_field_values(
    *,
    custom_field_values: TaskCustomFieldValues,
    definitions_by_key: dict[str, _BoardCustomFieldDefinition],
) -> None:
    for field_key, value in custom_field_values.items():
        definition = definitions_by_key[field_key]
        try:
            validate_custom_field_value(
                field_type=definition.field_type,
                value=value,
                validation_regex=definition.validation_regex,
            )
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": "Invalid custom field value.",
                    "field_key": field_key,
                    "field_type": definition.field_type,
                    "reason": str(err),
                },
            ) from err


async def _task_custom_field_rows_by_definition_id(
    session: AsyncSession,
    *,
    task_id: UUID,
    definition_ids: list[UUID],
) -> dict[UUID, TaskCustomFieldValue]:
    if not definition_ids:
        return {}
    rows = list(
        await session.exec(
            select(TaskCustomFieldValue).where(
                col(TaskCustomFieldValue.task_id) == task_id,
                col(TaskCustomFieldValue.task_custom_field_definition_id).in_(definition_ids),
            ),
        ),
    )
    return {row.task_custom_field_definition_id: row for row in rows}


async def _set_task_custom_field_values_for_create(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    custom_field_values: TaskCustomFieldValues,
) -> None:
    definitions_by_key = await _organization_custom_field_definitions_for_board(
        session,
        board_id=board_id,
    )
    _reject_unknown_custom_field_keys(
        custom_field_values=custom_field_values,
        definitions_by_key=definitions_by_key,
    )
    _reject_invalid_custom_field_values(
        custom_field_values=custom_field_values,
        definitions_by_key=definitions_by_key,
    )

    effective_values: TaskCustomFieldValues = {}
    for field_key, definition in definitions_by_key.items():
        if field_key in custom_field_values:
            effective_values[field_key] = custom_field_values[field_key]
        else:
            effective_values[field_key] = definition.default_value

    _reject_missing_required_custom_field_keys(
        effective_values=effective_values,
        definitions_by_key=definitions_by_key,
    )

    for field_key, definition in definitions_by_key.items():
        value = effective_values.get(field_key)
        if value is None:
            continue
        session.add(
            TaskCustomFieldValue(
                task_id=task_id,
                task_custom_field_definition_id=definition.id,
                value=value,
            ),
        )


async def _set_task_custom_field_values_for_update(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
    custom_field_values: TaskCustomFieldValues,
) -> None:
    definitions_by_key = await _organization_custom_field_definitions_for_board(
        session,
        board_id=board_id,
    )
    _reject_unknown_custom_field_keys(
        custom_field_values=custom_field_values,
        definitions_by_key=definitions_by_key,
    )
    _reject_invalid_custom_field_values(
        custom_field_values=custom_field_values,
        definitions_by_key=definitions_by_key,
    )
    definitions_by_id = {definition.id: definition for definition in definitions_by_key.values()}
    rows_by_definition_id = await _task_custom_field_rows_by_definition_id(
        session,
        task_id=task_id,
        definition_ids=list(definitions_by_id),
    )

    effective_values: TaskCustomFieldValues = {}
    for field_key, definition in definitions_by_key.items():
        current_row = rows_by_definition_id.get(definition.id)
        if field_key in custom_field_values:
            effective_values[field_key] = custom_field_values[field_key]
        elif current_row is not None:
            effective_values[field_key] = current_row.value
        else:
            effective_values[field_key] = definition.default_value

    _reject_missing_required_custom_field_keys(
        effective_values=effective_values,
        definitions_by_key=definitions_by_key,
    )

    for field_key, value in custom_field_values.items():
        definition = definitions_by_key[field_key]
        row = rows_by_definition_id.get(definition.id)
        if value is None:
            if row is not None:
                await session.delete(row)
            continue
        if row is None:
            session.add(
                TaskCustomFieldValue(
                    task_id=task_id,
                    task_custom_field_definition_id=definition.id,
                    value=value,
                ),
            )
            continue
        row.value = value
        row.updated_at = utcnow()
        session.add(row)


async def _task_custom_field_values_by_task_id(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: Sequence[UUID],
) -> dict[UUID, TaskCustomFieldValues]:
    unique_task_ids = list({*task_ids})
    if not unique_task_ids:
        return {}

    definitions_by_key = await _organization_custom_field_definitions_for_board(
        session,
        board_id=board_id,
    )
    if not definitions_by_key:
        return {task_id: {} for task_id in unique_task_ids}

    definitions_by_id = {definition.id: definition for definition in definitions_by_key.values()}
    default_values = {
        field_key: definition.default_value for field_key, definition in definitions_by_key.items()
    }
    values_by_task_id: dict[UUID, TaskCustomFieldValues] = {
        task_id: dict(default_values) for task_id in unique_task_ids
    }

    rows = (
        await session.exec(
            select(
                col(TaskCustomFieldValue.task_id),
                col(TaskCustomFieldValue.task_custom_field_definition_id),
                col(TaskCustomFieldValue.value),
            ).where(
                col(TaskCustomFieldValue.task_id).in_(unique_task_ids),
                col(TaskCustomFieldValue.task_custom_field_definition_id).in_(
                    list(definitions_by_id),
                ),
            ),
        )
    ).all()
    for task_id, definition_id, value in rows:
        definition = definitions_by_id.get(definition_id)
        if definition is None:
            continue
        values_by_task_id[task_id][definition.field_key] = value
    return values_by_task_id


def _task_list_statement(
    *,
    board_id: UUID,
    status_filter: str | None,
    assigned_agent_id: UUID | None,
    unassigned: bool | None,
) -> SelectOfScalar[Task]:
    statement = select(Task).where(Task.board_id == board_id)
    statuses = _status_values(status_filter)
    if statuses:
        statement = statement.where(col(Task.status).in_(statuses))
    if assigned_agent_id is not None:
        statement = statement.where(col(Task.assigned_agent_id) == assigned_agent_id)
    if unassigned:
        statement = statement.where(col(Task.assigned_agent_id).is_(None))
    return statement.order_by(col(Task.created_at).desc())


async def _task_read_page(
    *,
    session: AsyncSession,
    board_id: UUID,
    tasks: Sequence[Task],
) -> list[TaskRead]:
    if not tasks:
        return []

    task_ids = [task.id for task in tasks]
    tag_state_by_task_id = await load_tag_state(
        session,
        task_ids=task_ids,
    )
    deps_map = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=task_ids,
    )
    dep_ids: list[UUID] = []
    for value in deps_map.values():
        dep_ids.extend(value)
    dep_status = await dependency_status_by_id(
        session,
        board_id=board_id,
        dependency_ids=list({*dep_ids}),
    )
    custom_field_values_by_task_id = await _task_custom_field_values_by_task_id(
        session,
        board_id=board_id,
        task_ids=task_ids,
    )
    blocked_task_ids = await task_ids_with_open_blocker(
        session, board_id=board_id, task_ids=task_ids
    )
    pending_decision_task_ids = await task_ids_with_pending_operator_decision(
        session, board_id=board_id, task_ids=task_ids
    )
    terminal_parent_ids = [t.id for t in tasks if t.status in TERMINAL_STATUSES]
    orphan_children_map = (
        await orphan_children_by_parent_id(
            session, board_id=board_id, parent_task_ids=terminal_parent_ids
        )
        if terminal_parent_ids
        else {}
    )

    output: list[TaskRead] = []
    for task in tasks:
        tag_state = tag_state_by_task_id.get(task.id, TagState())
        dep_list = deps_map.get(task.id, [])
        blocked_by = blocked_by_dependency_ids(
            dependency_ids=dep_list,
            status_by_id=dep_status,
        )
        if _status_clears_blockers(task.status):
            blocked_by = []
        output.append(
            TaskRead.model_validate(task, from_attributes=True).model_copy(
                update={
                    "depends_on_task_ids": dep_list,
                    "tag_ids": tag_state.tag_ids,
                    "tags": tag_state.tags,
                    "blocked_by_task_ids": blocked_by,
                    "is_blocked": _task_is_blocked(
                        task,
                        blocked_by,
                        has_open_blocker=task.id in blocked_task_ids,
                        has_pending_operator_decision=(
                            task.id in pending_decision_task_ids
                        ),
                    ),
                    "custom_field_values": custom_field_values_by_task_id.get(task.id, {}),
                    "orphan_child_task_ids": orphan_children_map.get(task.id, []),
                },
            ),
        )
    return output


async def _stream_task_state(
    session: AsyncSession,
    *,
    board_id: UUID,
    rows: list[tuple[ActivityEvent, Task | None]],
) -> tuple[
    dict[UUID, list[UUID]],
    dict[UUID, str],
    dict[UUID, TagState],
    dict[UUID, TaskCustomFieldValues],
    set[UUID],
    set[UUID],
]:
    task_ids = [
        task.id for event, task in rows if task is not None and event.event_type != "task.comment"
    ]
    if not task_ids:
        return {}, {}, {}, {}, set(), set()

    unique_task_ids = list({*task_ids})
    tag_state_by_task_id = await load_tag_state(
        session,
        task_ids=unique_task_ids,
    )
    deps_map = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=unique_task_ids,
    )
    dep_ids: list[UUID] = []
    for value in deps_map.values():
        dep_ids.extend(value)
    custom_field_values_by_task_id = await _task_custom_field_values_by_task_id(
        session,
        board_id=board_id,
        task_ids=unique_task_ids,
    )
    blocked_task_ids = await task_ids_with_open_blocker(
        session, board_id=board_id, task_ids=unique_task_ids
    )
    pending_decision_task_ids = (
        await task_ids_with_pending_operator_decision(
            session, board_id=board_id, task_ids=unique_task_ids
        )
    )
    dep_status: dict[UUID, str] = {}
    if dep_ids:
        dep_status = await dependency_status_by_id(
            session,
            board_id=board_id,
            dependency_ids=list({*dep_ids}),
        )
    return (
        deps_map,
        dep_status,
        tag_state_by_task_id,
        custom_field_values_by_task_id,
        blocked_task_ids,
        pending_decision_task_ids,
    )


def _task_event_payload(
    event: ActivityEvent,
    task: Task | None,
    *,
    deps_map: dict[UUID, list[UUID]],
    dep_status: dict[UUID, str],
    tag_state_by_task_id: dict[UUID, TagState],
    custom_field_values_by_task_id: dict[UUID, TaskCustomFieldValues] | None = None,
    blocked_task_ids: set[UUID] | None = None,
    pending_decision_task_ids: set[UUID] | None = None,
) -> dict[str, object]:
    resolved_custom_field_values_by_task_id = custom_field_values_by_task_id or {}
    payload: dict[str, object] = {
        "type": event.event_type,
        "activity": ActivityEventRead.model_validate(event).model_dump(
            mode="json",
            exclude={"board_id", "route_name", "route_params"},
        ),
    }
    if event.event_type == "task.comment":
        payload["comment"] = _serialize_comment(event)
        return payload
    if task is None:
        payload["task"] = None
        return payload

    tag_state = tag_state_by_task_id.get(task.id, TagState())
    dep_list = deps_map.get(task.id, [])
    blocked_by = blocked_by_dependency_ids(
        dependency_ids=dep_list,
        status_by_id=dep_status,
    )
    if _status_clears_blockers(task.status):
        blocked_by = []
    payload["task"] = (
        TaskRead.model_validate(task, from_attributes=True)
        .model_copy(
            update={
                "depends_on_task_ids": dep_list,
                "tag_ids": tag_state.tag_ids,
                "tags": tag_state.tags,
                "blocked_by_task_ids": blocked_by,
                "is_blocked": _task_is_blocked(
                    task,
                    blocked_by,
                    has_open_blocker=(
                        blocked_task_ids is not None
                        and task.id in blocked_task_ids
                    ),
                    has_pending_operator_decision=(
                        pending_decision_task_ids is not None
                        and task.id in pending_decision_task_ids
                    ),
                ),
                "custom_field_values": resolved_custom_field_values_by_task_id.get(
                    task.id,
                    {},
                ),
            },
        )
        .model_dump(mode="json")
    )
    return payload


async def _task_event_generator(
    *,
    request: Request,
    board_id: UUID,
    since_dt: datetime,
) -> AsyncIterator[dict[str, str]]:
    last_seen = since_dt
    seen_ids: set[UUID] = set()
    seen_queue: deque[UUID] = deque()

    while True:
        if await request.is_disconnected():
            break

        async with async_session_maker() as session:
            rows = await _fetch_task_events(session, board_id, last_seen)
            (
                deps_map,
                dep_status,
                tag_state_by_task_id,
                custom_field_values_by_task_id,
                blocked_task_ids,
                pending_decision_task_ids,
            ) = await _stream_task_state(
                session,
                board_id=board_id,
                rows=rows,
            )

        for event, task in rows:
            if event.id in seen_ids:
                continue
            seen_ids.add(event.id)
            seen_queue.append(event.id)
            if len(seen_queue) > SSE_SEEN_MAX:
                oldest = seen_queue.popleft()
                seen_ids.discard(oldest)
            last_seen = max(event.created_at, last_seen)

            payload = _task_event_payload(
                event,
                task,
                deps_map=deps_map,
                dep_status=dep_status,
                tag_state_by_task_id=tag_state_by_task_id,
                custom_field_values_by_task_id=custom_field_values_by_task_id,
                blocked_task_ids=blocked_task_ids,
                pending_decision_task_ids=pending_decision_task_ids,
            )
            yield {"event": "task", "data": json.dumps(payload)}
        await asyncio.sleep(2)


@router.get("/stream")
async def stream_tasks(
    request: Request,
    board: Board = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
    since: str | None = SINCE_QUERY,
) -> EventSourceResponse:
    """Stream task and task-comment events as SSE payloads."""
    since_dt = _parse_since(since) or utcnow()
    return EventSourceResponse(
        _task_event_generator(
            request=request,
            board_id=board.id,
            since_dt=since_dt,
        ),
        ping=15,
    )


@router.get("", response_model=DefaultLimitOffsetPage[TaskRead])
async def list_tasks(
    status_filter: str | None = STATUS_QUERY,
    assigned_agent_id: UUID | None = None,
    unassigned: bool | None = None,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> LimitOffsetPage[TaskRead]:
    """List board tasks with optional status and assignment filters."""
    statement = _task_list_statement(
        board_id=board.id,
        status_filter=status_filter,
        assigned_agent_id=assigned_agent_id,
        unassigned=unassigned,
    )

    async def _transform(items: Sequence[object]) -> Sequence[object]:
        tasks = _coerce_task_items(items)
        return await _task_read_page(
            session=session,
            board_id=board.id,
            tasks=tasks,
        )

    return await paginate(session, statement, transformer=_transform)


@router.post("", response_model=TaskRead, responses={409: {"model": BlockedTaskError}})
async def create_task(
    payload: TaskCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> TaskRead:
    """Create a task and initialize dependency rows."""
    data = payload.model_dump(exclude={"depends_on_task_ids", "tag_ids", "custom_field_values"})
    depends_on_task_ids = list(payload.depends_on_task_ids)
    tag_ids = list(payload.tag_ids)
    custom_field_values = dict(payload.custom_field_values)

    task = Task.model_validate(data)
    task.board_id = board.id
    if task.created_by_user_id is None and auth.user is not None:
        task.created_by_user_id = auth.user.id

    normalized_deps = await validate_dependency_update(
        session,
        board_id=board.id,
        task_id=task.id,
        depends_on_task_ids=depends_on_task_ids,
    )
    normalized_tag_ids = await validate_tag_ids(
        session,
        organization_id=board.organization_id,
        tag_ids=tag_ids,
    )
    dep_status = await dependency_status_by_id(
        session,
        board_id=board.id,
        dependency_ids=normalized_deps,
    )
    blocked_by = blocked_by_dependency_ids(
        dependency_ids=normalized_deps,
        status_by_id=dep_status,
    )
    if blocked_by and (task.assigned_agent_id is not None or task.status != "inbox"):
        raise _blocked_task_error(blocked_by)
    if task.operator_decision_required and (task.assigned_agent_id is not None or task.status != "inbox"):
        raise _operator_decision_block_error(task.operator_decision_summary)
    await _validate_parent_task_id(
        session,
        board_id=board.id,
        task_id=task.id,
        parent_task_id=task.parent_task_id,
    )
    _require_delivery_contract_with_metric(
        task=task,
        actor_agent_id=None,  # create_task is user-initiated (USER_AUTH_DEP)
    )
    rollout_flags = await _resolve_rollout_flags(session, board_id=task.board_id)
    await _require_deploy_truth(
        task,
        actor_agent_id=None,
        rollout_flags=rollout_flags,
    )
    session.add(task)
    # Ensure the task exists in the DB before inserting dependency rows.
    await session.flush()
    await _set_task_custom_field_values_for_create(
        session,
        board_id=board.id,
        task_id=task.id,
        custom_field_values=custom_field_values,
    )
    for dep_id in normalized_deps:
        session.add(
            TaskDependency(
                board_id=board.id,
                task_id=task.id,
                depends_on_task_id=dep_id,
            ),
        )
    await replace_tags(
        session,
        task_id=task.id,
        tag_ids=normalized_tag_ids,
    )
    await session.commit()
    await session.refresh(task)

    record_activity(
        session,
        event_type="task.created",
        task_id=task.id,
        message=f"Task created: {task.title}.",
        board_id=board.id,
    )
    await session.commit()
    await _notify_lead_on_task_create(session=session, board=board, task=task)
    if task.assigned_agent_id:
        assigned_agent = await Agent.objects.by_id(task.assigned_agent_id).first(
            session,
        )
        if assigned_agent:
            await _notify_agent_on_task_assign(
                session=session,
                board=board,
                task=task,
                agent=assigned_agent,
            )
    return await _task_read_response(
        session,
        task=task,
        board_id=board.id,
    )


def _task_pipeline_event_read(event: TaskPipelineEvent) -> TaskPipelineEventRead:
    return TaskPipelineEventRead(
        id=event.id,
        board_id=event.board_id,
        task_id=event.task_id,
        agent_id=event.agent_id,
        state=event.state,
        source=event.source,
        commit_sha=event.commit_sha,
        artifact_hash=event.artifact_hash,
        deploy_target=event.deploy_target,
        live_sha=event.live_sha,
        evidence=event.evidence,
        created_at=event.created_at,
    )


async def _require_task_pipeline_write_access(
    session: AsyncSession,
    *,
    task: Task,
    actor: ActorContext,
) -> UUID | None:
    if actor.actor_type == "agent":
        if actor.agent is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if actor.agent.board_id and actor.agent.board_id != task.board_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return actor.agent.id
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    board = await Board.objects.by_id(task.board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await require_board_access(session, user=actor.user, board=board, write=True)
    return None


def _pipeline_event_missing_required_fields_error(
    *,
    state: str,
    missing_fields: list[str],
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": (
                f"Pipeline event `{state}` is missing required field(s): "
                f"{', '.join(missing_fields)}."
            ),
            "code": "task_pipeline_event_missing_required_fields",
            "state": state,
            "missing_fields": missing_fields,
        },
    )


# Statuses where posting pipeline events is rejected because the task
# has no valid in_progress cycle anchor (or has been removed from scope).
# - rework: events posted here get silently discarded by the next cycle
#   reset on rework→in_progress (E.3 incident 2026-05-03).
# - inbox: same cycle-anchor problem; agent should PATCH inbox→in_progress
#   first.
# - cancelled: task is dead; new pipeline events would pollute audit
#   trails on work the operator/lead explicitly removed from scope.
_PIPELINE_EVENT_REJECTED_STATUSES: Final[frozenset[str]] = frozenset(
    {"rework", "inbox", "cancelled"},
)


_PIPELINE_EVENT_REJECTION_REASONS: Final[dict[str, str]] = {
    "rework": (
        "Task is in rework — PATCH `rework → in_progress` first so the new "
        "cycle anchor is in place. Events posted under rework are silently "
        "discarded by the next cycle reset."
    ),
    "inbox": (
        "Task is in inbox — PATCH `inbox → in_progress` first to start the "
        "work cycle. Events posted under inbox have no cycle anchor and "
        "are silently discarded by the first cycle reset."
    ),
    "cancelled": (
        "Task is cancelled — operator/lead has removed it from scope. New "
        "pipeline events on a cancelled task pollute audit trails on dead "
        "work. Ask the operator to reactivate (uncancel) the task before "
        "posting events."
    ),
}


def _pipeline_event_requires_in_progress_error(*, current_status: str) -> HTTPException:
    message = _PIPELINE_EVENT_REJECTION_REASONS.get(
        current_status,
        f"Pipeline events cannot be recorded while task status is `{current_status}`.",
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": message,
            "code": "pipeline_event_requires_in_progress",
            "current_status": current_status,
        },
    )


def _allowed_reviewer_roles_for_agent(agent: Agent) -> set[str]:
    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    role = str(profile.get("role") or "").strip().lower()
    name = agent.name.strip().lower()
    dev_acp_flow = str(profile.get("dev_acp_flow") or "").strip().lower()
    validation_flow = str(profile.get("validation_flow") or "").strip().lower()
    haystack = f"{name} {role}"
    roles: set[str] = set()
    if agent.is_board_lead:
        roles.add("lead")
    if dev_acp_flow == "review_only" or "architect" in haystack or "code reviewer" in role:
        roles.add("architect")
    if validation_flow == "qa_validation" or "qa" in haystack or "quality assurance" in role:
        if "e2e" in haystack or "browser" in haystack:
            roles.add("qa_e2e")
        if "unit" in haystack or "validator" in haystack or "quality assurance" in role:
            roles.add("qa_unit")
    if "devops" in haystack or "infrastructure" in role or "infra" in role:
        roles.add("devops")
    return roles


def _require_reviewer_role_allowed(
    *,
    actor: ActorContext,
    reviewer_role: str,
) -> None:
    if actor.actor_type != "agent" or actor.agent is None:
        return
    allowed_roles = _allowed_reviewer_roles_for_agent(actor.agent)
    if reviewer_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": f"Agent may not record `{reviewer_role}` review events.",
                "code": "reviewer_role_not_allowed",
                "allowed_roles": sorted(allowed_roles),
            },
        )


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> TaskRead:
    """Return the full task envelope by id.

    Pair endpoint to ``GET /tasks`` (list) — lets clients fetch one task
    without paginating the whole board. Output shape matches list-page
    items (same enrichments via ``_task_read_page``).
    """
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    page = await _task_read_page(session=session, board_id=task.board_id, tasks=[task])
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return page[0]


@router.get("/{task_id}/pipeline", response_model=TaskPipelineStateRead)
async def get_task_pipeline_state(
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TaskPipelineStateRead:
    """Return structured pipeline readiness for the current task cycle."""
    cycle_since = task.in_progress_at or task.previous_in_progress_at
    events = await list_task_pipeline_events(
        session,
        task_id=task.id,
        since=cycle_since,
    )
    present_states = pipeline_present_states(events)
    missing_states = pipeline_missing_states(events)
    latest_fallback = latest_model_fallback_step(events)
    return TaskPipelineStateRead(
        task_id=task.id,
        required_states=list(FRONTEND_REVIEW_PIPELINE_STATES),
        present_states=present_states,
        missing_states=missing_states,
        ready=not missing_states,
        events=[_task_pipeline_event_read(event) for event in events],
        latest_fallback_step=(
            _task_pipeline_event_read(latest_fallback)
            if latest_fallback is not None
            else None
        ),
    )


@router.post("/{task_id}/pipeline/events", response_model=TaskPipelineEventRead)
async def record_task_pipeline_event(
    payload: TaskPipelineEventCreate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> TaskPipelineEventRead:
    """Record an append-only structured pipeline event for a task."""
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    agent_id = await _require_task_pipeline_write_access(
        session,
        task=task,
        actor=actor,
    )
    if task.status in _PIPELINE_EVENT_REJECTED_STATUSES:
        raise _pipeline_event_requires_in_progress_error(current_status=task.status)
    missing_fields = pipeline_missing_required_fields(
        state=payload.state,
        values={
            "commit_sha": payload.commit_sha,
            "artifact_hash": payload.artifact_hash,
            "deploy_target": payload.deploy_target,
            "live_sha": payload.live_sha,
            "evidence": payload.evidence,
        },
    )
    if missing_fields:
        raise _pipeline_event_missing_required_fields_error(
            state=payload.state,
            missing_fields=missing_fields,
        )
    if payload.overwrite:
        existing = (
            await session.exec(
                select(TaskPipelineEvent)
                .where(col(TaskPipelineEvent.task_id) == task.id)
                .where(col(TaskPipelineEvent.state) == payload.state)
                .order_by(desc(col(TaskPipelineEvent.created_at)))
            )
        ).first()
        if existing is not None:
            merged = False
            for field in ("commit_sha", "artifact_hash", "deploy_target", "live_sha", "evidence"):
                new_val = getattr(payload, field, None)
                if new_val is not None and getattr(existing, field) is None:
                    setattr(existing, field, new_val)
                    merged = True
            if payload.source and payload.source != "api":
                existing.source = payload.source
            if merged:
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
                # Phase V §I9 Fix 2 — overwrite-merge can supply the
                # final missing required field, flipping pipeline.ready
                # to true. Codex review caught that the original Fix 2
                # commit only hooked the create path. Both paths must
                # call the resolver.
                merge_resolved_count = await auto_resolve_pipeline_blockers_if_ready(
                    session,
                    board_id=task.board_id,
                    task_id=task.id,
                )
                if merge_resolved_count:
                    await session.commit()
                    if not await task_has_open_blocker(
                        session, board_id=task.board_id, task_id=task.id
                    ):
                        await notify_lead_after_blocker_resolved(
                            session=session, task=task
                        )
                return _task_pipeline_event_read(existing)
    event = TaskPipelineEvent(
        board_id=task.board_id,
        task_id=task.id,
        agent_id=agent_id,
        state=payload.state,
        source=payload.source or "api",
        commit_sha=payload.commit_sha,
        artifact_hash=payload.artifact_hash,
        deploy_target=payload.deploy_target,
        live_sha=payload.live_sha,
        evidence=payload.evidence,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    # Phase V §I9 Fix 2 — auto-resolve system-authored pipeline Blockers
    # when this event makes ``pipeline.ready=true``. Closes the AC5
    # failure mode where the lead's pipeline_missing_review_gate Blocker
    # would stay open forever after the worker filled in the missing
    # events. Best-effort: if the event committed but the resolver call
    # raises, the next pipeline-event POST will reconcile.
    resolved_count = await auto_resolve_pipeline_blockers_if_ready(
        session,
        board_id=task.board_id,
        task_id=task.id,
    )
    if resolved_count:
        await session.commit()
        if not await task_has_open_blocker(
            session, board_id=task.board_id, task_id=task.id
        ):
            await notify_lead_after_blocker_resolved(
                session=session, task=task
            )
    return _task_pipeline_event_read(event)


@router.get("/{task_id}/review-readiness", response_model=TaskReviewReadinessRead)
async def get_task_review_readiness_state(
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TaskReviewReadinessRead:
    """Return structured reviewer verdict readiness for the current task cycle."""
    return await get_task_review_readiness(session, task=task)


def _review_event_lead_message(
    *,
    board: Board,
    task: Task,
    event: TaskReviewEvent,
) -> str:
    return "\n".join(
        [
            "STRUCTURED REVIEW EVENT",
            f"Board: {board.name}",
            f"Task: {task.title}",
            f"Task ID: {task.id}",
            f"Reviewer role: {event.reviewer_role}",
            f"Verdict: {event.verdict}",
            "",
            "Run the lead next-action and review-readiness gates for this task.",
        ],
    )


async def _notify_lead_on_review_event(
    *,
    session: AsyncSession,
    task: Task,
    event: TaskReviewEvent,
) -> None:
    if task.board_id is None:
        return
    board = await Board.objects.by_id(task.board_id).first(session)
    if board is None:
        return
    lead = (
        await Agent.objects.filter_by(board_id=task.board_id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return
    if event.agent_id is not None and event.agent_id == lead.id:
        return

    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return

    error = await dispatch.try_send_agent_message(
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=_review_event_lead_message(board=board, task=task, event=event),
        deliver=True,
    )
    if error is None:
        record_activity(
            session,
            event_type="review_event.lead_notified",
            message=f"Lead agent notified for structured review event {event.id}.",
            agent_id=lead.id,
            task_id=task.id,
            board_id=task.board_id,
        )
    else:
        record_activity(
            session,
            event_type="review_event.lead_notify_failed",
            message=f"Lead notify failed for structured review event {event.id}: {error}",
            agent_id=lead.id,
            task_id=task.id,
            board_id=task.board_id,
        )
    await session.commit()


@router.post("/{task_id}/review-events", response_model=TaskReviewEventRead)
async def record_task_review_event(
    payload: TaskReviewEventCreate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> TaskReviewEventRead:
    """Record an append-only structured reviewer verdict for a task."""
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    agent_id = await _require_task_pipeline_write_access(
        session,
        task=task,
        actor=actor,
    )
    _require_reviewer_role_allowed(actor=actor, reviewer_role=payload.reviewer_role)
    event = TaskReviewEvent(
        board_id=task.board_id,
        task_id=task.id,
        agent_id=agent_id,
        reviewer_role=payload.reviewer_role,
        verdict=payload.verdict,
        evidence_type=payload.evidence_type,
        target=payload.target,
        build_hash=payload.build_hash,
        source_commit=payload.source_commit,
        blocking_owner=payload.blocking_owner,
        suggested_routing=payload.suggested_routing,
        evidence=payload.evidence,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    # Phase V §I9 — auto-transition review → rework on FAIL verdicts.
    # Without this, an Architect/QA FAIL only flips readiness non-ready;
    # the task stays in ``review`` and the lead has no signal to route
    # remediation. AC5 incident at 2026-05-02 01:48 UTC sat in review for
    # ~12h with an unaddressed FAIL because the status never moved.
    # Mirrors lead-path rework side-effects at ``_lead_apply_status``:
    # snapshot in_progress_at, stamp rework_started_at, capture
    # rework_entry_commit_sha, route assignee back to the last worker
    # who moved this task to review (the implementer, not the reviewer).
    # ``session.refresh(task)`` before the status check closes the
    # stale-read race: under ``expire_on_commit=False`` the in-memory
    # ``task.status`` would otherwise reflect the value loaded at handler
    # entry, so a concurrent transition (e.g. another lead/admin moving
    # ``review -> done``) could be silently overwritten. After refresh
    # we only auto-transition if the canonical row still says ``review``.
    # ``_task_has_pending_linked_approval`` + board flag check mirrors
    # the regular PATCH path's pending-approval gate (codex 2026-05-02
    # holistic review caught the bypass: my auto-rework would land
    # status=rework while a pending move_to_done approval stayed linked
    # to the now-non-review task). When the gate would block the same
    # transition on the regular PATCH path, the auto-transition is
    # silently skipped — the FAIL event is still committed (visible in
    # readiness) and operator can choose to cancel or honor the
    # approval before the next status move.
    await session.refresh(task)
    if payload.verdict == "fail" and task.status == "review":
        board_blocks_on_pending_approval = (
            await session.exec(
                select(col(Board.block_status_changes_with_pending_approval)).where(
                    col(Board.id) == task.board_id,
                ),
            )
        ).first()
        if board_blocks_on_pending_approval and await _task_has_pending_linked_approval(
            session,
            board_id=task.board_id,
            task_id=task.id,
        ):
            record_activity(
                session,
                event_type="review_event.auto_rework_skipped_pending_approval",
                message=(
                    f"FAIL verdict on {task.title} did not trigger auto-rework: "
                    "pending linked approval blocks status change "
                    "(Board.block_status_changes_with_pending_approval=True). "
                    "Operator must resolve the approval before status moves."
                ),
                agent_id=agent_id,
                task_id=task.id,
                board_id=task.board_id,
            )
            await session.commit()
        else:
            lead = (
                await Agent.objects.filter_by(board_id=task.board_id)
                .filter(col(Agent.is_board_lead).is_(True))
                .first(session)
            )
            last_worker_id: UUID | None = None
            if lead is not None:
                last_worker_id = await _last_worker_who_moved_task_to_review(
                    session,
                    task_id=task.id,
                    board_id=task.board_id,
                    lead_agent_id=lead.id,
                )
            rework_at = utcnow()
            task.previous_in_progress_at = task.in_progress_at
            task.in_progress_at = None
            task.rework_started_at = rework_at
            task.rework_entry_commit_sha = task.packet_commit_sha
            task.assigned_agent_id = last_worker_id
            task.status = "rework"
            task.updated_at = rework_at
            session.add(task)
            record_activity(
                session,
                event_type="task.status_changed",
                message=(
                    f"Task moved to rework: {task.title} "
                    f"(auto-transition on {payload.reviewer_role} FAIL verdict)."
                ),
                agent_id=agent_id,
                task_id=task.id,
                board_id=task.board_id,
            )
            await session.commit()
            await session.refresh(task)
    try:
        await _notify_lead_on_review_event(session=session, task=task, event=event)
    except Exception:
        logger.exception(
            "review_event.lead_notify_unexpected board_id=%s task_id=%s event_id=%s",
            task.board_id,
            task.id,
            event.id,
        )
    return task_review_event_read(event)


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    responses={409: {"model": BlockedTaskError}},
)
async def update_task(
    payload: TaskUpdate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> TaskRead:
    """Update task status, assignment, comment, and dependency state."""
    if task.board_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Task board_id is required.",
        )
    board_id = task.board_id
    if actor.actor_type == "user" and actor.user is not None:
        await _require_task_user_write_access(
            session,
            board_id=board_id,
            user=actor.user,
        )
    previous_status = task.status
    previous_assigned = task.assigned_agent_id
    updates = payload.model_dump(exclude_unset=True)
    comment = payload.comment if "comment" in payload.model_fields_set else None
    depends_on_task_ids = (
        payload.depends_on_task_ids if "depends_on_task_ids" in payload.model_fields_set else None
    )
    tag_ids = payload.tag_ids if "tag_ids" in payload.model_fields_set else None
    custom_field_values = (
        payload.custom_field_values if "custom_field_values" in payload.model_fields_set else None
    )
    custom_field_values_set = "custom_field_values" in payload.model_fields_set
    updates.pop("comment", None)
    updates.pop("depends_on_task_ids", None)
    updates.pop("tag_ids", None)
    updates.pop("custom_field_values", None)
    requested_status = payload.status if "status" in payload.model_fields_set else None
    update = _TaskUpdateInput(
        task=task,
        actor=actor,
        board_id=board_id,
        previous_status=previous_status,
        previous_assigned=previous_assigned,
        previous_in_progress_at=task.in_progress_at,
        status_requested=(requested_status is not None and requested_status != previous_status),
        updates=updates,
        comment=comment,
        depends_on_task_ids=depends_on_task_ids,
        tag_ids=tag_ids,
        custom_field_values=custom_field_values or {},
        custom_field_values_set=custom_field_values_set,
    )
    if actor.actor_type == "agent" and actor.agent and actor.agent.is_board_lead:
        return await _apply_lead_task_update(session, update=update)

    if actor.actor_type == "agent":
        await _apply_non_lead_agent_task_rules(session, update=update)
    else:
        await _apply_admin_task_rules(session, update=update)
    return await _finalize_updated_task(
        session,
        update=update,
    )


async def delete_task_and_related_records(
    session: AsyncSession,
    *,
    task: Task,
) -> None:
    """Delete a task and associated relational records, then commit."""
    await crud.delete_where(
        session,
        ActivityEvent,
        col(ActivityEvent.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskFingerprint,
        col(TaskFingerprint.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskPipelineEvent,
        col(TaskPipelineEvent.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskReviewEvent,
        col(TaskReviewEvent.task_id) == task.id,
        commit=False,
    )

    primary_approvals = list(
        await Approval.objects.filter(col(Approval.task_id) == task.id).all(session),
    )
    await crud.delete_where(
        session,
        ApprovalTaskLink,
        col(ApprovalTaskLink.task_id) == task.id,
        commit=False,
    )
    if primary_approvals:
        primary_ids = [approval.id for approval in primary_approvals]
        remaining_by_approval = await load_task_ids_by_approval(session, approval_ids=primary_ids)
        for approval in primary_approvals:
            remaining_task_ids = remaining_by_approval.get(approval.id, [])
            if remaining_task_ids:
                approval.task_id = remaining_task_ids[0]
                session.add(approval)
                continue
            await session.delete(approval)
    await crud.delete_where(
        session,
        TaskDependency,
        or_(
            col(TaskDependency.task_id) == task.id,
            col(TaskDependency.depends_on_task_id) == task.id,
        ),
        commit=False,
    )
    await crud.delete_where(
        session,
        TagAssignment,
        col(TagAssignment.task_id) == task.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        TaskCustomFieldValue,
        col(TaskCustomFieldValue.task_id) == task.id,
        commit=False,
    )
    await session.delete(task)
    await session.commit()


@router.delete("/{task_id}", response_model=OkResponse)
async def delete_task(
    session: AsyncSession = SESSION_DEP,
    task: Task = TASK_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> OkResponse:
    """Delete a task and related records."""
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    board = await Board.objects.by_id(task.board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=True)
    await delete_task_and_related_records(session, task=task)
    return OkResponse()


INCLUDE_FLAGGED_QUERY = Query(default=False)


@router.get(
    "/{task_id}/comments",
    response_model=DefaultLimitOffsetPage[TaskCommentRead],
)
async def list_task_comments(
    board: Board = BOARD_READ_DEP,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
    include_flagged: bool = INCLUDE_FLAGGED_QUERY,
) -> LimitOffsetPage[TaskCommentRead]:
    """List comments for a task in chronological order.

    Applies the board's ``comment_signal_filter`` policy. See
    ``app/services/comment_policy.py`` for filter semantics.
    """

    filter_mode = board.comment_signal_filter
    statement = (
        select(ActivityEvent)
        .where(col(ActivityEvent.task_id) == task.id)
        .where(col(ActivityEvent.event_type) == "task.comment")
        .order_by(asc(col(ActivityEvent.created_at)))
    )
    statement = apply_comment_signal_filter(
        statement,
        filter_mode=filter_mode,
        actor_is_agent=actor.actor_type == "agent",
        include_flagged=include_flagged,
    )
    return await paginate(session, statement)


async def _validate_task_comment_access(
    session: AsyncSession,
    *,
    task: Task,
    actor: ActorContext,
) -> None:
    if task.board_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    if actor.actor_type == "user" and actor.user is not None:
        board = await Board.objects.by_id(task.board_id).first(session)
        if board is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await require_board_access(session, user=actor.user, board=board, write=True)

    if (
        actor.actor_type == "agent"
        and actor.agent
        and actor.agent.is_board_lead
        and task.status != "review"
        and not await _lead_was_mentioned(session, task, actor.agent)
        and not _lead_created_task(task, actor.agent)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Board leads can only comment during review, when mentioned, "
                "or on tasks they created."
            ),
        )


def _comment_actor_id(actor: ActorContext) -> UUID | None:
    if actor.actor_type == "agent" and actor.agent:
        return actor.agent.id
    return None


def _comment_actor_name(actor: ActorContext) -> str:
    if actor.actor_type == "agent" and actor.agent:
        return actor.agent.name
    return "User"


async def _comment_targets(
    session: AsyncSession,
    *,
    task: Task,
    message: str,
    actor: ActorContext,
) -> tuple[dict[UUID, Agent], set[str]]:
    mention_names = extract_mentions(message)
    targets: dict[UUID, Agent] = {}
    if mention_names and task.board_id:
        for agent in await Agent.objects.filter_by(board_id=task.board_id).all(session):
            if matches_agent_mention(agent, mention_names):
                targets[agent.id] = agent
    if not mention_names and task.assigned_agent_id:
        assigned_agent = await Agent.objects.by_id(task.assigned_agent_id).first(
            session,
        )
        if assigned_agent:
            targets[assigned_agent.id] = assigned_agent

    if actor.actor_type == "agent" and actor.agent:
        targets.pop(actor.agent.id, None)
    return targets, mention_names


@dataclass(frozen=True, slots=True)
class _TaskCommentNotifyRequest:
    task: Task
    actor: ActorContext
    message: str
    targets: dict[UUID, Agent]
    mention_names: set[str]


async def _notify_task_comment_targets(
    session: AsyncSession,
    *,
    request: _TaskCommentNotifyRequest,
) -> None:
    if not request.targets:
        return
    board = (
        await Board.objects.by_id(request.task.board_id).first(session)
        if request.task.board_id
        else None
    )
    if board is None:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if not config:
        return

    snippet = _truncate_snippet(request.message)
    actor_name = _comment_actor_name(request.actor)
    for agent in request.targets.values():
        if not agent.openclaw_session_id:
            continue
        mentioned = matches_agent_mention(agent, request.mention_names)
        header = "TASK MENTION" if mentioned else "NEW TASK COMMENT"
        action_line = (
            "You were mentioned in this comment."
            if mentioned
            else "A new comment was posted on your task."
        )
        notification = (
            f"{header}\n"
            f"Board: {board.name}\n"
            f"Task: {request.task.title}\n"
            f"Task ID: {request.task.id}\n"
            f"From: {actor_name}\n\n"
            f"{action_line}\n\n"
            f"Comment:\n{snippet}\n\n"
            "If you are mentioned but not assigned, reply in the task "
            "thread but do not change task status."
        )
        # Mentioned agents (especially @lead) get deliver=True for
        # immediate wake — they need to act on the mention now.
        # Non-mentioned targets (assigned agent) get deliver=False
        # to avoid unnecessary wakes on routine comments.
        should_deliver = mentioned
        error = await dispatch.try_send_agent_message(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=notification,
            deliver=should_deliver,
        )
        if error:
            record_activity(
                session,
                event_type="task.comment_notify_failed",
                task_id=request.task.id,
                message=(
                    f"Failed to notify {agent.name} "
                    f"(deliver={should_deliver}): {error}"
                ),
                agent_id=agent.id,
            )


@dataclass(slots=True)
class _TaskUpdateInput:
    task: Task
    actor: ActorContext
    board_id: UUID
    previous_status: str
    previous_assigned: UUID | None
    status_requested: bool
    updates: dict[str, object]
    comment: str | None
    depends_on_task_ids: list[UUID] | None
    tag_ids: list[UUID] | None
    custom_field_values: TaskCustomFieldValues
    custom_field_values_set: bool
    previous_in_progress_at: datetime | None = None
    normalized_tag_ids: list[UUID] | None = None


def _required_status_value(value: object) -> str:
    if isinstance(value, str):
        return value
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _optional_assigned_agent_id(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


async def _board_organization_id(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> UUID:
    organization_id = (
        await session.exec(
            select(Board.organization_id).where(col(Board.id) == board_id),
        )
    ).first()
    if organization_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return organization_id


async def _task_dep_ids(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> list[UUID]:
    deps_map = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=[task_id],
    )
    return deps_map.get(task_id, [])


async def _task_blocked_ids(
    session: AsyncSession,
    *,
    board_id: UUID,
    dep_ids: Sequence[UUID],
) -> list[UUID]:
    if not dep_ids:
        return []
    dep_status = await dependency_status_by_id(
        session,
        board_id=board_id,
        dependency_ids=list(dep_ids),
    )
    return blocked_by_dependency_ids(
        dependency_ids=list(dep_ids),
        status_by_id=dep_status,
    )


async def _task_read_response(
    session: AsyncSession,
    *,
    task: Task,
    board_id: UUID,
) -> TaskRead:
    dep_ids = await _task_dep_ids(session, board_id=board_id, task_id=task.id)
    tag_state = (await load_tag_state(session, task_ids=[task.id])).get(
        task.id,
        TagState(),
    )
    blocked_ids = await _task_blocked_ids(
        session,
        board_id=board_id,
        dep_ids=dep_ids,
    )
    custom_field_values_by_task_id = await _task_custom_field_values_by_task_id(
        session,
        board_id=board_id,
        task_ids=[task.id],
    )
    if _status_clears_blockers(task.status):
        blocked_ids = []
    has_open_blocker = await task_has_open_blocker(
        session, board_id=board_id, task_id=task.id
    )
    has_pending_decision = await task_has_pending_operator_decision(
        session, board_id=board_id, task_id=task.id
    )
    # Phase V — surface orphan children only when the task itself is
    # terminal. Skipping the lookup for non-terminal tasks keeps the
    # hot path's query count unchanged.
    if task.status in TERMINAL_STATUSES:
        orphan_child_ids = await non_terminal_children_of(
            session, board_id=board_id, parent_task_id=task.id
        )
    else:
        orphan_child_ids = []
    return TaskRead.model_validate(task, from_attributes=True).model_copy(
        update={
            "depends_on_task_ids": dep_ids,
            "tag_ids": tag_state.tag_ids,
            "tags": tag_state.tags,
            "blocked_by_task_ids": blocked_ids,
            "is_blocked": _task_is_blocked(
                task,
                blocked_ids,
                has_open_blocker=has_open_blocker,
                has_pending_operator_decision=has_pending_decision,
            ),
            "custom_field_values": custom_field_values_by_task_id.get(task.id, {}),
            "orphan_child_task_ids": orphan_child_ids,
        },
    )


async def _require_task_user_write_access(
    session: AsyncSession,
    *,
    board_id: UUID,
    user: User | None,
) -> None:
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=user, board=board, write=True)


def _lead_requested_fields(update: _TaskUpdateInput) -> set[str]:
    requested_fields = set(update.updates)
    if update.comment is not None:
        requested_fields.add("comment")
    if update.depends_on_task_ids is not None:
        requested_fields.add("depends_on_task_ids")
    if update.tag_ids is not None:
        requested_fields.add("tag_ids")
    if update.custom_field_values_set:
        requested_fields.add("custom_field_values")
    return requested_fields


def _validate_lead_update_request(update: _TaskUpdateInput) -> None:
    allowed_fields = {
        "assigned_agent_id",
        "status",
        "depends_on_task_ids",
        "tag_ids",
        "custom_field_values",
        "review_packet_type",
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
        "operator_decision_required",
        "operator_decision_summary",
        # Phase V §I8 deploy-truth metadata. Previously omitted —
        # codex review 2026-04-24 (finding G) flagged that leads
        # couldn't stamp a SHA on a review task before approving
        # done, which defeated the purpose of the gate. The
        # deploy-truth pre-apply gate at _apply_lead_task_update
        # already runs a projected check when these fields change.
        "packet_commit_sha",
        "packet_build_sha",
        "supports_build_metadata",
    }
    requested_fields = _lead_requested_fields(update)
    if update.comment is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Lead comment gate failed: board leads cannot include `comment` in task PATCH. "
                "Use the task comments endpoint instead."
            ),
        )
    disallowed_fields = requested_fields - allowed_fields
    if disallowed_fields:
        disallowed = ", ".join(sorted(disallowed_fields))
        allowed = ", ".join(sorted(allowed_fields))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Lead field gate failed: unsupported fields for board leads: "
                f"{disallowed}. Allowed fields: {allowed}."
            ),
        )


def _is_lead_rework_return(update: _TaskUpdateInput) -> bool:
    return (
        update.previous_status == "review"
        and update.task.status == "rework"
        and update.actor.actor_type == "agent"
        and update.actor.agent is not None
        and update.actor.agent.is_board_lead
    )


async def _lead_effective_dependencies(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> tuple[list[UUID], list[UUID]]:
    # Use newly normalized dependency updates when supplied; otherwise fall back
    # to the task's current dependencies for blocked-by evaluation.
    normalized_deps: list[UUID] | None = None
    if update.depends_on_task_ids is not None:
        if update.task.status == "done":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Cannot change task dependencies after a task is done."),
            )
        normalized_deps = await replace_task_dependencies(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
            depends_on_task_ids=update.depends_on_task_ids,
        )
    effective_deps = (
        normalized_deps
        if normalized_deps is not None
        else await _task_dep_ids(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
        )
    )
    blocked_by = await _task_blocked_ids(
        session,
        board_id=update.board_id,
        dep_ids=effective_deps,
    )
    return effective_deps, blocked_by


async def _normalized_update_tag_ids(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> list[UUID] | None:
    if update.tag_ids is None:
        return None
    organization_id = await _board_organization_id(
        session,
        board_id=update.board_id,
    )
    return await validate_tag_ids(
        session,
        organization_id=organization_id,
        tag_ids=update.tag_ids,
    )


async def _lead_apply_assignment(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if "assigned_agent_id" not in update.updates:
        return
    assigned_id = _optional_assigned_agent_id(update.updates["assigned_agent_id"])
    if not assigned_id:
        update.task.assigned_agent_id = None
        return
    agent = await Agent.objects.by_id(assigned_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if agent.is_board_lead:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Board leads cannot assign tasks to themselves.",
        )
    if agent.board_id and update.task.board_id and agent.board_id != update.task.board_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    update.task.assigned_agent_id = agent.id


async def _last_worker_who_moved_task_to_review(
    session: AsyncSession,
    *,
    task_id: UUID,
    board_id: UUID,
    lead_agent_id: UUID,
) -> UUID | None:
    statement = (
        select(col(ActivityEvent.agent_id))
        .where(col(ActivityEvent.task_id) == task_id)
        .where(col(ActivityEvent.event_type) == "task.status_changed")
        .where(col(ActivityEvent.message).like("Task moved to review:%"))
        .where(col(ActivityEvent.agent_id).is_not(None))
        .order_by(desc(col(ActivityEvent.created_at)))
    )
    candidate_ids = list(await session.exec(statement))
    for candidate_id in candidate_ids:
        if candidate_id is None or candidate_id == lead_agent_id:
            continue
        candidate = await Agent.objects.by_id(candidate_id).first(session)
        if candidate is None:
            continue
        if candidate.board_id != board_id or candidate.is_board_lead:
            continue
        return candidate.id
    return None


async def _lead_apply_status(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.actor.actor_type != "agent" or update.actor.agent is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    lead_agent = update.actor.agent
    if "status" not in update.updates:
        return
    target_status = _required_status_value(update.updates["status"])
    if update.task.status == "cancelled" or target_status == "cancelled":
        raise _operator_only_cancel_error()
    # Leads may set `in_progress` when simultaneously assigning an agent to an
    # inbox task (assignment-and-start shortcut).
    if update.task.status != "review":
        assigning_agent = "assigned_agent_id" in update.updates and bool(
            _optional_assigned_agent_id(update.updates["assigned_agent_id"])
        )
        if update.task.status == "inbox" and target_status == "in_progress" and assigning_agent:
            # Auto-correct: if the target agent is a validator (QA or
            # review-only), use ``review`` instead of ``in_progress``.
            # Validators only process review-status tasks — assigning
            # them as in_progress leaves the task in a dead state.
            target_agent_id = _optional_assigned_agent_id(
                update.updates["assigned_agent_id"]
            )
            if target_agent_id is not None:
                target_agent = await Agent.objects.by_id(target_agent_id).first(
                    session
                )
                if target_agent is not None:
                    profile = (
                        target_agent.identity_profile
                        if isinstance(target_agent.identity_profile, dict)
                        else {}
                    )
                    is_validator = (
                        profile.get("validation_flow") == "qa_validation"
                        or profile.get("dev_acp_flow") == "review_only"
                    )
                    if is_validator:
                        target_status = "review"
            update.task.status = target_status
            # Stamp ``in_progress_at`` on the lead shortcut the same way the
            # non-lead path does at its ``in_progress`` branch. Without
            # this, a later ``review`` transition clears a null
            # ``in_progress_at`` into ``previous_in_progress_at``, losing
            # cycle-time truth.
            if target_status == "in_progress":
                update.task.in_progress_at = utcnow()
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Lead status gate failed: board leads can only change status when the current "
                f"task status is `review` (current: `{update.task.status}`)."
            ),
        )
    if target_status not in {"done", "inbox", "rework"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Lead status target gate failed: review tasks can only move to `done`, `inbox`, or "
                f"`rework` (requested: `{target_status}`)."
            ),
        )
    if target_status == "rework":
        if update.task.status != target_status:
            update.task.previous_in_progress_at = update.task.in_progress_at
            update.task.in_progress_at = None
            update.task.rework_started_at = utcnow()
            update.task.rework_entry_commit_sha = update.task.packet_commit_sha
        if "assigned_agent_id" not in update.updates:
            update.task.assigned_agent_id = await _last_worker_who_moved_task_to_review(
                session,
                task_id=update.task.id,
                board_id=update.board_id,
                lead_agent_id=lead_agent.id,
            )
        update.task.status = target_status
        return
    if target_status == "inbox":
        if update.task.status != target_status:
            update.task.previous_in_progress_at = update.task.in_progress_at
            update.task.in_progress_at = None
            update.task.rework_started_at = None
        if "assigned_agent_id" not in update.updates:
            update.task.assigned_agent_id = None
        update.task.status = target_status
        return
    if target_status == "done":
        update.task.rework_started_at = None
    update.task.status = target_status


def _task_event_details(task: Task, previous_status: str) -> tuple[str, str]:
    if task.status != previous_status:
        return "task.status_changed", f"Task moved to {task.status}: {task.title}."
    return "task.updated", f"Task updated: {task.title}."


async def _record_parent_terminated_event_if_orphans(
    session: AsyncSession,
    *,
    task: Task,
    previous_status: str,
    actor_agent_id: UUID | None,
) -> None:
    """Emit ``task.parent_terminated`` listing non-terminal children.

    Phase V cascade: when a parent task transitions into a terminal
    state, surface its non-terminal children as orphans in the
    activity stream. The event is informational — it does NOT mutate
    the children. Lead-cancel narrow exception (follow-up PR) and
    operator review consume this signal.
    """
    if previous_status == task.status:
        return
    if task.status not in TERMINAL_STATUSES:
        return
    if task.board_id is None:
        return
    orphan_ids = await non_terminal_children_of(
        session, board_id=task.board_id, parent_task_id=task.id
    )
    if not orphan_ids:
        return
    short_list = ", ".join(str(cid)[:8] for cid in orphan_ids[:5])
    if len(orphan_ids) > 5:
        short_list += f", +{len(orphan_ids) - 5} more"
    record_activity(
        session,
        event_type="task.parent_terminated",
        task_id=task.id,
        message=(
            f"Parent task moved to {task.status}; "
            f"{len(orphan_ids)} non-terminal child task(s) now orphaned: "
            f"{short_list}. Operator/lead may cancel obsolete children."
        ),
        agent_id=actor_agent_id,
        board_id=task.board_id,
    )


async def _lead_notify_new_assignee(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if (
        not update.task.assigned_agent_id
        or update.task.assigned_agent_id == update.previous_assigned
    ):
        return
    assigned_agent = await Agent.objects.by_id(update.task.assigned_agent_id).first(
        session,
    )
    if assigned_agent is None:
        return
    board = (
        await Board.objects.by_id(update.task.board_id).first(session)
        if update.task.board_id
        else None
    )
    if board:
        if _is_lead_rework_return(update):
            await _notify_agent_on_task_rework(
                session=session,
                board=board,
                task=update.task,
                agent=assigned_agent,
                lead=update.actor.agent,
            )
            return
        await _notify_agent_on_task_assign(
            session=session,
            board=board,
            task=update.task,
            agent=assigned_agent,
        )


async def _apply_lead_task_update(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> TaskRead:
    if update.actor.actor_type != "agent" or update.actor.agent is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    _validate_lead_update_request(update)
    _effective_deps, blocked_by = await _lead_effective_dependencies(
        session,
        update=update,
    )
    normalized_tag_ids = await _normalized_update_tag_ids(
        session,
        update=update,
    )
    effective_operator_decision_required = bool(
        update.updates.get(
            "operator_decision_required",
            update.task.operator_decision_required,
        ),
    )
    effective_operator_decision_summary = update.updates.get(
        "operator_decision_summary",
        update.task.operator_decision_summary,
    )

    # Blocked tasks should not be silently rewritten into a "blocked-safe" state.
    # Instead, reject assignment/status transitions with an explicit 409 payload.
    if blocked_by:
        attempted_fields: set[str] = set(update.updates.keys())
        attempted_transition = (
            "assigned_agent_id" in attempted_fields or "status" in attempted_fields
        )
        if attempted_transition:
            raise _blocked_task_error(blocked_by)
    attempted_fields = set(update.updates.keys())
    attempted_transition = (
        "assigned_agent_id" in attempted_fields or "status" in attempted_fields
    )
    # Phase V §I9 — open structured ``Blocker`` rows must veto forward
    # status transitions (in_progress/review/done) on the lead path,
    # mirroring the dependency and OperatorDecision vetoes above. Until
    # this guard existed, the AC5 incident at 2026-05-02 01:46 UTC was
    # possible: the lead path PATCHed ``status=review`` while a
    # pipeline_missing_review_gate Blocker stayed open. The guard fires
    # only on real forward transitions; ``rework`` / ``inbox`` /
    # ``cancelled`` stay reachable so blocked work can be parked, sent
    # back for fixes, or dropped without resolving every Blocker first.
    if "status" in attempted_fields:
        target_status = _required_status_value(update.updates["status"])
        if (
            target_status in {"in_progress", "review", "done"}
            and target_status != update.task.status
        ):
            open_blockers = await open_blocker_summary_for_task(
                session,
                board_id=update.board_id,
                task_id=update.task.id,
            )
            if open_blockers:
                raise _open_blocker_block_error(open_blockers)
    if (
        "operator_decision_required" in attempted_fields
        and effective_operator_decision_required
    ):
        target_status = _required_status_value(
            update.updates.get("status", update.task.status),
        )
        target_assigned_agent_id = (
            update.updates.get("assigned_agent_id", update.task.assigned_agent_id)
            if target_status != "inbox"
            else update.updates.get("assigned_agent_id")
        )
        legacy_odr_allowed = target_status in {"done", "cancelled"} or (
            target_status == "inbox" and target_assigned_agent_id is None
        )
        if not legacy_odr_allowed:
            raise _legacy_operator_decision_active_task_error(
                effective_operator_decision_summary
                if isinstance(effective_operator_decision_summary, str)
                or effective_operator_decision_summary is None
                else None
            )
    if effective_operator_decision_required and attempted_transition:
        raise _operator_decision_block_error(
            effective_operator_decision_summary
            if isinstance(effective_operator_decision_summary, str)
            or effective_operator_decision_summary is None
            else None
        )
    # Phase III: the new-entity path has to veto just as the legacy
    # flag does, otherwise a lead can advance a task blocked only by
    # a pending OperatorDecision — is_blocked would be advisory-only
    # on the lead path.
    if (
        attempted_transition
        and not effective_operator_decision_required
        and update.task.board_id is not None
        and await task_has_pending_operator_decision(
            session, board_id=update.task.board_id, task_id=update.task.id
        )
    ):
        raise _operator_decision_block_error()

    # Phase V §I8 parity: the non-lead path enforces deploy-truth
    # PRE-mutation via a projected task (``_finalize_updated_task`` at
    # ``_require_deploy_truth`` call-site). The lead path must run the
    # same pre-apply gate — lead PATCHes that change ``status`` /
    # ``validation_target`` / ``packet_commit_sha`` /
    # ``supports_build_metadata`` would otherwise skip SHA comparison
    # entirely. Same projection pattern keeps the 5s /__build fetch
    # outside any open ORM flush.
    if {
        "status",
        "validation_target",
        "packet_commit_sha",
        "supports_build_metadata",
    }.intersection(update.updates):
        projected = _projected_task(update.task, update.updates)
        rollout_flags = await _resolve_rollout_flags(session, board_id=update.board_id)
        await _require_deploy_truth(
            projected,
            actor_agent_id=_comment_actor_id(update.actor),
            rollout_flags=rollout_flags,
        )

    await _lead_apply_assignment(session, update=update)
    await _lead_apply_status(session, update=update)

    # Non-status / non-assignment fields (``review_packet_type``,
    # ``validation_target*``, ``operator_decision_*``,
    # ``packet_commit_sha``, ``packet_build_sha``,
    # ``supports_build_metadata``) are accepted by the lead validator
    # at ``_validate_lead_update_request`` but were silently dropped on
    # the lead path — ``_lead_apply_assignment`` + ``_lead_apply_status``
    # only handle those two scalars. Mirror the non-lead setattr loop
    # at ``_finalize_updated_task`` so the PATCH's intended fields
    # land on the Task before commit.
    for key, value in update.updates.items():
        if key in {"assigned_agent_id", "status"}:
            continue
        setattr(update.task, key, value)

    # Phase IV §I2 parity: delivery-contract revalidation after the
    # setattr loop. ``assigned_agent_id`` is in the trigger set so a
    # lead PATCH that clears the owner on an already-``in_progress``
    # or ``done`` task re-validates and 409s — same contract the
    # non-lead path enforces at ``_finalize_updated_task``.
    if {
        "status",
        "assigned_agent_id",
        "review_packet_type",
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    }.intersection(update.updates):
        _require_delivery_contract_with_metric(
            task=update.task,
            actor_agent_id=_comment_actor_id(update.actor),
        )

    await _require_no_pending_approval_for_status_change_when_enabled(
        session,
        board_id=update.board_id,
        task_id=update.task.id,
        previous_status=update.previous_status,
        target_status=update.task.status,
        status_requested=update.status_requested,
    )
    await _require_review_before_done_when_enabled(
        session,
        board_id=update.board_id,
        previous_status=update.previous_status,
        target_status=update.task.status,
    )
    await _require_approved_linked_approval_for_done(
        session,
        board_id=update.board_id,
        task_id=update.task.id,
        previous_status=update.previous_status,
        target_status=update.task.status,
    )

    if normalized_tag_ids is not None:
        await replace_tags(
            session,
            task_id=update.task.id,
            tag_ids=normalized_tag_ids,
        )
    if update.custom_field_values_set:
        await _set_task_custom_field_values_for_update(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
            custom_field_values=update.custom_field_values,
        )

    update.task.updated_at = utcnow()
    session.add(update.task)
    event_type, message = _task_event_details(update.task, update.previous_status)
    record_activity(
        session,
        event_type=event_type,
        task_id=update.task.id,
        message=message,
        agent_id=update.actor.agent.id,
        board_id=update.board_id,
    )
    await _record_parent_terminated_event_if_orphans(
        session,
        task=update.task,
        previous_status=update.previous_status,
        actor_agent_id=update.actor.agent.id,
    )
    await _reconcile_dependents_for_dependency_toggle(
        session,
        board_id=update.board_id,
        dependency_task=update.task,
        previous_status=update.previous_status,
        actor_agent_id=update.actor.agent.id,
    )
    await session.commit()
    await session.refresh(update.task)
    await _lead_notify_new_assignee(session, update=update)
    # Mirror the umbrella auto-cascade hook in _finalize_updated_task —
    # without this, lead-driven terminal transitions silently leave
    # retired umbrellas in inbox forever (codex review 2026-05-03).
    if update.task.status in TERMINAL_STATUSES:
        cascaded_parent = await maybe_cascade_umbrella_close(
            session, task=update.task
        )
        if cascaded_parent is not None:
            await session.commit()
    return await _task_read_response(
        session,
        task=update.task,
        board_id=update.board_id,
    )


async def _apply_non_lead_agent_task_rules(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.actor.actor_type != "agent":
        return
    if (
        update.actor.agent
        and update.actor.agent.board_id
        and update.task.board_id
        and update.actor.agent.board_id != update.task.board_id
    ):
        raise _task_update_forbidden_error(
            code="task_board_mismatch",
            message="Agent can only update tasks for their assigned board.",
        )
    # Allow agents to claim unassigned tasks by updating status (when permitted by board rules).
    if (
        update.actor.agent
        and update.task.assigned_agent_id is not None
        and update.task.assigned_agent_id != update.actor.agent.id
        and "status" in update.updates
    ):
        raise _task_update_forbidden_error(
            code="task_assignee_mismatch",
            message="Agents can only change status or commit metadata on tasks assigned to them.",
        )
    # Agents are limited to status/comment updates, and non-inbox status moves
    # must pass dependency checks before they can proceed.
    allowed_fields = {
        "status",
        "comment",
        "custom_field_values",
        "packet_commit_sha",
    }
    if (
        update.depends_on_task_ids is not None
        or update.tag_ids is not None
        or not set(update.updates).issubset(
            allowed_fields,
        )
    ):
        raise _task_update_forbidden_error(
            code="task_update_field_forbidden",
            message="Agents may only update status, comment, packet_commit_sha, and custom field values.",
        )
    if "status" in update.updates:
        only_lead_can_change_status = (
            await session.exec(
                select(col(Board.only_lead_can_change_status)).where(
                    col(Board.id) == update.board_id,
                ),
            )
        ).first()
        if only_lead_can_change_status:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only board leads can change task status.",
            )
        status_value = _required_status_value(update.updates["status"])
        if status_value == "cancelled" or update.task.status == "cancelled":
            raise _operator_only_cancel_error()
        _validate_agent_transition(
            from_status=update.task.status,
            to_status=status_value,
        )
        if status_value != "inbox":
            dep_ids = await _task_dep_ids(
                session,
                board_id=update.board_id,
                task_id=update.task.id,
            )
            blocked_ids = await _task_blocked_ids(
                session,
                board_id=update.board_id,
                dep_ids=dep_ids,
            )
            if blocked_ids:
                raise _blocked_task_error(blocked_ids)
            effective_operator_decision_required = bool(
                update.updates.get(
                    "operator_decision_required",
                    update.task.operator_decision_required,
                ),
            )
            effective_operator_decision_summary = update.updates.get(
                "operator_decision_summary",
                update.task.operator_decision_summary,
            )
            if effective_operator_decision_required:
                raise _operator_decision_block_error(
                    effective_operator_decision_summary
                    if isinstance(effective_operator_decision_summary, str)
                    or effective_operator_decision_summary is None
                    else None
                )
        # Phase V §I9 — open structured ``Blocker`` veto on the agent
        # path. Same shape as the lead-path guard in
        # ``_apply_lead_task_rules``: forward transitions
        # (in_progress/review/done) require all open Blockers resolved
        # first; ``rework`` / ``inbox`` / ``cancelled`` are escape
        # hatches for assignees to park, retry, or drop blocked work.
        # Fires only on real status changes, leaving the no-op
        # claim PATCH (``status=in_progress`` while already
        # in_progress, used to assign the actor) unaffected.
        if (
            status_value in {"in_progress", "review", "done"}
            and status_value != update.task.status
        ):
            open_blockers = await open_blocker_summary_for_task(
                session,
                board_id=update.board_id,
                task_id=update.task.id,
            )
            if open_blockers:
                raise _open_blocker_block_error(open_blockers)
        # ``status_changing`` distinguishes a real transition from a
        # no-op echo. Side effects that depend on the from→to delta
        # (clearing ``in_progress_at``, snapshotting it into
        # ``previous_in_progress_at``, clearing ``assigned_agent_id``
        # on inbox/review) must not run on no-ops — codex finding B
        # (2026-04-24) showed those would otherwise wipe the prior
        # snapshot to null. But owner-claim on ``in_progress`` /
        # ``rework`` MUST still run on no-ops: the public contract at
        # the top of this function ("agents may claim unassigned tasks
        # by updating status") relies on a no-op
        # ``status=in_progress`` PATCH to assign the actor. Skipping
        # it would leave actionable tasks owner-less and trigger the
        # downstream actionability gate. (Codex review 2026-04-24
        # caught this in the second pass.)
        status_changing = status_value != update.task.status
        if status_value == "inbox":
            if status_changing:
                update.task.assigned_agent_id = None
                update.task.previous_in_progress_at = update.task.in_progress_at
                update.task.in_progress_at = None
                update.task.rework_started_at = None
        elif status_value == "review":
            if status_changing:
                update.task.previous_in_progress_at = update.task.in_progress_at
                update.task.assigned_agent_id = None
                update.task.in_progress_at = None
        else:
            update.task.assigned_agent_id = update.actor.agent.id if update.actor.agent else None
            if status_value == "in_progress" and status_changing:
                update.task.in_progress_at = utcnow()


async def _apply_admin_task_rules(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    admin_normalized_deps: list[UUID] | None = None
    update.normalized_tag_ids = await _normalized_update_tag_ids(
        session,
        update=update,
    )
    if update.depends_on_task_ids is not None:
        if update.task.status == "done":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Cannot change task dependencies after a task is done."),
            )
        admin_normalized_deps = await replace_task_dependencies(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
            depends_on_task_ids=update.depends_on_task_ids,
        )

    effective_deps = (
        admin_normalized_deps
        if admin_normalized_deps is not None
        else await _task_dep_ids(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
        )
    )
    blocked_ids = await _task_blocked_ids(
        session,
        board_id=update.board_id,
        dep_ids=effective_deps,
    )
    target_status = _required_status_value(
        update.updates.get("status", update.task.status),
    )
    # Reset blocked tasks to inbox unless the task is moving into a terminal
    # status that intentionally clears blockers from active work tracking.
    if blocked_ids and not (
        (update.task.status == "done" and target_status == "done") or target_status == "cancelled"
    ):
        update.task.status = "inbox"
        update.task.assigned_agent_id = None
        update.task.in_progress_at = None
        update.task.rework_started_at = None
        update.updates["status"] = "inbox"
        update.updates["assigned_agent_id"] = None

    if "status" in update.updates:
        status_value = _required_status_value(update.updates["status"])
        # Admin-path side effects run only on an actual status CHANGE so
        # a no-op ``status=X`` PATCH cannot wipe ``previous_in_progress_at``.
        # The ``cancelled_at`` branches still need to run when toggling
        # in/out of cancelled, and are therefore checked explicitly below.
        status_changing = status_value != update.task.status
        if status_value == "inbox":
            if status_changing:
                update.task.previous_in_progress_at = update.task.in_progress_at
                update.task.assigned_agent_id = None
                update.task.in_progress_at = None
                update.task.rework_started_at = None
            if update.task.status == "cancelled":
                update.task.cancelled_at = None
        elif status_value == "cancelled":
            if status_changing:
                update.task.previous_in_progress_at = update.task.in_progress_at
                update.task.assigned_agent_id = None
                update.task.in_progress_at = None
                update.task.rework_started_at = None
                update.task.cancelled_at = utcnow()
                await _reject_pending_move_to_done_approvals_for_task(
                    session,
                    board_id=update.board_id,
                    task_id=update.task.id,
                )
        elif status_value == "review":
            if status_changing:
                update.task.previous_in_progress_at = update.task.in_progress_at
                update.task.assigned_agent_id = None
                update.task.in_progress_at = None
            if update.task.status == "cancelled":
                update.task.cancelled_at = None
        elif status_value == "rework":
            if status_changing:
                update.task.rework_started_at = utcnow()
                update.task.rework_entry_commit_sha = update.task.packet_commit_sha
        elif status_value == "in_progress":
            if status_changing:
                update.task.in_progress_at = utcnow()
            if update.task.status == "cancelled":
                update.task.cancelled_at = None
        elif status_value == "done" and status_changing:
            update.task.rework_started_at = None

    assigned_agent_id = _optional_assigned_agent_id(
        update.updates.get("assigned_agent_id"),
    )
    if assigned_agent_id:
        agent = await Agent.objects.by_id(assigned_agent_id).first(session)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if agent.board_id and update.task.board_id and agent.board_id != update.task.board_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT)


async def _apply_classifier_to_comment_event(
    session: AsyncSession,
    *,
    event: ActivityEvent,
    task: Task,
    agent_id: UUID | None,
    message: str,
) -> None:
    """Run the classifier and stamp event.classifier_flags + shadow events.

    Shared by both comment ingress paths (POST /comments, PATCH with
    comment). Call BEFORE session.add(event) so the prior-lookup can't
    see the uncommitted row. The caller still owns session.commit().

    Observability failure must never kill the caller's write: outer
    try/except catches any exception from the shadow pipeline and
    logs without propagating.
    """

    try:
        classifier_result = await build_shadow_events_for_comment(
            session,
            task_id=task.id,
            board_id=task.board_id,
            agent_id=agent_id,
            source_event_id=event.id,
            message=message,
            packet_type=task.review_packet_type,
        )
    except Exception:
        logger.exception(
            "shadow_metrics.hook_failed task_id=%s — comment write proceeds",
            task.id,
        )
        return
    # None column = classifier did not run (skipped or crashed).
    # classifier_ran=True = stamp the flag list (possibly [] = "clean").
    if classifier_result.classifier_ran:
        event.classifier_flags = [flag.value for flag in classifier_result.flags]
    for shadow in classifier_result.shadow_events:
        session.add(shadow)


async def _record_task_comment_from_update(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.comment is None or not update.comment.strip():
        return
    # Gate is already enforced pre-commit in ``_finalize_updated_task``
    # so the whole PATCH (task mutation + comment) commits atomically
    # or rejects atomically. No second gate call here.
    agent_id = (
        update.actor.agent.id
        if update.actor.actor_type == "agent" and update.actor.agent
        else None
    )
    event = ActivityEvent(
        event_type="task.comment",
        message=update.comment,
        task_id=update.task.id,
        board_id=update.task.board_id,
        agent_id=agent_id,
    )
    await _apply_classifier_to_comment_event(
        session,
        event=event,
        task=update.task,
        agent_id=agent_id,
        message=update.comment,
    )
    session.add(event)
    await session.commit()


async def _record_task_update_activity(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    event_type, message = _task_event_details(update.task, update.previous_status)
    actor_agent_id = (
        update.actor.agent.id if update.actor.actor_type == "agent" and update.actor.agent else None
    )
    # Record the task transition first, then reconcile dependents so any
    # cascaded dependency effects are logged after the source change.
    record_activity(
        session,
        event_type=event_type,
        task_id=update.task.id,
        message=message,
        agent_id=actor_agent_id,
        board_id=update.board_id,
    )
    await _record_parent_terminated_event_if_orphans(
        session,
        task=update.task,
        previous_status=update.previous_status,
        actor_agent_id=actor_agent_id,
    )
    await _reconcile_dependents_for_dependency_toggle(
        session,
        board_id=update.board_id,
        dependency_task=update.task,
        previous_status=update.previous_status,
        actor_agent_id=actor_agent_id,
    )
    await session.commit()


async def _assign_review_task_to_lead(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.task.status != "review" or update.previous_status == "review":
        return
    lead = (
        await Agent.objects.filter_by(board_id=update.board_id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None:
        return
    update.task.assigned_agent_id = lead.id


async def _require_worker_review_evidence_packet(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    if update.updates.get("status") != "review":
        return
    if not _actor_is_implementation_agent(update.actor):
        return

    review_comment_author = update.previous_assigned
    review_comment_since = (
        update.task.previous_in_progress_at
        if update.task.previous_in_progress_at is not None
        else update.previous_in_progress_at
    )
    is_rework_resubmission = update.task.rework_started_at is not None or (
        await _task_has_unresolved_rework_marker(
            session,
            task_id=update.task.id,
        )
    )
    if is_rework_resubmission and update.task.review_packet_type == "review_only":
        raise _review_evidence_packet_error(
            code="review_only_rework_requires_packet_type_change",
            message=(
                "Implementation agents cannot resubmit a `review_only` task from rework. "
                "The lead must convert `review_packet_type` to the implementation packet type "
                "or create a separate implementation task."
            ),
        )
    if is_rework_resubmission:
        if update.task.packet_commit_sha is None:
            raise _review_evidence_packet_error(
                code="rework_no_commit",
                message=(
                    "Cannot move rework to review without `packet_commit_sha`. "
                    "Set it to the fix commit SHA."
                ),
            )
        if not GIT_COMMIT_SHA_RE.fullmatch(update.task.packet_commit_sha):
            raise _review_evidence_packet_error(
                code="rework_invalid_commit_sha",
                message=(
                    "`packet_commit_sha` must be a Git commit SHA "
                    "(7 to 40 lowercase hexadecimal characters)."
                ),
            )
    if is_rework_resubmission and update.task.rework_entry_commit_sha is not None:
        if update.task.packet_commit_sha == update.task.rework_entry_commit_sha:
            raise _review_evidence_packet_error(
                code="rework_same_commit",
                message=(
                    f"`packet_commit_sha` ({update.task.packet_commit_sha}) is unchanged "
                    "since rework entry. Commit a fix before moving to review."
                ),
            )
    if update.task.review_packet_type not in REVIEW_EVIDENCE_REQUIRED_PACKET_TYPES:
        return
    required_pattern = (
        ACTIVE_BLOCKER_CLEARED_RE if is_rework_resubmission else FINAL_EVIDENCE_PACKET_RE
    )
    packet = update.comment if update.comment and required_pattern.match(update.comment) else None
    if packet is None:
        packet = await _latest_recent_task_comment_matching(
            session,
            task=update.task,
            agent_id=review_comment_author,
            since=review_comment_since,
            pattern=required_pattern,
        )
    if frontend_pipeline_required(update.task.review_packet_type):
        if is_rework_resubmission and packet is None:
            raise _review_evidence_packet_error(
                code="task_active_blocker_clearance_required",
                message=(
                    "Rework resubmission must include a parent-owned comment starting with "
                    "`Active blocker cleared:` and evidence that clears the reviewer blocker."
                ),
            )
        await require_frontend_pipeline_ready_for_review(
            session,
            task=update.task,
            since=review_comment_since,
        )
        return
    if packet is not None:
        return
    if is_rework_resubmission:
        raise _review_evidence_packet_error(
            code="task_active_blocker_clearance_required",
            message=(
                "Rework resubmission must include a parent-owned comment starting with "
                "`Active blocker cleared:` and evidence that clears the reviewer blocker."
            ),
        )
    raise _review_evidence_packet_error(
        code="task_final_evidence_packet_required",
        message=(
            "Moving this task to review requires a parent-owned comment starting with "
            "`FINAL_EVIDENCE_PACKET`; source-only or child-section evidence is not enough."
        ),
    )


async def _notify_task_update_assignment_changes(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> None:
    board: Board | None = None

    async def _board() -> Board | None:
        nonlocal board
        if board is None and update.task.board_id:
            board = await Board.objects.by_id(update.task.board_id).first(session)
        return board

    if (
        update.task.status == "inbox"
        and update.task.assigned_agent_id is None
        and (update.previous_status != "inbox" or update.previous_assigned is not None)
    ):
        current_board = await _board()
        if current_board:
            await _notify_lead_on_task_unassigned(
                session=session,
                board=current_board,
                task=update.task,
            )

    if not update.task.assigned_agent_id:
        return

    assigned_agent = await Agent.objects.by_id(update.task.assigned_agent_id).first(
        session,
    )
    if assigned_agent is None:
        return

    assignment_changed = update.task.assigned_agent_id != update.previous_assigned
    entered_in_progress = (
        update.task.status == "in_progress" and update.previous_status != "in_progress"
    )

    if entered_in_progress and not assignment_changed:
        current_board = await _board()
        if current_board:
            await _wake_agent_online_for_task(
                session=session,
                board=current_board,
                task=update.task,
                agent=assigned_agent,
                reason="status_in_progress",
            )

    if not assignment_changed:
        return

    if _is_lead_rework_return(update):
        current_board = await _board()
        if current_board:
            await _notify_agent_on_task_rework(
                session=session,
                board=current_board,
                task=update.task,
                agent=assigned_agent,
                lead=update.actor.agent,
            )
        return

    if (
        update.actor.actor_type == "agent"
        and update.actor.agent
        and update.task.assigned_agent_id == update.actor.agent.id
    ):
        return

    current_board = await _board()
    if current_board:
        await _notify_agent_on_task_assign(
            session=session,
            board=current_board,
            task=update.task,
            agent=assigned_agent,
            wake_assignee=True,
        )


async def _finalize_updated_task(
    session: AsyncSession,
    *,
    update: _TaskUpdateInput,
) -> TaskRead:
    # Phase V §I8: run the deploy-truth gate FIRST, before any ORM
    # mutation or autoflushing DB query. The /__build fetch blocks
    # for up to 5s; holding that wall-clock window inside an open
    # transaction would keep flushed row locks live through the
    # outbound HTTP call. Run the gate against a projected state that
    # reflects the PATCH's intended mutations without touching the
    # session.
    if {
        "status",
        "validation_target",
        "packet_commit_sha",
        "supports_build_metadata",
    }.intersection(update.updates):
        projected = _projected_task(update.task, update.updates)
        rollout_flags = await _resolve_rollout_flags(session, board_id=update.board_id)
        await _require_deploy_truth(
            projected,
            actor_agent_id=_comment_actor_id(update.actor),
            rollout_flags=rollout_flags,
        )

    # Phase VI §I6: the inline-comment path (PATCH with ``comment``)
    # commits the task mutation first and calls the gate in
    # ``_record_task_comment_from_update`` afterwards. If the gate
    # rejects the comment, the task mutation would already be
    # persisted while the caller sees a 403. Check the gate here,
    # pre-commit, so the whole PATCH either lands atomically or
    # rejects atomically.
    if (
        update.comment is not None
        and update.comment.strip()
    ):
        _validate_task_comment_format_for_actor(update.comment, update.actor)
        _require_rendered_live_pass_has_browser_evidence(update.comment, update.actor)
        if update.updates.get("status") != "rework":
            _require_comment_not_claim_unapplied_rework_routing(
                task=update.task,
                message=update.comment,
                actor=update.actor,
            )
        await _require_lane_quieting_allows_comment(
            session, task=update.task, actor=update.actor
        )
        await _require_echo_guard_allows_comment(
            session,
            task=update.task,
            actor=update.actor,
            message=update.comment,
        )

    for key, value in update.updates.items():
        setattr(update.task, key, value)
    if {
        "status",
        "assigned_agent_id",
        "operator_decision_required",
        "operator_decision_summary",
    }.intersection(update.updates):
        await _require_operator_decision_task_not_active(session, update.task)
    _require_commit_sha_for_review(update.task, update.updates)
    if {
        "status",
        "assigned_agent_id",
        "review_packet_type",
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    }.intersection(update.updates):
        # Phase IV §I2: ``assigned_agent_id`` is in the trigger set so
        # a PATCH that clears the owner on an already-``in_progress``
        # or ``done`` task re-validates and 409s. Without this, an
        # admin PATCH {"assigned_agent_id": null} would silently land
        # an ownerless active task.
        _require_delivery_contract_with_metric(
            task=update.task,
            actor_agent_id=_comment_actor_id(update.actor),
        )
    await _require_no_pending_approval_for_status_change_when_enabled(
        session,
        board_id=update.board_id,
        task_id=update.task.id,
        previous_status=update.previous_status,
        target_status=update.task.status,
        status_requested=update.status_requested,
    )
    await _require_review_before_done_when_enabled(
        session,
        board_id=update.board_id,
        previous_status=update.previous_status,
        target_status=update.task.status,
    )
    await _require_approved_linked_approval_for_done(
        session,
        board_id=update.board_id,
        task_id=update.task.id,
        previous_status=update.previous_status,
        target_status=update.task.status,
    )
    update.task.updated_at = utcnow()

    status_raw = update.updates.get("status")
    # Entering review can require a new comment or valid recent context when
    # the board-level rule is enabled.
    if status_raw == "review" and await _require_comment_for_review_when_enabled(
        session,
        board_id=update.board_id,
    ):
        comment_text = (update.comment or "").strip()
        review_comment_author = update.task.assigned_agent_id or update.previous_assigned
        review_comment_since = (
            update.task.previous_in_progress_at
            if update.task.previous_in_progress_at is not None
            else update.previous_in_progress_at
        )
        if not comment_text and not await has_valid_recent_comment(
            session,
            update.task,
            review_comment_author,
            review_comment_since,
        ):
            raise _comment_validation_error()
    await _require_worker_review_evidence_packet(session, update=update)
    if status_raw == "review" and _actor_is_implementation_agent(update.actor):
        update.task.rework_started_at = None
    await _assign_review_task_to_lead(session, update=update)

    if update.tag_ids is not None:
        normalized = (
            update.normalized_tag_ids
            if update.normalized_tag_ids is not None
            else await _normalized_update_tag_ids(
                session,
                update=update,
            )
        )
        await replace_tags(
            session,
            task_id=update.task.id,
            tag_ids=normalized or [],
        )

    if update.custom_field_values_set:
        await _set_task_custom_field_values_for_update(
            session,
            board_id=update.board_id,
            task_id=update.task.id,
            custom_field_values=update.custom_field_values,
        )

    session.add(update.task)
    await session.commit()
    await session.refresh(update.task)
    await _record_task_comment_from_update(session, update=update)
    await _record_task_update_activity(session, update=update)
    await _notify_task_update_assignment_changes(session, update=update)
    # Wake the lead immediately when a worker moves a task to review
    # or resubmits from rework, so the Supervisor doesn't wait for
    # the next heartbeat to start routing reviewers.
    if (
        update.task.status == "review"
        and update.previous_status in ("in_progress", "rework")
    ):
        await _notify_lead_on_end_work_event(
            session=session,
            task=update.task,
            reason=f"task moved from {update.previous_status} to review",
        )
    # Umbrella auto-cascade: closing the last child of a never-executed
    # parent retires the parent (and its grandparent, recursively).
    # Without this, retired-umbrella rows accumulate in inbox forever.
    if update.task.status in TERMINAL_STATUSES:
        cascaded_parent = await maybe_cascade_umbrella_close(
            session, task=update.task
        )
        if cascaded_parent is not None:
            await session.commit()

    return await _task_read_response(
        session,
        task=update.task,
        board_id=update.board_id,
    )


@router.post("/{task_id}/comments", response_model=TaskCommentRead)
async def create_task_comment(
    payload: TaskCommentCreate,
    task: Task = TASK_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> ActivityEvent:
    """Create a task comment and notify relevant agents."""
    await _validate_task_comment_access(session, task=task, actor=actor)
    _validate_task_comment_format_for_actor(payload.message, actor)
    _require_rendered_live_pass_has_browser_evidence(payload.message, actor)
    _require_comment_not_claim_unapplied_rework_routing(
        task=task,
        message=payload.message,
        actor=actor,
    )
    await _require_lane_quieting_allows_comment(
        session, task=task, actor=actor
    )
    await _require_echo_guard_allows_comment(
        session, task=task, actor=actor, message=payload.message
    )
    event = ActivityEvent(
        event_type="task.comment",
        message=payload.message,
        task_id=task.id,
        board_id=task.board_id,
        agent_id=_comment_actor_id(actor),
    )
    await _apply_classifier_to_comment_event(
        session,
        event=event,
        task=task,
        agent_id=_comment_actor_id(actor),
        message=payload.message,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    targets, mention_names = await _comment_targets(
        session,
        task=task,
        message=payload.message,
        actor=actor,
    )
    await _notify_task_comment_targets(
        session,
        request=_TaskCommentNotifyRequest(
            task=task,
            actor=actor,
            message=payload.message,
            targets=targets,
            mention_names=mention_names,
        ),
    )
    return event
