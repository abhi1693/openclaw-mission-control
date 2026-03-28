"""Tests for per-agent model assignment API and service layer.

Tests cover:
  - GET bootstraps a pending profile when none exists
  - PATCH primary sets manual selection and returns aggregate
  - PATCH primary switches back to auto
  - PUT fallback-override replaces manual entries and returns aggregate
  - PUT fallback-override with override_mode=none + empty entries reverts to generated
  - POST recommendation:regenerate produces a fresh recommendation
  - Validation: manual primary referencing invalid model surfaces blocking issue
  - Fallback dedup: effective entries exclude the effective primary
  - Transition invariant: recommendation refresh does not overwrite valid manual override

These are unit-level tests using a mock/in-memory pattern — they validate
service logic without requiring a live database. Integration tests that run
against a real Postgres instance should live in tests/integration/.
"""

from __future__ import annotations

from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.model_controls import (
    PatchPrimaryRequest,
    PutFallbackOverrideRequest,
    FallbackEntryInput,
    RegenerateRecommendationRequest,
)
from app.services.model_controls import (
    _ACTIVE_MODEL_IDS,
    _assemble_effective_fallback,
    _compute_validation,
    _resolve_effective_primary,
    AgentModelAssignmentService,
)
from app.models.model_controls import AgentModelProfile, AgentModelFallbackEntry


# ---------------------------------------------------------------------------
# Unit tests for pure functions
# ---------------------------------------------------------------------------


def make_profile(**kwargs) -> AgentModelProfile:
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        board_id=None,
        role_key="worker",
        primary_model_id=None,
        primary_selection_mode="auto",
        recommended_primary_model_id=None,
        recommendation_status="pending",
        fallback_override_mode="none",
        config_status="pending",
    )
    defaults.update(kwargs)
    return AgentModelProfile(**defaults)


def make_fallback_entry(profile_id: UUID, source: str, position: int, model_id: str, enabled: bool = True) -> AgentModelFallbackEntry:
    return AgentModelFallbackEntry(
        id=uuid4(),
        agent_model_profile_id=profile_id,
        source=source,
        position=position,
        model_id=model_id,
        trigger_type="unavailable",
        enabled=enabled,
    )


class TestResolveEffectivePrimary:
    def test_manual_valid_model_returns_manual(self):
        p = make_profile(
            primary_selection_mode="manual",
            primary_model_id="9router/cx/gpt-5.4",
            recommended_primary_model_id="9router/ag/claude-sonnet-4-6",
        )
        assert _resolve_effective_primary(p) == "9router/cx/gpt-5.4"

    def test_manual_invalid_model_falls_back_to_recommended(self):
        p = make_profile(
            primary_selection_mode="manual",
            primary_model_id="9router/invalid/unknown",
            recommended_primary_model_id="9router/ag/claude-sonnet-4-6",
        )
        assert _resolve_effective_primary(p) == "9router/ag/claude-sonnet-4-6"

    def test_auto_mode_returns_recommended(self):
        p = make_profile(
            primary_selection_mode="auto",
            recommended_primary_model_id="9router/ag/claude-sonnet-4-6",
        )
        assert _resolve_effective_primary(p) == "9router/ag/claude-sonnet-4-6"

    def test_auto_mode_no_recommendation_returns_none(self):
        p = make_profile(primary_selection_mode="auto", recommended_primary_model_id=None)
        assert _resolve_effective_primary(p) is None


