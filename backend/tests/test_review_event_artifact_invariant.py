# ruff: noqa: INP001
"""POST /review-events must reject Architect PASS for review_only packets
that lack child-task evidence — write-time enforcement of the
``planned_child_task_ids`` / ``no_child_tasks_required:true`` rule from
``architect-review-verdict/SKILL.md``.

Production gap 2026-05-03 on QA gate 5b7abdd2: Architect (still on the
old skill content) posted a structured PASS without child_task evidence.
The structured event committed cleanly; review-readiness reported
``ready=false`` with ``artifact_issues=[review_only_architect_pass_missing_child_task_evidence]``;
Supervisor REACTIVELY filed a Blocker. Reactive blockers in agent prose
are exactly the layer the architectural critique earlier today flagged
as wrong — invariants belong at the write boundary.

The fix: reject the POST itself with 422 + ``code=review_only_pass_requires_child_task_evidence``
when (reviewer_role=architect, verdict=pass, task.review_packet_type=review_only)
and the evidence dict has neither ``planned_child_task_ids`` (non-empty)
nor ``no_child_tasks_required:true``.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.tasks as tasks_api
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.task_review_events import TaskReviewEventCreate


@dataclass
class _ActorStub:
    agent: Agent | None
    actor_type: str = "agent"
    user: object | None = None


async def _seed_review_only_task(
    session: AsyncSession,
    *,
    board_slug: str,
    review_packet_type: str = "review_only",
) -> tuple[Board, Agent, Task]:
    """Seed an org/gateway/board + Architect agent + a review-status
    task with the given review_packet_type."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    architect_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name=f"org-{board_slug}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name=f"gw-{board_slug}",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name=board_slug,
        slug=board_slug,
    )
    session.add(board)
    architect = Agent(
        id=architect_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id=f"agent:{board_slug}:architect",
        identity_profile={"dev_acp_flow": "review_only"},
    )
    session.add(architect)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{board_slug}",
        status="review",
        review_packet_type=review_packet_type,
        assigned_agent_id=architect_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, architect, task


@pytest.mark.asyncio
async def test_review_only_architect_pass_without_child_task_evidence_rejects(
    sqlite_session: AsyncSession,
) -> None:
    """Architect PASS on a review_only packet without
    ``planned_child_task_ids`` or ``no_child_tasks_required:true``
    must be rejected at write time with 422."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-pass-no-evidence",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={"comment": "PASS without child_task evidence"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=architect),
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "review_only_pass_requires_child_task_evidence"
    assert "planned_child_task_ids" in str(detail.get("message", ""))


@pytest.mark.asyncio
async def test_review_only_architect_pass_with_no_child_tasks_required_succeeds(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: explicit ``no_child_tasks_required:true`` in the
    evidence dict satisfies the rule (intentionally non-decomposed)."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-explicit-no-children",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={
            "comment": "PASS — single-AC scope, no decomposition needed",
            "no_child_tasks_required": True,
        },
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=architect,
        message="@Supervisor lead approve and move to done\nLead wake: structured-review-verdict review event",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=architect),
    )
    assert read.verdict == "pass"
    assert read.reviewer_role == "architect"


@pytest.mark.asyncio
async def test_review_only_architect_pass_with_planned_child_task_ids_succeeds(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: ``planned_child_task_ids`` (non-empty list)
    satisfies the rule."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-with-children",
    )
    child_id = uuid4()
    sqlite_session.add(
        Task(
            id=child_id,
            board_id=board.id,
            title="subtask",
            status="inbox",
            parent_task_id=task.id,
        ),
    )
    await sqlite_session.commit()

    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={
            "comment": "PASS — decomposition into 1 child task",
            "planned_child_task_ids": [str(child_id)],
        },
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=architect,
        message="@Supervisor lead approve and move to done\nLead wake: structured-review-verdict review event",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=architect),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_review_only_architect_fail_does_not_require_child_task_evidence(
    sqlite_session: AsyncSession,
) -> None:
    """FAIL verdicts don't need child_task evidence — the rule is
    PASS-specific (only applies to the ``ready`` decision the
    review-readiness gate makes for done transitions)."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-fail-no-evidence",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="fail",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={"comment": "FAIL: missing field X"},
        blocking_owner="PF",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=architect),
    )
    assert read.verdict == "fail"


