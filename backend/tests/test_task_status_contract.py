from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import tasks as tasks_api
from app.api.tasks import _delivery_contract_incomplete_error
from app.schemas.tasks import (
    OWNER_REQUIRED_STATUSES,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    actionability_missing_fields,
    delivery_contract_missing_fields,
    status_requires_assigned_owner,
)


def test_task_update_accepts_rework_status() -> None:
    model = TaskUpdate(status="rework")
    assert model.status == "rework"


def test_task_update_accepts_cancelled_status() -> None:
    model = TaskUpdate(status="cancelled")
    assert model.status == "cancelled"


def test_status_filter_accepts_rework_and_cancelled() -> None:
    assert tasks_api._status_values("review,rework,cancelled") == [
        "review",
        "rework",
        "cancelled",
    ]


def test_status_filter_rejects_unknown_status() -> None:
    with pytest.raises(HTTPException) as exc:
        tasks_api._status_values("archived")

    assert exc.value.status_code == 422
    assert exc.value.detail == "Unsupported task status filter."


def test_task_create_accepts_control_plane_metadata() -> None:
    model = TaskCreate(
        title="T",
        review_packet_type="frontend_ui",
        validation_target="http://192.168.2.60:3000",
        validation_target_kind="live_url",
        validation_target_scope="review",
        operator_decision_required=True,
        operator_decision_summary="Awaiting operator pricing decision.",
    )
    assert model.review_packet_type == "frontend_ui"
    assert model.validation_target_kind == "live_url"
    assert model.validation_target_scope == "review"
    assert model.operator_decision_required is True


def test_task_update_accepts_control_plane_metadata() -> None:
    model = TaskUpdate(
        review_packet_type="mixed",
        validation_target="/shared/worktree",
        validation_target_kind="workspace",
        validation_target_scope="runtime",
        operator_decision_required=True,
        operator_decision_summary="Awaiting legal text from operator.",
    )
    assert model.review_packet_type == "mixed"
    assert model.validation_target_kind == "workspace"
    assert model.validation_target_scope == "runtime"
    assert model.operator_decision_required is True


def test_task_read_exposes_control_plane_metadata() -> None:
    model = TaskRead(
        id="00000000-0000-4000-8000-000000000001",
        board_id="00000000-0000-4000-8000-000000000002",
        title="T",
        status="inbox",
        priority="medium",
        created_by_user_id=None,
        in_progress_at=None,
        cancelled_at=None,
        created_at="2026-04-16T00:00:00Z",
        updated_at="2026-04-16T00:00:00Z",
        review_packet_type="content_copy",
        validation_target="pricing operator brief",
        validation_target_kind="other",
        validation_target_scope="all",
        operator_decision_required=True,
        operator_decision_summary="Awaiting operator commitments.",
    )
    assert model.review_packet_type == "content_copy"
    assert model.validation_target == "pricing operator brief"
    assert model.operator_decision_required is True


def test_delivery_contract_requires_review_packet_for_active_status() -> None:
    assert delivery_contract_missing_fields(
        status="in_progress",
        review_packet_type=None,
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
    ) == ["review_packet_type"]


def test_delivery_contract_requires_validation_target_for_frontend_review() -> None:
    assert delivery_contract_missing_fields(
        status="review",
        review_packet_type="frontend_ui",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
    ) == [
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    ]


def test_delivery_contract_allows_content_copy_without_validation_target() -> None:
    assert (
        delivery_contract_missing_fields(
            status="review",
            review_packet_type="content_copy",
            validation_target=None,
            validation_target_kind=None,
            validation_target_scope=None,
        )
        == []
    )


# --------------------------------------------------------------------
# Phase IV §I2: actionability owner check (plan reference at
# docs/plans/2026-04-16-mc-delivery-enforcement-plan.md §I2).
# --------------------------------------------------------------------


def _actionability(
    status: str, *, owner: bool
) -> list[str]:
    """Call the pure helper with a complete contract triplet so only
    the owner check matters for the assertion."""

    return actionability_missing_fields(
        status=status,
        review_packet_type="review_only",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=uuid4() if owner else None,
    )


def test_owner_required_statuses_are_in_progress_and_done() -> None:
    assert OWNER_REQUIRED_STATUSES == {"in_progress", "done"}


def test_status_requires_assigned_owner_only_fires_for_those() -> None:
    for active in ("in_progress", "done"):
        assert status_requires_assigned_owner(active)
    for passive in ("inbox", "review", "rework", "cancelled", None):
        assert not status_requires_assigned_owner(passive)


def test_actionability_owner_missing_flags_in_progress() -> None:
    assert _actionability("in_progress", owner=False) == ["assigned_agent_id"]


