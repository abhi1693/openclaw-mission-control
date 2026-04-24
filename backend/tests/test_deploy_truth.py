# ruff: noqa: INP001
"""Unit tests for Phase V §I8 deploy-truth helpers.

Covers the pure comparator, the ``/__build`` fetcher (with httpx
MockTransport), and the handler-level ``_require_deploy_truth`` guard
branches. End-to-end PATCH coverage rides on the existing task test
suite once Phase V is graduated on a board.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.api.tasks import (
    ERROR_CODE_DEPLOY_TRUTH_MISSING_PACKET_SHA,
    ERROR_CODE_DEPLOY_TRUTH_SHA_MISMATCH,
    ERROR_CODE_DEPLOY_TRUTH_UNREACHABLE,
    _require_deploy_truth,
)
from app.models.tasks import Task
from app.services.deploy_truth import (
    BuildMetadata,
    DeployTruthFetchError,
    fetch_build_metadata,
    packet_sha_matches_live,
)


# --------------------------------------------------------------------
# packet_sha_matches_live
# --------------------------------------------------------------------


def test_exact_full_match() -> None:
    assert packet_sha_matches_live(
        packet_sha="a" * 40, live_sha="a" * 40
    )


def test_short_prefix_matches_full() -> None:
    full = "abcdef1234567890" + "0" * 24
    short = full[:7]
    assert packet_sha_matches_live(packet_sha=short, live_sha=full)


def test_full_packet_against_short_live_rejected() -> None:
    """Live SHA is the authority. If the target reports a short SHA
    while the reviewer claims a full one, the capability is
    misconfigured — the target should always report at least as much
    precision as the claim. Fail closed rather than fuzzy-match."""

    full = "abcdef1234567890" + "0" * 24
    short = full[:10]
    assert not packet_sha_matches_live(packet_sha=full, live_sha=short)


def test_different_prefixes_do_not_match() -> None:
    assert not packet_sha_matches_live(
        packet_sha="abcdef1", live_sha="0000000"
    )


def test_drift_at_or_beyond_short_length_rejected() -> None:
    """If the shorter prefix diverges at any character, the two SHAs
    are treated as different commits — no fuzzy match."""

    assert not packet_sha_matches_live(
        packet_sha="abcde01", live_sha="abcde99" + "f" * 33
    )


# --------------------------------------------------------------------
# fetch_build_metadata
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_normalised_metadata() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/__build"
        return httpx.Response(
            200,
            json={
                "sha": "ABCDEF1234567890",
                "built_at": "2026-04-21T12:00:00Z",
                "branch": "main",
                "target": "prod",
            },
        )

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        md = await fetch_build_metadata(
            "https://example.test", client=client
        )
    # SHA is lowercased to match the schema validator's normalisation.
    assert md == BuildMetadata(
        sha="abcdef1234567890",
        built_at="2026-04-21T12:00:00Z",
        branch="main",
        target="prod",
    )


@pytest.mark.asyncio
async def test_fetch_raises_on_non_200() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DeployTruthFetchError, match="HTTP 404"):
            await fetch_build_metadata(
                "https://example.test", client=client
            )


@pytest.mark.asyncio
async def test_fetch_raises_on_non_json_body() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, text="not json")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DeployTruthFetchError, match="non-JSON"):
            await fetch_build_metadata(
                "https://example.test", client=client
            )


@pytest.mark.asyncio
async def test_fetch_rejects_malformed_live_sha() -> None:
    """A target returning ``sha=abcdef1zzz`` would pass
    ``live.startswith(packet)`` for ``packet=abcdef1`` and silently
    false-pass the deploy-truth gate. Live SHA must satisfy the same
    hex shape the packet validator enforces."""

    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"sha": "abcdef1zzz"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DeployTruthFetchError, match="malformed sha"):
            await fetch_build_metadata(
                "https://example.test", client=client
            )


@pytest.mark.asyncio
async def test_fetch_handles_trailing_slash_target() -> None:
    observed: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        observed.append(str(request.url))
        return httpx.Response(200, json={"sha": "abcdef1"})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await fetch_build_metadata(
            "https://example.test/", client=client
        )
    # No double-slash after the host.
    assert observed == ["https://example.test/__build"]


# --------------------------------------------------------------------
# _require_deploy_truth
# --------------------------------------------------------------------


def _task(**overrides: object) -> Task:
    defaults: dict[str, object] = {
        "board_id": uuid4(),
        "title": "Test",
        "status": "review",
        "validation_target": "https://example.test",
        "supports_build_metadata": True,
        "packet_commit_sha": "abcdef1",
    }
    defaults.update(overrides)
    return Task(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_guard_skips_non_review_done_states() -> None:
    """inbox / in_progress / cancelled / rework should never hit the
    gate — the deploy-truth check only applies to review + done."""

    for status in ("inbox", "in_progress", "cancelled", "rework"):
        await _require_deploy_truth(
            _task(status=status, supports_build_metadata=None),
            actor_agent_id=None,
        )


@pytest.mark.asyncio
async def test_guard_skips_when_no_validation_target() -> None:
    """Content/review-only tasks legitimately have no target; the
    gate has nothing to check."""

    await _require_deploy_truth(
        _task(validation_target=None), actor_agent_id=None
    )


@pytest.mark.asyncio
async def test_guard_rejects_missing_packet_sha_when_capable() -> None:
    with pytest.raises(HTTPException) as exc:
        await _require_deploy_truth(
            _task(packet_commit_sha=None), actor_agent_id=None
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == ERROR_CODE_DEPLOY_TRUTH_MISSING_PACKET_SHA  # type: ignore[index]


@pytest.mark.asyncio
async def test_guard_degrades_silently_when_capability_false_or_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """False/None capability is the degraded-validation path: emit the
    shadow metric, let the transition through. No 409."""

    captured: list[tuple[object, ...]] = []

    from app.api import tasks as tasks_module

    def _spy(**kwargs: object) -> None:
        captured.append(tuple(sorted(kwargs.items())))

    monkeypatch.setattr(
        tasks_module, "_schedule_deploy_degraded_emit", _spy
    )
    await _require_deploy_truth(
        _task(supports_build_metadata=False), actor_agent_id=None
    )
    await _require_deploy_truth(
        _task(supports_build_metadata=None), actor_agent_id=None
    )
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_guard_rejects_sha_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import tasks as tasks_module

    async def _stub_fetch(target: str, *, client: object = None) -> BuildMetadata:
        return BuildMetadata(sha="9999999")

    monkeypatch.setattr(tasks_module, "fetch_build_metadata", _stub_fetch)
    with pytest.raises(HTTPException) as exc:
        await _require_deploy_truth(_task(), actor_agent_id=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == ERROR_CODE_DEPLOY_TRUTH_SHA_MISMATCH  # type: ignore[index]


@pytest.mark.asyncio
async def test_guard_accepts_matching_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import tasks as tasks_module

    async def _stub_fetch(target: str, *, client: object = None) -> BuildMetadata:
        return BuildMetadata(sha="abcdef1234567890" + "0" * 24)

    monkeypatch.setattr(tasks_module, "fetch_build_metadata", _stub_fetch)
    # Packet SHA is a prefix of the live SHA — treated as a match.
    await _require_deploy_truth(_task(), actor_agent_id=None)


@pytest.mark.asyncio
async def test_guard_rejects_unreachable_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import tasks as tasks_module

    async def _stub_fetch(target: str, *, client: object = None) -> BuildMetadata:
        raise DeployTruthFetchError("connection refused")

    monkeypatch.setattr(tasks_module, "fetch_build_metadata", _stub_fetch)
    with pytest.raises(HTTPException) as exc:
        await _require_deploy_truth(_task(), actor_agent_id=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == ERROR_CODE_DEPLOY_TRUTH_UNREACHABLE  # type: ignore[index]


@pytest.mark.asyncio
async def test_guard_rejects_live_payload_without_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target that returns /__build but with no sha field is a
    misconfigured endpoint — 409 with the unreachable code so the
    operator fixes the build-metadata response."""

    from app.api import tasks as tasks_module

    async def _stub_fetch(target: str, *, client: object = None) -> BuildMetadata:
        return BuildMetadata(sha=None)

    monkeypatch.setattr(tasks_module, "fetch_build_metadata", _stub_fetch)
    with pytest.raises(HTTPException) as exc:
        await _require_deploy_truth(_task(), actor_agent_id=None)
    assert exc.value.detail["code"] == ERROR_CODE_DEPLOY_TRUTH_UNREACHABLE  # type: ignore[index]