@pytest.mark.asyncio
async def test_frontend_ui_packet_pass_does_not_trigger_invariant(
    sqlite_session: AsyncSession,
) -> None:
    """The rule is review_only-specific. ``frontend_ui`` packets keep
    the existing gate logic — Architect PASS without child_task
    evidence is fine because the packet has its own browser/source
    artifacts."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="frontend-ui-pass",
        review_packet_type="frontend_ui",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={"comment": "PASS on frontend_ui packet"},
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=architect,
        message="@Supervisor lead approve and move to done\nLead wake: structured-review-verdict review event",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=architect),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_review_only_qa_pass_does_not_trigger_invariant(
    sqlite_session: AsyncSession,
) -> None:
    """The rule applies only to ``architect`` reviewer_role for
    review_only packets. QA roles have their own evidence requirements
    that aren't gated by child_task_ids."""
    board, _, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-qa-pass",
    )
    qa_id = uuid4()
    qa = Agent(
        id=qa_id,
        board_id=board.id,
        gateway_id=board.gateway_id,
        name="QA-E2E",
        openclaw_session_id="agent:qa:main",
        identity_profile={"validation_flow": "qa_validation"},
    )
    sqlite_session.add(qa)
    await sqlite_session.commit()
    await sqlite_session.refresh(qa)

    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        evidence={"comment": "QA PASS on review_only packet"},
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=qa),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_review_only_architect_pass_with_invalid_uuid_in_planned_ids_rejects(
    sqlite_session: AsyncSession,
) -> None:
    """A non-UUID string inside ``planned_child_task_ids`` collapses
    to "no usable IDs" — read-side returns
    ``review_only_architect_pass_missing_child_task_evidence`` for
    this case (``_coerce_uuid_list`` returns None on parse failure).
    Write-side must reject before commit so the bad payload never
    reaches the readiness gate."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-bad-uuid",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={
            "comment": "PASS with malformed child id",
            "planned_child_task_ids": ["not-a-uuid"],
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=architect),
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "review_only_pass_requires_child_task_evidence"


@pytest.mark.asyncio
async def test_review_only_architect_pass_with_parent_id_as_child_rejects(
    sqlite_session: AsyncSession,
) -> None:
    """The parent task can't be its own decomposition target. Read-side
    yields ``review_only_architect_pass_includes_parent_task_id``;
    write-side must 422 with the matching code."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-parent-self",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={
            "comment": "PASS but listed self as child",
            "planned_child_task_ids": [str(task.id)],
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=architect),
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "review_only_pass_includes_parent_task_id"


@pytest.mark.asyncio
async def test_review_only_architect_pass_with_cross_board_child_rejects(
    sqlite_session: AsyncSession,
) -> None:
    """Declared child task IDs that don't exist on the parent's board
    fail the read-side membership check; write-side must reject so the
    parent task doesn't end up referencing children that resolution
    can't traverse to."""
    board, architect, task = await _seed_review_only_task(
        sqlite_session,
        board_slug="review-only-cross-board-child",
    )
    other_board_id = uuid4()
    other_board = Board(
        id=other_board_id,
        organization_id=board.organization_id,
        gateway_id=board.gateway_id,
        name="other-board",
        slug="other-board",
    )
    sqlite_session.add(other_board)
    foreign_child = uuid4()
    sqlite_session.add(
        Task(
            id=foreign_child,
            board_id=other_board_id,
            title="foreign",
            status="inbox",
        ),
    )
    await sqlite_session.commit()

    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        evidence={
            "comment": "PASS but child belongs to different board",
            "planned_child_task_ids": [str(foreign_child)],
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=architect),
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "review_only_pass_child_tasks_not_found"