def test_actionability_owner_missing_flags_done() -> None:
    assert _actionability("done", owner=False) == ["assigned_agent_id"]


def test_actionability_owner_present_does_not_flag() -> None:
    assert _actionability("in_progress", owner=True) == []


def test_actionability_review_does_not_require_owner() -> None:
    """Review is a queue state where the reviewer picks up after the
    transition — the handler explicitly unassigns on entry. §I2's
    owner requirement intentionally carves out this state."""

    assert _actionability("review", owner=False) == []


def test_actionability_inbox_and_terminal_states_skip_the_check() -> None:
    for status in ("inbox", "cancelled", "rework"):
        assert _actionability(status, owner=False) == []


def test_actionability_reports_owner_alongside_contract_triplet() -> None:
    """When both the owner and the triplet are missing, both surface
    so the operator can fix everything in one round trip."""

    assert actionability_missing_fields(
        status="in_progress",
        review_packet_type="frontend_ui",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    ) == [
        "assigned_agent_id",
        "validation_target",
        "validation_target_kind",
        "validation_target_scope",
    ]


def test_error_message_surfaces_actionability_when_owner_missing() -> None:
    """String-branch coverage: owner-missing tips the message wording
    toward "not actionable" while the wire ``code`` stays stable."""

    exc = _delivery_contract_incomplete_error(
        status_value="in_progress",
        missing_fields=["assigned_agent_id", "validation_target"],
    )
    detail = exc.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "task_delivery_contract_incomplete"
    assert "not actionable" in detail["message"]


def test_error_message_stays_contract_when_owner_present() -> None:
    """Triplet-only violation keeps the legacy wording for
    downstream log-matchers that haven't migrated."""

    exc = _delivery_contract_incomplete_error(
        status_value="review",
        missing_fields=["validation_target"],
    )
    detail = exc.detail
    assert isinstance(detail, dict)
    assert "delivery contract metadata" in detail["message"]
    assert "not actionable" not in detail["message"]


# --------------------------------------------------------------------
# Phase V §I8: deploy-truth field validators.
# --------------------------------------------------------------------


def test_packet_commit_sha_accepts_short_and_full_hex() -> None:
    model = TaskCreate(title="T", packet_commit_sha="abc1234")
    assert model.packet_commit_sha == "abc1234"
    model = TaskCreate(title="T", packet_commit_sha="a" * 40)
    assert model.packet_commit_sha == "a" * 40


def test_packet_commit_sha_lowercases_and_trims() -> None:
    model = TaskCreate(title="T", packet_commit_sha="  ABCDEF9  ")
    assert model.packet_commit_sha == "abcdef9"


def test_packet_commit_sha_rejects_non_hex() -> None:
    with pytest.raises(ValueError, match="packet_commit_sha"):
        TaskCreate(title="T", packet_commit_sha="not-a-sha")


def test_packet_commit_sha_rejects_too_short() -> None:
    with pytest.raises(ValueError, match="packet_commit_sha"):
        TaskCreate(title="T", packet_commit_sha="abc123")  # 6 chars


def test_packet_commit_sha_rejects_too_long() -> None:
    with pytest.raises(ValueError, match="packet_commit_sha"):
        TaskCreate(title="T", packet_commit_sha="a" * 41)


def test_packet_build_sha_independently_validated() -> None:
    """Build SHA uses the same validator as commit SHA — the two are
    independently nullable because a target may have a build SHA
    without a distinct commit SHA (pre-Phase-V data)."""

    with pytest.raises(ValueError, match="packet_build_sha"):
        TaskCreate(title="T", packet_build_sha="nope")


def test_packet_shas_null_by_default() -> None:
    model = TaskCreate(title="T")
    assert model.packet_commit_sha is None
    assert model.packet_build_sha is None
    assert model.supports_build_metadata is None


def test_supports_build_metadata_accepts_tri_state() -> None:
    for value in (True, False, None):
        model = TaskCreate(title="T", supports_build_metadata=value)
        assert model.supports_build_metadata is value


def test_task_update_also_validates_sha_shape() -> None:
    """Update path applies the same SHA format check so a PATCH can't
    sneak garbage past the create-time validator."""

    with pytest.raises(ValueError, match="packet_commit_sha"):
        TaskUpdate(packet_commit_sha="not-a-sha")


def test_actionability_validates_against_done_when_approval_gates_move_to_done() -> None:
    """move_to_done approval gate must validate against the TARGET
    state (``done``) not the task's current state (``review``).

    Without this, a task whose assignee is cleared between approval
    creation and execution would skip the owner check — ``review``
    doesn't require an owner but ``done`` does, and the lead PATCH
    that actually transitions to ``done`` never re-validates.
    """

    assert actionability_missing_fields(
        status="done",
        review_packet_type="review_only",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    ) == ["assigned_agent_id"]
    # Same payload against the current state ``review`` would NOT
    # flag the owner — the carve-out intentionally skips it.
    assert actionability_missing_fields(
        status="review",
        review_packet_type="review_only",
        validation_target=None,
        validation_target_kind=None,
        validation_target_scope=None,
        assigned_agent_id=None,
    ) == []


