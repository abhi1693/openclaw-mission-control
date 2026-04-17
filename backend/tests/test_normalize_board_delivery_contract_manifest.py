from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.tasks import TaskUpdate
from scripts.normalize_board_delivery_contract import (
    BoardDeliveryContractManifest,
    NormalizationTaskPatch,
    render_dry_run_lines,
    summarize_patch,
)


def test_normalization_patch_requires_non_comment_updates() -> None:
    with pytest.raises(ValidationError, match="at least one non-comment task field"):
        NormalizationTaskPatch(
            task_id=uuid4(),
            update=TaskUpdate(comment="normalize this task"),
        )


def test_normalization_patch_summary_lists_changed_fields() -> None:
    patch = NormalizationTaskPatch(
        task_id=uuid4(),
        title="Track A.1",
        update=TaskUpdate(
            review_packet_type="frontend_ui",
            validation_target="http://192.168.2.60:3000",
            validation_target_kind="live_url",
            validation_target_scope="runtime",
            comment="Attach live review contract.",
        ),
    )

    summary = summarize_patch(patch)

    assert "Track A.1" in summary
    assert "review_packet_type" in summary
    assert "validation_target" in summary
    assert "comment" not in summary


def test_manifest_requires_tasks() -> None:
    with pytest.raises(ValidationError, match="at least one task patch"):
        BoardDeliveryContractManifest(
            board_id=uuid4(),
            tasks=[],
        )


def test_render_dry_run_lines_emits_all_patch_summaries() -> None:
    manifest = BoardDeliveryContractManifest(
        board_id=uuid4(),
        tasks=[
            NormalizationTaskPatch(
                task_id=uuid4(),
                title="Track B",
                update=TaskUpdate(
                    status="inbox",
                    operator_decision_required=True,
                    operator_decision_summary="Awaiting operator input.",
                ),
            ),
            NormalizationTaskPatch(
                task_id=uuid4(),
                title="Track E",
                update=TaskUpdate(
                    review_packet_type="mixed",
                    validation_target="http://192.168.2.64:3000",
                    validation_target_kind="live_url",
                    validation_target_scope="all",
                ),
            ),
        ],
    )

    lines = render_dry_run_lines(manifest)

    assert lines == [
        "DRY RUN Track B: operator_decision_required, operator_decision_summary, status",
        "DRY RUN Track E: review_packet_type, validation_target, validation_target_kind, validation_target_scope",
    ]