async def _seed_frontend_ui_qa_task(
    session: AsyncSession,
    *,
    board_slug: str,
) -> tuple[Board, Agent, Task]:
    """Seed a frontend_ui packet (which requires architect + qa_e2e)
    with an assigned QA-E2E agent so the write path passes the
    pipeline-write-access check."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    qa_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name=f"org-{board_slug}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name=f"gw-{board_slug}",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name=board_slug,
        slug=board_slug,
    )
    session.add(board)
    qa = Agent(
        id=qa_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="QA-E2E",
        openclaw_session_id=f"agent:{board_slug}:qa",
        identity_profile={"validation_flow": "qa_validation"},
    )
    session.add(qa)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{board_slug}",
        status="review",
        review_packet_type="frontend_ui",
        assigned_agent_id=qa_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, qa, task


def _full_qa_e2e_pass_evidence() -> dict:
    """A maximal evidence dict that satisfies every QA-E2E PASS rule
    in ``_qa_e2e_pass_artifact_issues`` — used as the positive control
    and as a base each negative test mutates one field of."""
    return {
        "comment": "All ACs verified",
        "ac_rows": [{"ac": "AC1", "result": "pass"}],
        "browser_matrix": [
            {
                "route": "/",
                "viewport": "375x812",
                "result": "pass",
                "console_errors": 0,
                "network_failures": 0,
            },
        ],
    }


@pytest.mark.asyncio
async def test_qa_e2e_pass_full_evidence_succeeds(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: a complete QA-E2E PASS evidence packet on a
    frontend_ui task is accepted at write time."""
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-full",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        build_hash="sha256-abc",
        evidence=_full_qa_e2e_pass_evidence(),
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=qa,
        message="@Supervisor lead approve and move to done\nLead wake: structured-review-verdict review event",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=qa),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_qa_e2e_pass_wrong_evidence_type_rejects(
    sqlite_session: AsyncSession,
) -> None:
    """The read-side requires ``evidence_type='browser'`` for QA-E2E
    PASS. Anything else (including ``source_review``) must reject at
    write time."""
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-wrong-type",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="source_review",
        target="http://192.168.2.63:3002/product",
        build_hash="sha256-abc",
        evidence=_full_qa_e2e_pass_evidence(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "qa_e2e_pass_invalid_evidence"
    assert "qa_e2e_pass_wrong_evidence_type" in str(detail.get("issues", []))


@pytest.mark.asyncio
async def test_qa_e2e_pass_missing_target_rejects(
    sqlite_session: AsyncSession,
) -> None:
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-no-target",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target=None,
        build_hash="sha256-abc",
        evidence=_full_qa_e2e_pass_evidence(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    assert "qa_e2e_pass_missing_target" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_qa_e2e_pass_missing_build_hash_rejects(
    sqlite_session: AsyncSession,
) -> None:
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-no-hash",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        build_hash=None,
        evidence=_full_qa_e2e_pass_evidence(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    assert "qa_e2e_pass_missing_build_hash" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_qa_e2e_pass_missing_ac_rows_rejects(
    sqlite_session: AsyncSession,
) -> None:
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-no-ac-rows",
    )
    evidence = _full_qa_e2e_pass_evidence()
    del evidence["ac_rows"]
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        build_hash="sha256-abc",
        evidence=evidence,
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    assert "qa_e2e_pass_missing_ac_rows" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_qa_e2e_pass_failing_ac_rows_rejects(
    sqlite_session: AsyncSession,
) -> None:
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-failing-ac-rows",
    )
    evidence = _full_qa_e2e_pass_evidence()
    evidence["ac_rows"] = [{"ac": "AC1", "result": "fail"}]
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        build_hash="sha256-abc",
        evidence=evidence,
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    assert "qa_e2e_pass_ac_rows_have_failures" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_qa_e2e_pass_missing_browser_matrix_rejects(
    sqlite_session: AsyncSession,
) -> None:
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-no-matrix",
    )
    evidence = _full_qa_e2e_pass_evidence()
    del evidence["browser_matrix"]
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        build_hash="sha256-abc",
        evidence=evidence,
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    assert "qa_e2e_pass_missing_browser_matrix" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_qa_e2e_pass_failing_browser_matrix_rejects(
    sqlite_session: AsyncSession,
) -> None:
    """A browser_matrix row with non-zero console_errors fails the
    read-side check. Mirror that on write."""
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-pass-bad-matrix",
    )
    evidence = _full_qa_e2e_pass_evidence()
    evidence["browser_matrix"] = [
        {
            "route": "/",
            "viewport": "375x812",
            "result": "pass",
            "console_errors": 3,
            "network_failures": 0,
        },
    ]
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        build_hash="sha256-abc",
        evidence=evidence,
    )
    with pytest.raises(HTTPException) as exc_info:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=qa),
        )
    assert exc_info.value.status_code == 422
    assert "qa_e2e_pass_browser_matrix_has_failures" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_qa_e2e_fail_skips_evidence_invariant(
    sqlite_session: AsyncSession,
) -> None:
    """FAIL verdicts don't need the PASS-only evidence shape."""
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-fail-skip",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="fail",
        evidence_type="browser",
        target="http://192.168.2.63:3002/product",
        evidence={"comment": "FAIL: AC1 broken at 375px"},
        blocking_owner="PF",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=qa),
    )
    assert read.verdict == "fail"


