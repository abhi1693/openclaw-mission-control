# ruff: noqa: INP001
"""Regression tests for structured review verdict readiness."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.time import utcnow
from app.models.task_review_events import TaskReviewEvent
from app.models.tasks import Task
from app.services.task_review_events import build_review_readiness


def _task(*, review_packet_type: str = "frontend_ui") -> Task:
    return Task(
        id=uuid4(),
        board_id=uuid4(),
        title="Task under review",
        status="review",
        review_packet_type=review_packet_type,
        in_progress_at=utcnow(),
    )


def _event(
    task: Task,
    *,
    reviewer_role: str,
    verdict: str,
    minutes_after_cycle: int = 1,
    evidence: dict[str, object] | None = None,
    evidence_type: str | None = None,
    target: str | None = None,
    build_hash: str | None = None,
) -> TaskReviewEvent:
    assert task.board_id is not None
    assert task.in_progress_at is not None
    return TaskReviewEvent(
        board_id=task.board_id,
        task_id=task.id,
        agent_id=uuid4(),
        reviewer_role=reviewer_role,
        verdict=verdict,
        evidence_type=evidence_type
        if evidence_type is not None
        else "browser"
        if reviewer_role == "qa_e2e"
        else "review",
        target=target,
        build_hash=build_hash,
        evidence=evidence,
        created_at=task.in_progress_at + timedelta(minutes=minutes_after_cycle),
    )


def _qa_e2e_pass_evidence() -> dict[str, object]:
    return {
        "ac_rows": [
            {
                "ac": "Navigation top state stays visible on the live target",
                "category": "browser",
                "result": "pass",
                "evidence": "Playwright observed active nav state after route change.",
            },
        ],
        "browser_matrix": [
            {
                "route": "/dashboard",
                "viewport": "375x812",
                "locale": "en-US",
                "role": "authenticated-user",
                "console_errors": 0,
                "network_failures": 0,
                "result": "pass",
            },
        ],
    }


def _required_pass_events(task: Task) -> list[TaskReviewEvent]:
    return [
        _event(task, reviewer_role="architect", verdict="pass"),
        _event(task, reviewer_role="qa_unit", verdict="pass"),
        _event(
            task,
            reviewer_role="qa_e2e",
            verdict="pass",
            target="http://127.0.0.1:3002",
            build_hash="index-abc123.js",
            evidence=_qa_e2e_pass_evidence(),
        ),
        _event(task, reviewer_role="devops", verdict="pass"),
    ]


def test_frontend_review_readiness_requires_architect_and_qa_e2e_pass() -> None:
    task = _task(review_packet_type="frontend_ui")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=_qa_e2e_pass_evidence(),
            ),
        ],
    )

    assert readiness.ready is True
    assert readiness.required_roles == ["architect", "qa_e2e"]
    assert readiness.missing_roles == []
    assert readiness.blocking_roles == []
    assert readiness.artifact_issues == []


def test_frontend_review_readiness_rejects_qa_e2e_pass_without_structured_evidence() -> None:
    task = _task(review_packet_type="frontend_ui")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(task, reviewer_role="qa_e2e", verdict="pass"),
        ],
    )

    assert readiness.ready is False
    assert readiness.missing_roles == []
    assert readiness.blocking_roles == []
    assert readiness.artifact_issues == [
        "qa_e2e_pass_missing_target",
        "qa_e2e_pass_missing_build_hash",
        "qa_e2e_pass_missing_ac_rows",
        "qa_e2e_pass_missing_browser_matrix",
    ]


def test_frontend_review_readiness_rejects_qa_e2e_pass_with_failed_matrix_row() -> None:
    task = _task(review_packet_type="frontend_ui")
    evidence = _qa_e2e_pass_evidence()
    browser_matrix = evidence["browser_matrix"]
    assert isinstance(browser_matrix, list)
    browser_matrix[0] = {
        **browser_matrix[0],
        "console_errors": 1,
        "result": "pass",
    }
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=evidence,
            ),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == ["qa_e2e_pass_browser_matrix_has_failures"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("console_errors", False),
        ("network_failures", False),
        ("console_errors", "0"),
        ("network_failures", "0"),
        ("console_errors", 1),
        ("network_failures", 1),
    ],
)
def test_frontend_review_readiness_rejects_malformed_browser_matrix_counts(
    field: str,
    value: object,
) -> None:
    task = _task(review_packet_type="frontend_ui")
    evidence = _qa_e2e_pass_evidence()
    browser_matrix = evidence["browser_matrix"]
    assert isinstance(browser_matrix, list)
    browser_matrix[0] = {**browser_matrix[0], field: value}

    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=evidence,
            ),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == ["qa_e2e_pass_browser_matrix_has_failures"]


@pytest.mark.parametrize("missing_field", ["route", "viewport"])
def test_frontend_review_readiness_rejects_browser_matrix_missing_required_text(
    missing_field: str,
) -> None:
    task = _task(review_packet_type="frontend_ui")
    evidence = _qa_e2e_pass_evidence()
    browser_matrix = evidence["browser_matrix"]
    assert isinstance(browser_matrix, list)
    browser_matrix[0] = {**browser_matrix[0], missing_field: " "}

    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=evidence,
            ),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == ["qa_e2e_pass_browser_matrix_has_failures"]


def test_frontend_review_readiness_rejects_wrong_qa_e2e_evidence_type() -> None:
    task = _task(review_packet_type="frontend_ui")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                evidence_type="runtime",
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=_qa_e2e_pass_evidence(),
            ),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == ["qa_e2e_pass_wrong_evidence_type"]


def test_frontend_review_readiness_rejects_failing_ac_row() -> None:
    task = _task(review_packet_type="frontend_ui")
    evidence = _qa_e2e_pass_evidence()
    ac_rows = evidence["ac_rows"]
    assert isinstance(ac_rows, list)
    ac_rows[0] = {**ac_rows[0], "result": "fail"}

    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=evidence,
            ),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == ["qa_e2e_pass_ac_rows_have_failures"]


def test_mixed_review_readiness_requires_valid_qa_e2e_matrix() -> None:
    task = _task(review_packet_type="mixed")
    readiness = build_review_readiness(
        task=task,
        events=_required_pass_events(task),
    )

    assert readiness.ready is True
    assert readiness.required_roles == ["architect", "qa_unit", "qa_e2e", "devops"]
    assert readiness.artifact_issues == []

    thin_events = deepcopy(_required_pass_events(task))
    for idx, event in enumerate(thin_events):
        if event.reviewer_role == "qa_e2e":
            thin_events[idx] = _event(task, reviewer_role="qa_e2e", verdict="pass")
            break

    thin_readiness = build_review_readiness(task=task, events=thin_events)

    assert thin_readiness.ready is False
    assert thin_readiness.artifact_issues == [
        "qa_e2e_pass_missing_target",
        "qa_e2e_pass_missing_build_hash",
        "qa_e2e_pass_missing_ac_rows",
        "qa_e2e_pass_missing_browser_matrix",
    ]


def test_frontend_review_readiness_uses_latest_qa_e2e_event_for_matrix() -> None:
    task = _task(review_packet_type="frontend_ui")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(task, reviewer_role="qa_e2e", verdict="pass", minutes_after_cycle=1),
            _event(
                task,
                reviewer_role="qa_e2e",
                verdict="pass",
                minutes_after_cycle=2,
                target="http://127.0.0.1:3002",
                build_hash="index-abc123.js",
                evidence=_qa_e2e_pass_evidence(),
            ),
        ],
    )

    assert readiness.ready is True
    assert readiness.artifact_issues == []


def test_latest_fail_blocks_even_when_required_roles_exist() -> None:
    task = _task(review_packet_type="backend_api")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
            _event(task, reviewer_role="qa_unit", verdict="pass"),
            _event(task, reviewer_role="qa_unit", verdict="fail", minutes_after_cycle=2),
        ],
    )

    assert readiness.ready is False
    assert readiness.missing_roles == []
    assert readiness.blocking_roles == ["qa_unit"]


def test_stale_verdict_before_current_cycle_does_not_count() -> None:
    task = _task(review_packet_type="infra_ops")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="devops", verdict="pass", minutes_after_cycle=-1),
        ],
    )

    assert readiness.ready is False
    assert readiness.required_roles == ["devops"]
    assert readiness.missing_roles == ["devops"]


def test_review_only_architect_pass_requires_child_task_evidence() -> None:
    task = _task(review_packet_type="review_only")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(task, reviewer_role="architect", verdict="pass"),
        ],
    )

    assert readiness.ready is False
    assert readiness.artifact_issues == [
        "review_only_architect_pass_missing_child_task_evidence"
    ]


def test_review_only_architect_pass_accepts_declared_child_task_ids() -> None:
    task = _task(review_packet_type="review_only")
    child_task_id = uuid4()
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(
                task,
                reviewer_role="architect",
                verdict="pass",
                evidence={"planned_child_task_ids": [str(child_task_id)]},
            ),
        ],
        board_task_ids={task.id, child_task_id},
    )

    assert readiness.ready is True
    assert readiness.declared_child_task_ids == [child_task_id]
    assert readiness.artifact_issues == []


def test_review_only_architect_pass_blocks_missing_declared_child_task_ids() -> None:
    task = _task(review_packet_type="review_only")
    child_task_id = uuid4()
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(
                task,
                reviewer_role="architect",
                verdict="pass",
                evidence={"planned_child_task_ids": [str(child_task_id)]},
            ),
        ],
        board_task_ids={task.id},
    )

    assert readiness.ready is False
    assert readiness.declared_child_task_ids == [child_task_id]
    assert readiness.missing_child_task_ids == [child_task_id]
    assert readiness.artifact_issues == [
        "review_only_architect_pass_child_tasks_not_found"
    ]


def test_review_only_architect_pass_accepts_explicit_no_child_tasks_required() -> None:
    task = _task(review_packet_type="review_only")
    readiness = build_review_readiness(
        task=task,
        events=[
            _event(
                task,
                reviewer_role="architect",
                verdict="pass",
                evidence={"no_child_tasks_required": True},
            ),
        ],
    )

    assert readiness.ready is True
    assert readiness.artifact_issues == []