def test_projected_task_applies_only_declared_fields() -> None:
    """The projection helper copies the fields deploy-truth reads and
    overlays only the fields the PATCH actually declared. This is the
    anti-autoflush shape — we check the projected state before
    mutating the ORM task so the /__build fetch can't hold a row
    lock while blocked on HTTP."""

    from app.api.tasks import _projected_task

    current = _task(status="in_progress", packet_commit_sha="abcdef1")
    # PATCH declares a status transition + new SHA.
    projected = _projected_task(
        current,
        {"status": "done", "packet_commit_sha": "9999999"},
    )
    # Projected task reflects the declared mutation…
    assert projected.status == "done"
    assert projected.packet_commit_sha == "9999999"
    # …but the source task is untouched.
    assert current.status == "in_progress"
    assert current.packet_commit_sha == "abcdef1"


def test_projected_task_preserves_unmentioned_fields() -> None:
    """Fields not mentioned in the PATCH updates dict must read
    through from the source task."""

    from app.api.tasks import _projected_task

    current = _task(
        status="in_progress",
        validation_target="https://example.test",
        supports_build_metadata=True,
        packet_commit_sha="abcdef1",
    )
    projected = _projected_task(current, {"status": "review"})
    assert projected.status == "review"
    # No mutation → inherited from source.
    assert projected.validation_target == "https://example.test"
    assert projected.supports_build_metadata is True
    assert projected.packet_commit_sha == "abcdef1"