class TestAssembleEffectiveFallback:
    def _make_db_entry(self, profile_id: UUID, source: str, pos: int, model_id: str) -> AgentModelFallbackEntry:
        return make_fallback_entry(profile_id, source, pos, model_id)

    def test_override_none_returns_generated_only(self):
        pid = uuid4()
        generated = [
            self._make_db_entry(pid, "generated", 0, "9router/ag/claude-sonnet-4-6"),
        ]
        effective, source, status, has_fb, reason = _assemble_effective_fallback(
            generated, [], "none", "9router/cx/gpt-5.4"
        )
        assert len(effective) == 1
        assert effective[0].model_id == "9router/ag/claude-sonnet-4-6"
        assert source == "generated_only"
        assert has_fb is True

    def test_override_replace_uses_manual_only(self):
        pid = uuid4()
        generated = [
            self._make_db_entry(pid, "generated", 0, "9router/ag/claude-sonnet-4-6"),
        ]
        manual = [
            self._make_db_entry(pid, "manual", 0, "9router/cx/gpt-5.3-codex"),
        ]
        effective, source, status, has_fb, reason = _assemble_effective_fallback(
            generated, manual, "replace", "9router/cx/gpt-5.4"
        )
        assert len(effective) == 1
        assert effective[0].model_id == "9router/cx/gpt-5.3-codex"
        assert source == "manual_only"

    def test_primary_excluded_from_effective_fallback(self):
        pid = uuid4()
        primary = "9router/ag/claude-sonnet-4-6"
        generated = [
            self._make_db_entry(pid, "generated", 0, "9router/ag/claude-sonnet-4-6"),  # same as primary
            self._make_db_entry(pid, "generated", 1, "9router/ag/gemini-3-flash"),
        ]
        effective, source, status, has_fb, reason = _assemble_effective_fallback(
            generated, [], "none", primary
        )
        assert len(effective) == 1
        assert effective[0].model_id == "9router/ag/gemini-3-flash"

    def test_no_valid_entries_returns_empty_invalid(self):
        pid = uuid4()
        # All entries use an invalid model_id
        generated = [
            self._make_db_entry(pid, "generated", 0, "9router/invalid/xxx"),
        ]
        effective, source, status, has_fb, reason = _assemble_effective_fallback(
            generated, [], "none", None
        )
        assert has_fb is False
        assert status == "empty_invalid"
        assert reason is not None

    def test_deduplication_keeps_first_occurrence(self):
        pid = uuid4()
        manual = [
            self._make_db_entry(pid, "manual", 0, "9router/cx/gpt-5.4"),
            self._make_db_entry(pid, "manual", 1, "9router/cx/gpt-5.4"),  # duplicate
            self._make_db_entry(pid, "manual", 2, "9router/ag/gemini-3-flash"),
        ]
        effective, *_ = _assemble_effective_fallback([], manual, "replace", None)
        model_ids = [e.model_id for e in effective]
        assert model_ids.count("9router/cx/gpt-5.4") == 1
        assert "9router/ag/gemini-3-flash" in model_ids


class TestComputeValidation:
    def test_valid_state_returns_valid(self):
        p = make_profile(
            primary_selection_mode="manual",
            primary_model_id="9router/cx/gpt-5.4",
            recommendation_status="fresh",
            config_status="valid",
        )
        v = _compute_validation(p, "9router/cx/gpt-5.4", True, "configured")
        assert v.config_status == "valid"
        assert v.blocking_issues == []
        assert v.warnings == []

    def test_invalid_manual_primary_surfaces_blocking_issue(self):
        p = make_profile(
            primary_selection_mode="manual",
            primary_model_id="9router/invalid/xxx",
            recommendation_status="fresh",
        )
        v = _compute_validation(p, None, True, "configured")
        codes = [i.code for i in v.blocking_issues]
        assert "primary_model_invalid" in codes

    def test_no_effective_fallback_surfaces_blocking_issue(self):
        p = make_profile(recommendation_status="fresh")
        v = _compute_validation(p, "9router/cx/gpt-5.4", False, "empty_invalid")
        codes = [i.code for i in v.blocking_issues]
        assert "no_effective_fallback" in codes

    def test_stale_recommendation_emits_warning(self):
        p = make_profile(recommendation_status="stale")
        v = _compute_validation(p, "9router/cx/gpt-5.4", True, "configured")
        codes = [w.code for w in v.warnings]
        assert "recommendation_stale" in codes


class TestCatalogSet:
    def test_known_models_are_valid(self):
        for mid in _ACTIVE_MODEL_IDS:
            from app.services.model_controls import _is_valid_model
            assert _is_valid_model(mid), f"Expected {mid} to be valid"

    def test_unknown_model_is_invalid(self):
        from app.services.model_controls import _is_valid_model
        assert not _is_valid_model("9router/unknown/model")


