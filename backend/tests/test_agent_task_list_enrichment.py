# ruff: noqa: S101
"""Regression tests for agent task-list card enrichment."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.api.agent import _task_card_with_reason_codes
from app.schemas.view_models import TaskCardRead


def _task_card() -> TaskCardRead:
    now = datetime.now(timezone.utc)
    return TaskCardRead(
        id=uuid4(),
        board_id=uuid4(),
        created_by_user_id=None,
        title="Task",
        description=None,
        status="inbox",
        priority="medium",
        due_at=None,
        assigned_agent_id=None,
        review_packet_type=None,
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        packet_commit_sha=None,
        packet_build_sha=None,
        supports_build_metadata=None,
        operator_decision_required=False,
        operator_decision_summary=None,
        depends_on_task_ids=[],
        tag_ids=[],
        parent_task_id=None,
        in_progress_at=None,
        previous_in_progress_at=None,
        rework_started_at=None,
        rework_entry_commit_sha=None,
        source_memory_id=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
        blocked_by_task_ids=[],
        is_blocked=False,
        tags=[],
        custom_field_values={},
        orphan_child_task_ids=[],
        open_blocker_reason_codes=["stale_blocker"],
        pending_operator_decision_reason_codes=["stale_decision"],
    )


def test_task_card_enrichment_replaces_existing_reason_code_fields() -> None:
    card = _task_card()

    enriched = _task_card_with_reason_codes(
        card,
        open_blocker_reason_codes=["runtime_unavailable"],
        pending_operator_decision_reason_codes=["needs_operator_choice"],
    )

    assert enriched.open_blocker_reason_codes == ["runtime_unavailable"]
    assert enriched.pending_operator_decision_reason_codes == ["needs_operator_choice"]