@pytest.mark.asyncio
async def test_qa_e2e_pass_skipped_when_role_not_required(
    sqlite_session: AsyncSession,
) -> None:
    """When the packet type doesn't require qa_e2e (e.g. infra_ops or
    review_only), the PASS evidence shape is not enforced — the role
    is informational on those packets."""
    board, qa, task = await _seed_frontend_ui_qa_task(
        sqlite_session,
        board_slug="qa-e2e-not-required",
    )
    task.review_packet_type = "infra_ops"
    sqlite_session.add(task)
    await sqlite_session.commit()
    await sqlite_session.refresh(task)

    payload = TaskReviewEventCreate(
        reviewer_role="qa_e2e",
        verdict="pass",
        evidence_type="browser",
        target=None,
        build_hash=None,
        evidence={"comment": "QA helper PASS on infra_ops"},
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=qa),
    )
    assert read.verdict == "pass"


# --- @Supervisor citation enforcement on PASS verdicts (Option A+B
# from operator review menu 2026-05-04 23:59 UTC). Architect verdict
# comment had the right structure but omitted the
# `@Supervisor <one-line routing intent>` line that
# architect-review-verdict skill mandates. Backend must reject the
# /review-events POST so a malformed comment cannot leave the
# human-visibility surface dark. Two paths: (B) skill passes
# ``linked_comment_id`` so the backend validates that exact comment
# text inline; (A) when not passed, fallback to the most recent
# comment from the same agent on the same task. Both reject 422
# with code=verdict_comment_missing_supervisor_citation.