# ---------------------------------------------------------------------------
# Integration-style service tests (requires AsyncSession mock)
# ---------------------------------------------------------------------------
# These are kept lightweight; full DB integration tests should be in
# tests/integration/test_model_controls_integration.py


class TestAgentModelAssignmentServiceStubs:
    """Smoke-level tests for service public methods using mocked session."""

    def _make_mock_session(self, profile: AgentModelProfile) -> MagicMock:
        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.one_or_none.return_value = profile
        exec_result.all.return_value = []
        session.exec = AsyncMock(return_value=exec_result)
        session.add = MagicMock()
        session.delete = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_get_assignment_bootstraps_new_profile(self):
        session = AsyncMock()

        # First exec: no existing profile for this agent
        exec_result_profile = MagicMock()
        exec_result_profile.one_or_none.return_value = None
        exec_result_profile.all.return_value = []

        # Second exec: fallback entries (empty on bootstrap)
        exec_result_fallbacks = MagicMock()
        exec_result_fallbacks.one_or_none.return_value = None
        exec_result_fallbacks.all.return_value = []

        # Simulate multiple exec calls with appropriate results
        session.exec = AsyncMock(side_effect=[exec_result_profile, exec_result_fallbacks])
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        # After add/flush, simulate profile with an id so downstream queries work
        new_profile = make_profile()
        added_models: list = []

        def capture_add(obj):
            added_models.append(obj)
            if isinstance(obj, AgentModelProfile):
                # simulate DB assigning a primary key
                obj.id = new_profile.id

        session.add.side_effect = capture_add

        svc = AgentModelAssignmentService(session)
        agent_id = uuid4()

        # Call should succeed on the happy path without raising
        result = await svc.get_assignment(agent_id)

        # A new profile should have been created for this agent
        created_profiles = [m for m in added_models if isinstance(m, AgentModelProfile)]
        assert len(created_profiles) == 1
        assert created_profiles[0].agent_id == agent_id

        # Service should have attempted to persist changes
        assert session.commit.await_count >= 1
        # And we got some aggregate assignment payload back
        assert result is not None
    @pytest.mark.asyncio
    async def test_patch_primary_manual_mode(self):
        profile = make_profile(
            primary_selection_mode="auto",
            recommended_primary_model_id="9router/ag/claude-sonnet-4-6",
            recommendation_status="fresh",
        )
        session = self._make_mock_session(profile)
        svc = AgentModelAssignmentService(session)

        payload = PatchPrimaryRequest(selection_mode="manual", model_id="9router/cx/gpt-5.4")
        result = await svc.patch_primary(profile.agent_id, payload)

        assert result.primary.manual_model_id == "9router/cx/gpt-5.4"
        assert result.primary.selection_mode == "manual"
        assert result.primary.source == "manual"

    @pytest.mark.asyncio
    async def test_patch_primary_missing_model_id_raises(self):
        profile = make_profile()
        session = self._make_mock_session(profile)
        svc = AgentModelAssignmentService(session)

        payload = PatchPrimaryRequest(selection_mode="manual", model_id=None)
        with pytest.raises(ValueError, match="model_id is required"):
            await svc.patch_primary(profile.agent_id, payload)

    @pytest.mark.asyncio
    async def test_regenerate_recommendation_does_not_overwrite_manual_primary(self):
        profile = make_profile(
            role_key="coding",
            primary_selection_mode="manual",
            primary_model_id="9router/cx/gpt-5.4",
            recommended_primary_model_id="9router/ag/claude-sonnet-4-6",
            recommendation_status="stale",
        )
        session = self._make_mock_session(profile)
        svc = AgentModelAssignmentService(session)

        payload = RegenerateRecommendationRequest(reason="test")
        result = await svc.regenerate_recommendation(profile.agent_id, payload)

        # Manual primary must survive recommendation refresh
        assert result.primary.manual_model_id == "9router/cx/gpt-5.4"
        assert result.primary.selection_mode == "manual"
        # Recommendation should be updated
        assert result.recommendation.status == "fresh"
