"""Mission Control approval gate → GitHub required check.

This module maintains a GitHub Check Run (recommended) named:
- `mission-control/approval`

The check is intended to be added to GitHub ruleset required checks so PRs
cannot merge unless the corresponding Mission Control task has an approved
in-app approval.

Mapping:
- PR → Task: by `custom_field_values.github_pr_url` exact match.
- Task → Approval: any linked Approval rows with status in {pending, approved, rejected}.

Triggers (implemented via API hooks):
- approval created / resolved
- task github_pr_url updated

A periodic reconciliation job should call the sync functions as a safety net.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_maker
from app.models.approval_task_links import ApprovalTaskLink
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.task_custom_fields import TaskCustomFieldDefinition, TaskCustomFieldValue
from app.models.tasks import Task
from app.services.github.client import (
    GitHubClientError,
    get_pull_request_head_sha,
    parse_pull_request_url,
    upsert_check_run,
)

if False:  # pragma: no cover
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)

CHECK_NAME = "mission-control/approval"

# Default action types that qualify as a "merge gate" approval.
# (Action types are free-form today; keep this conservative but configurable later.)
REQUIRED_ACTION_TYPES = {"mark_done", "mark_task_done"}


CheckOutcome = Literal["success", "pending", "rejected", "missing", "error", "multiple"]


@dataclass(frozen=True)
class ApprovalGateEvaluation:
    outcome: CheckOutcome
    task_ids: tuple[UUID, ...] = ()
    summary: str = ""


async def _board_org_id(session: AsyncSession, *, board_id: UUID) -> UUID | None:
    return (
        await session.exec(
            select(col(Board.organization_id)).where(col(Board.id) == board_id),
        )
    ).first()


async def _tasks_for_pr_url(
    session: AsyncSession,
    *,
    board_id: UUID,
    pr_url: str,
) -> list[Task]:
    org_id = await _board_org_id(session, board_id=board_id)
    if org_id is None:
        return []

    statement = (
        select(Task)
        .join(TaskCustomFieldValue, col(TaskCustomFieldValue.task_id) == col(Task.id))
        .join(
            TaskCustomFieldDefinition,
            col(TaskCustomFieldDefinition.id)
            == col(TaskCustomFieldValue.task_custom_field_definition_id),
        )
        .where(col(Task.board_id) == board_id)
        .where(col(TaskCustomFieldDefinition.organization_id) == org_id)
        .where(col(TaskCustomFieldDefinition.field_key) == "github_pr_url")
        .where(col(TaskCustomFieldValue.value) == pr_url)
        .order_by(col(Task.created_at).asc())
    )
    rows = list(await session.exec(statement))
    return [row for row in rows if isinstance(row, Task)]


async def _approval_rows_for_task(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_id: UUID,
) -> list[Approval]:
    # Linked approvals (new style)
    linked_stmt = (
        select(Approval)
        .join(ApprovalTaskLink, col(ApprovalTaskLink.approval_id) == col(Approval.id))
        .where(col(Approval.board_id) == board_id)
        .where(col(ApprovalTaskLink.task_id) == task_id)
        .order_by(col(Approval.created_at).asc())
    )
    linked = list(await session.exec(linked_stmt))

    # Legacy approvals (Approval.task_id) not linked via ApprovalTaskLink
    legacy_stmt = (
        select(Approval)
        .where(col(Approval.board_id) == board_id)
        .where(col(Approval.task_id) == task_id)
        .order_by(col(Approval.created_at).asc())
    )
    legacy = list(await session.exec(legacy_stmt))

    # Merge unique by id
    by_id: dict[UUID, Approval] = {}
    for approval in [*linked, *legacy]:
        if isinstance(approval, Approval):
            by_id.setdefault(approval.id, approval)
    return list(by_id.values())


def _qualifies_for_gate(approval: Approval) -> bool:
    # If action types evolve, we can broaden this; for now keep it anchored.
    return approval.action_type in REQUIRED_ACTION_TYPES


async def evaluate_approval_gate_for_pr_url(
    session: AsyncSession,
    *,
    board_id: UUID,
    pr_url: str,
) -> ApprovalGateEvaluation:
    tasks = await _tasks_for_pr_url(session, board_id=board_id, pr_url=pr_url)
    if not tasks:
        return ApprovalGateEvaluation(
            outcome="missing",
            task_ids=(),
            summary=(
                "No Mission Control task is linked to this PR. Set the task custom field "
                "`github_pr_url` to this PR URL."
            ),
        )
    if len(tasks) > 1:
        return ApprovalGateEvaluation(
            outcome="multiple",
            task_ids=tuple(task.id for task in tasks),
            summary=(
                "Multiple Mission Control tasks are linked to this PR URL. "
                "Ensure exactly one task has `github_pr_url` set to this PR."
            ),
        )

    task = tasks[0]
    approvals = await _approval_rows_for_task(session, board_id=board_id, task_id=task.id)
    gate_approvals = [a for a in approvals if _qualifies_for_gate(a)]

    if not gate_approvals:
        return ApprovalGateEvaluation(
            outcome="missing",
            task_ids=(task.id,),
            summary=(
                "No qualifying approval found for this task. Create an approval request "
                f"(action_type in {sorted(REQUIRED_ACTION_TYPES)})."
            ),
        )

    statuses = [str(a.status) for a in gate_approvals]
    if any(s == "approved" for s in statuses):
        return ApprovalGateEvaluation(
            outcome="success",
            task_ids=(task.id,),
            summary="Approval is approved. Merge is permitted.",
        )
    if any(s == "rejected" for s in statuses):
        return ApprovalGateEvaluation(
            outcome="rejected",
            task_ids=(task.id,),
            summary="Approval was rejected. Merge is blocked until a new approval is granted.",
        )
    if any(s == "pending" for s in statuses):
        return ApprovalGateEvaluation(
            outcome="pending",
            task_ids=(task.id,),
            summary="Approval is pending. Merge is blocked until approved.",
        )

    return ApprovalGateEvaluation(
        outcome="error",
        task_ids=(task.id,),
        summary=f"Unexpected approval statuses: {sorted(set(statuses))}",
    )


async def sync_github_approval_check_for_pr_url(
    session: AsyncSession,
    *,
    board_id: UUID,
    pr_url: str,
) -> None:
    """Upsert the GitHub check run for a PR URL based on Mission Control approval state."""

    parsed = parse_pull_request_url(pr_url)
    if parsed is None:
        logger.warning(
            "github.approval_check.invalid_pr_url",
            extra={"board_id": str(board_id), "pr_url": pr_url},
        )
        return

    try:
        evaluation = await evaluate_approval_gate_for_pr_url(
            session,
            board_id=board_id,
            pr_url=pr_url,
        )

        head_sha = await get_pull_request_head_sha(parsed)

        title = "Mission Control approval gate"
        summary_lines = [
            f"PR: {parsed.url}",
            f"Board: {board_id}",
        ]
        if evaluation.task_ids:
            summary_lines.append("Task(s): " + ", ".join(str(tid) for tid in evaluation.task_ids))
        summary_lines.append("")
        summary_lines.append(evaluation.summary)

        if evaluation.outcome == "success":
            await upsert_check_run(
                owner=parsed.owner,
                repo=parsed.repo,
                head_sha=head_sha,
                check_name=CHECK_NAME,
                status="completed",
                conclusion="success",
                title=title,
                summary="\n".join(summary_lines),
            )
            return

        if evaluation.outcome == "pending":
            # Keep as in_progress to clearly signal it's waiting.
            await upsert_check_run(
                owner=parsed.owner,
                repo=parsed.repo,
                head_sha=head_sha,
                check_name=CHECK_NAME,
                status="in_progress",
                conclusion=None,
                title=title,
                summary="\n".join(summary_lines),
            )
            return

        # failure-like outcomes
        await upsert_check_run(
            owner=parsed.owner,
            repo=parsed.repo,
            head_sha=head_sha,
            check_name=CHECK_NAME,
            status="completed",
            conclusion="failure",
            title=title,
            summary="\n".join(summary_lines),
        )

    except GitHubClientError as exc:
        logger.warning(
            "github.approval_check.github_error",
            extra={"board_id": str(board_id), "pr_url": pr_url, "error": str(exc)},
        )
    except Exception as exc:
        logger.exception(
            "github.approval_check.unexpected",
            extra={"board_id": str(board_id), "pr_url": pr_url, "error": str(exc)},
        )


async def sync_github_approval_check_for_task_ids(
    session: AsyncSession,
    *,
    board_id: UUID,
    task_ids: list[UUID],
) -> None:
    """Sync approval checks for any tasks that have github_pr_url set.

    Used by approval hooks (one approval can link multiple tasks).
    """

    if not task_ids:
        return

    # Load custom-field values for these tasks and find github_pr_url.
    # We reuse the same join approach but filter by task ids.
    org_id = await _board_org_id(session, board_id=board_id)
    if org_id is None:
        return

    stmt = (
        select(col(TaskCustomFieldValue.task_id), col(TaskCustomFieldValue.value))
        .join(
            TaskCustomFieldDefinition,
            col(TaskCustomFieldDefinition.id)
            == col(TaskCustomFieldValue.task_custom_field_definition_id),
        )
        .where(col(TaskCustomFieldDefinition.organization_id) == org_id)
        .where(col(TaskCustomFieldDefinition.field_key) == "github_pr_url")
        .where(col(TaskCustomFieldValue.task_id).in_(task_ids))
    )
    rows = list(await session.exec(stmt))

    pr_urls: set[str] = set()
    for _task_id, value in rows:
        if isinstance(value, str) and value.strip():
            pr_urls.add(value.strip())

    for pr_url in sorted(pr_urls):
        await sync_github_approval_check_for_pr_url(session, board_id=board_id, pr_url=pr_url)


async def reconcile_github_approval_checks_for_board(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> int:
    """Periodic reconciliation safety net.

    Returns number of distinct PR URLs processed.

    Intended to be run by a cron/worker periodically.
    """

    org_id = await _board_org_id(session, board_id=board_id)
    if org_id is None:
        return 0

    stmt = (
        select(col(TaskCustomFieldValue.value))
        .join(
            TaskCustomFieldDefinition,
            col(TaskCustomFieldDefinition.id)
            == col(TaskCustomFieldValue.task_custom_field_definition_id),
        )
        .join(Task, col(Task.id) == col(TaskCustomFieldValue.task_id))
        .where(col(Task.board_id) == board_id)
        .where(col(TaskCustomFieldDefinition.organization_id) == org_id)
        .where(col(TaskCustomFieldDefinition.field_key) == "github_pr_url")
    )
    rows = list(await session.exec(stmt))

    pr_urls: set[str] = set()
    for (value,) in rows:
        if isinstance(value, str) and value.strip():
            pr_urls.add(value.strip())

    for pr_url in sorted(pr_urls):
        await sync_github_approval_check_for_pr_url(session, board_id=board_id, pr_url=pr_url)

    return len(pr_urls)


async def reconcile_mission_control_approval_checks_for_all_boards() -> int:
    """Reconcile approval checks for every board.

    Returns total number of distinct PR URLs processed across boards.

    This is intentionally a safety net: the primary, low-latency updates happen on
    approval create/resolution and task github_pr_url updates.
    """

    async with async_session_maker() as session:
        board_ids = list(
            await session.exec(
                select(col(Board.id)).order_by(col(Board.created_at).asc()),
            ),
        )
        processed = 0
        for board_id in board_ids:
            try:
                processed += await reconcile_github_approval_checks_for_board(
                    session,
                    board_id=board_id,
                )
            except Exception:
                logger.exception(
                    "github.approval_check.reconcile.board_failed",
                    extra={"board_id": str(board_id)},
                )
        return processed


def github_approval_check_enabled() -> bool:
    return bool((settings.github_token or "").strip())