# --------------------------------------------------------------------
# deploy_truth_v1 rollout flag (codex finding E, 2026-04-24)
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deploy_truth_skipped_when_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``rollout_flags["deploy_truth_v1"]`` is False, the gate must
    emit a degraded-shadow metric and return without raising — even if
    the task would otherwise fail (missing packet_commit_sha)."""

    shadow_calls: list[dict[str, object]] = []

    def _fake_emit(**kwargs: object) -> None:
        shadow_calls.append(kwargs)

    monkeypatch.setattr(
        "app.api.tasks._schedule_deploy_degraded_emit",
        _fake_emit,
    )

    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="t",
        status="review",
        validation_target="https://example.test",
        supports_build_metadata=True,
        packet_commit_sha=None,  # would normally raise
    )
    await _require_deploy_truth(
        task,
        actor_agent_id=None,
        rollout_flags={"deploy_truth_v1": False},
    )
    assert len(shadow_calls) == 1
    assert shadow_calls[0]["reason"] == "deploy_truth_v1_disabled"


@pytest.mark.asyncio
async def test_deploy_truth_enforces_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``rollout_flags["deploy_truth_v1"]`` is True, the gate must
    raise on missing packet_commit_sha (pre-existing enforcement path)."""

    monkeypatch.setattr(
        "app.api.tasks._schedule_deploy_degraded_emit",
        lambda **_: None,
    )

    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="t",
        status="review",
        validation_target="https://example.test",
        supports_build_metadata=True,
        packet_commit_sha=None,
    )
    with pytest.raises(HTTPException) as exc:
        await _require_deploy_truth(
            task,
            actor_agent_id=None,
            rollout_flags={"deploy_truth_v1": True},
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == ERROR_CODE_DEPLOY_TRUTH_MISSING_PACKET_SHA


@pytest.mark.asyncio
async def test_deploy_truth_unchanged_when_flag_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backward-compat: when the caller passes ``rollout_flags=None``
    (i.e. doesn't know about the flag), the gate behaves as before —
    enforced. This preserves admin-path / create-path behavior for
    callers that haven't been updated to resolve flags yet."""

    monkeypatch.setattr(
        "app.api.tasks._schedule_deploy_degraded_emit",
        lambda **_: None,
    )

    task = Task(
        id=uuid4(),
        board_id=uuid4(),
        title="t",
        status="review",
        validation_target="https://example.test",
        supports_build_metadata=True,
        packet_commit_sha=None,
    )
    with pytest.raises(HTTPException) as exc:
        await _require_deploy_truth(task, actor_agent_id=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == ERROR_CODE_DEPLOY_TRUTH_MISSING_PACKET_SHA