async def _seed_frontend_ui_arch_task(
    session: AsyncSession,
    *,
    board_slug: str,
) -> tuple[Board, Agent, Task]:
    """Seed a frontend_ui packet + Architect agent + review-status task."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    arch_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name=f"org-{board_slug}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name=f"gw-{board_slug}",
            url="ws://gateway.example/ws",
            workspace_root="/tmp/openclaw",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name=board_slug,
        slug=board_slug,
    )
    session.add(board)
    arch = Agent(
        id=arch_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Architect",
        openclaw_session_id=f"agent:{board_slug}:architect",
        identity_profile={"dev_acp_flow": "review_only"},
    )
    session.add(arch)
    task = Task(
        id=task_id,
        board_id=board_id,
        title=f"task-{board_slug}",
        status="review",
        review_packet_type="frontend_ui",
        assigned_agent_id=arch_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return board, arch, task


async def _seed_comment(
    session: AsyncSession,
    *,
    board: Board,
    task: Task,
    agent: Agent,
    message: str,
) -> UUID:
    """Insert a task-comment ActivityEvent row and return its id."""
    from app.models.activity_events import ActivityEvent

    event = ActivityEvent(
        event_type="task.comment",
        message=message,
        task_id=task.id,
        board_id=board.id,
        agent_id=agent.id,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event.id


@pytest.mark.asyncio
async def test_architect_pass_rejects_when_recent_comment_missing_supervisor_citation(
    sqlite_session: AsyncSession,
) -> None:
    """Architect verdict comment without `@Supervisor` line → 422."""
    board, arch, task = await _seed_frontend_ui_arch_task(
        sqlite_session,
        board_slug="arch-no-citation",
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=arch,
        message=(
            "Architect review for X\nVerdict: PASS\n"
            "Lead wake: structured-review-verdict review event"
        ),
    )

    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://example/product",
        evidence={"comment": "PASS — verified", "no_child_tasks_required": True},
    )
    with pytest.raises(HTTPException) as exc:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=arch),
        )
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "verdict_comment_missing_supervisor_citation"


@pytest.mark.asyncio
async def test_architect_pass_accepts_when_recent_comment_has_supervisor_citation(
    sqlite_session: AsyncSession,
) -> None:
    """Positive control: A path — recent comment carries `@Supervisor` → POST succeeds."""
    board, arch, task = await _seed_frontend_ui_arch_task(
        sqlite_session,
        board_slug="arch-with-citation",
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=arch,
        message=(
            "Architect review for X\nVerdict: PASS\n"
            "@Supervisor lead approve and move to done\n"
            "Lead wake: structured-review-verdict review event"
        ),
    )

    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://example/product",
        evidence={"comment": "PASS — verified", "no_child_tasks_required": True},
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=arch),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_architect_pass_accepts_when_recent_comment_has_lead_citation(
    sqlite_session: AsyncSession,
) -> None:
    """``@lead`` is also accepted as a lead-citation, equivalent to
    ``@Supervisor``. Both refer to the board lead; the validator treats
    them as interchangeable so non-verdict comment conventions
    (``@lead``) and the structured-verdict convention (``@Supervisor``)
    can converge without forcing a one-sided template change."""
    board, arch, task = await _seed_frontend_ui_arch_task(
        sqlite_session,
        board_slug="arch-with-lead-citation",
    )
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=arch,
        message=(
            "Architect review for X\nVerdict: PASS\n"
            "@lead approve and move to done\n"
            "Lead wake: structured-review-verdict review event"
        ),
    )

    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://example/product",
        evidence={"comment": "PASS — verified", "no_child_tasks_required": True},
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=arch),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_architect_pass_accepts_with_linked_comment_id(
    sqlite_session: AsyncSession,
) -> None:
    """B path: ``linked_comment_id`` references the verdict comment
    explicitly. Defends against races where another comment landed
    between verdict POST and validator lookup."""
    board, arch, task = await _seed_frontend_ui_arch_task(
        sqlite_session,
        board_slug="arch-linked-id",
    )
    verdict_comment_id = await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=arch,
        message=(
            "Architect review for X\nVerdict: PASS\n"
            "@Supervisor @QA-E2E next gate is qa_e2e\n"
            "Lead wake: structured-review-verdict review event"
        ),
    )
    # newer comment without citation; fallback path would pick this and fail.
    await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=arch,
        message="follow-up note without citation",
    )

    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://example/product",
        evidence={"comment": "PASS — verified", "no_child_tasks_required": True},
        linked_comment_id=verdict_comment_id,
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=arch),
    )
    assert read.verdict == "pass"


@pytest.mark.asyncio
async def test_architect_pass_rejects_when_linked_comment_lacks_citation(
    sqlite_session: AsyncSession,
) -> None:
    """B path negative: explicit ``linked_comment_id`` to a comment
    without `@Supervisor` → 422."""
    board, arch, task = await _seed_frontend_ui_arch_task(
        sqlite_session,
        board_slug="arch-linked-bad",
    )
    bad_comment_id = await _seed_comment(
        sqlite_session,
        board=board,
        task=task,
        agent=arch,
        message="just a status note no citation",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="pass",
        evidence_type="source_review",
        target="http://example/product",
        evidence={"comment": "PASS — verified", "no_child_tasks_required": True},
        linked_comment_id=bad_comment_id,
    )
    with pytest.raises(HTTPException) as exc:
        await tasks_api.record_task_review_event(
            payload=payload,
            task=task,
            session=sqlite_session,
            actor=_ActorStub(agent=arch),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "verdict_comment_missing_supervisor_citation"


@pytest.mark.asyncio
async def test_fail_verdict_does_not_require_supervisor_citation(
    sqlite_session: AsyncSession,
) -> None:
    """FAIL/INCONCLUSIVE/INFRA_BLOCKED verdicts skip the citation
    check. The rule applies only to PASS — the verdict from which
    the operator may approve."""
    board, arch, task = await _seed_frontend_ui_arch_task(
        sqlite_session,
        board_slug="arch-fail-skip",
    )
    payload = TaskReviewEventCreate(
        reviewer_role="architect",
        verdict="fail",
        evidence_type="source_review",
        target="http://example/product",
        evidence={"comment": "FAIL: missing X"},
        blocking_owner="PF",
    )
    read = await tasks_api.record_task_review_event(
        payload=payload,
        task=task,
        session=sqlite_session,
        actor=_ActorStub(agent=arch),
    )
    assert read.verdict == "fail"