# --------------------------------------------------------------------
# SSRF guard on validation_target (Phase V §I8 deploy-truth fetch
# target — applies only when ``validation_target_kind`` is a URL
# shape, i.e. ``live_url`` or ``api_base``).
# --------------------------------------------------------------------


def _url_target_update(url: str) -> TaskUpdate:
    return TaskUpdate(
        validation_target=url,
        validation_target_kind="live_url",
        validation_target_scope="review",
    )


def test_validation_target_accepts_private_lan_url() -> None:
    """MC deploys on a private LAN — RFC1918 hosts must remain legal
    (prod uses ``192.168.2.64``, tests use ``192.168.2.60``)."""

    model = _url_target_update("http://192.168.2.60:3000")
    assert model.validation_target == "http://192.168.2.60:3000"


def test_validation_target_accepts_public_https() -> None:
    model = _url_target_update("https://example.com/build")
    assert model.validation_target == "https://example.com/build"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://attacker.tld/",
        "javascript:alert(1)",
    ],
)
def test_validation_target_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(Exception) as exc:  # ValidationError wraps ValueError
        _url_target_update(url)
    assert "http://" in str(exc.value) or "https://" in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5432/healthz",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_validation_target_rejects_ssrf_hosts(url: str) -> None:
    with pytest.raises(Exception) as exc:
        _url_target_update(url)
    assert "blocked" in str(exc.value).lower()


def test_validation_target_rejects_length_bomb() -> None:
    with pytest.raises(Exception) as exc:
        _url_target_update("http://example.com/" + ("a" * 3000))
    assert "exceeds" in str(exc.value)


def test_validation_target_url_guard_skipped_for_workspace_kind() -> None:
    """``workspace`` kind is a filesystem path, not a URL — the SSRF
    guard must not apply. Lock the carve-out so a well-meaning audit
    doesn't later tighten it into breaking legitimate workspace targets."""

    model = TaskUpdate(
        validation_target="/shared/worktree",
        validation_target_kind="workspace",
        validation_target_scope="runtime",
    )
    assert model.validation_target == "/shared/worktree"


def test_validation_target_url_guard_skipped_for_other_kind() -> None:
    """``other`` kind carries freeform text — no URL validation."""

    model = TaskUpdate(
        validation_target="prod-cluster-v2",
        validation_target_kind="other",
        validation_target_scope="deploy",
    )
    assert model.validation_target == "prod-cluster-v2"


# --- Agent-path transition state machine ---------------------------------
#
# Codex review 2026-04-24 found that the non-lead agent path accepted
# any target status without checking the source state, which let
# ``inbox → review``, ``rework → review``, ``rework → done``, and
# ``in_progress → done`` slip through. The allow-list and validator
# below now refuse those.


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("inbox", "in_progress"),
        ("rework", "in_progress"),
        ("in_progress", "review"),
        # completion — subject to downstream gates
        ("in_progress", "done"),
        ("review", "done"),
        # backward / abandon
        ("in_progress", "inbox"),
        ("rework", "inbox"),
        ("in_progress", "rework"),
        # no-op self-moves
        ("inbox", "inbox"),
        ("in_progress", "in_progress"),
        ("review", "review"),
        ("rework", "rework"),
        ("done", "done"),
    ],
)
def test_agent_transition_allows_legitimate_moves(
    from_status: str,
    to_status: str,
) -> None:
    # Should not raise.
    tasks_api._validate_agent_transition(
        from_status=from_status,
        to_status=to_status,
    )


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        # cycle-1 bug class: inbox skipping in_progress
        ("inbox", "review"),
        ("inbox", "done"),
        # codex finding D: rework skipping in_progress
        ("rework", "review"),
        ("rework", "done"),
        # agents cannot unilaterally move backward out of review;
        # rework / inbox / in_progress from review is lead-only
        ("review", "inbox"),
        ("review", "rework"),
        ("review", "in_progress"),
        # terminal: done never exits on the agent path
        ("done", "in_progress"),
        ("done", "review"),
        ("done", "inbox"),
    ],
)
def test_agent_transition_rejects_illegal_moves(
    from_status: str,
    to_status: str,
) -> None:
    with pytest.raises(HTTPException) as exc:
        tasks_api._validate_agent_transition(
            from_status=from_status,
            to_status=to_status,
        )

    assert exc.value.status_code == 403
    assert "Invalid status transition" in str(exc.value.detail)
