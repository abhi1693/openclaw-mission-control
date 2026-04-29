# ruff: noqa

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app.services.openclaw.internal.agent_key as agent_key_mod
import app.services.openclaw.provisioning as agent_provisioning
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.services.openclaw.shared import GatewayAgentIdentity
from app.services.souls_directory import SoulRef


def test_slugify_normalizes_and_trims():
    assert agent_provisioning.slugify("Hello, World") == "hello-world"
    assert agent_provisioning.slugify("  A   B  ") == "a-b"


def test_slugify_falls_back_to_uuid_hex(monkeypatch):
    class _FakeUuid:
        hex = "deadbeef"

    monkeypatch.setattr(agent_key_mod, "uuid4", lambda: _FakeUuid())
    assert agent_provisioning.slugify("!!!") == "deadbeef"


@dataclass
class _AgentStub:
    name: str
    openclaw_session_id: str | None = None
    heartbeat_config: dict | None = None
    is_board_lead: bool = False
    id: UUID = field(default_factory=uuid4)
    identity_profile: dict | None = None
    identity_template: str | None = None
    soul_template: str | None = None


def test_agent_key_uses_session_key_when_present():
    agent = _AgentStub(name="Alice", openclaw_session_id="agent:alice:main")
    assert agent_provisioning._agent_key(agent) == "alice"

    agent2 = _AgentStub(name="Hello, World", openclaw_session_id=None)
    assert agent_provisioning._agent_key(agent2) == "hello-world"


def test_workspace_path_preserves_tilde_in_workspace_root():
    # Mission Control accepts a user-entered workspace root (from the UI) and must
    # treat it as an opaque string. In particular, we must not expand "~" to a
    # filesystem path since that behavior depends on the host environment.
    agent = _AgentStub(name="Alice", openclaw_session_id="agent:alice:main")
    assert agent_provisioning._workspace_path(agent, "~/.openclaw") == "~/.openclaw/workspace-alice"


def test_wakeup_text_includes_bootstrap_before_agents():
    agent = _AgentStub(name="Alice")

    text = agent_provisioning._wakeup_text(agent, verb="created")

    assert "If BOOTSTRAP.md exists, read it first, then read AGENTS.md." in text
    assert "Do not assume exec is blocked based on an earlier session." in text
    assert "Attempt the required command once in this session before saying you are blocked." in text


def test_wakeup_text_requires_explicit_heartbeat_checkin():
    """Regression: idle agents must be told to POST /api/v1/agent/heartbeat
    explicitly, otherwise gpt-5.4 and similar models short-circuit with
    ``NO_REPLY`` and never trigger ``commit_heartbeat`` — which is the only
    code path that resets ``wake_attempts`` to 0. Without this instruction,
    an idle agent can age into the permanent-offline state after three
    deadline-spaced wakes.
    """
    agent = _AgentStub(name="Alice")

    text = agent_provisioning._wakeup_text(agent, verb="updated")

    assert "POST" in text and "/api/v1/agent/heartbeat" in text, (
        "wake text must name the heartbeat endpoint so the agent runs the "
        "check-in curl via tool use"
    )
    # Both BOOTSTRAP.md and TOOLS.md render the credentials on fresh
    # provision; either must be an acceptable source so a late TOOLS.md
    # visibility lag does not break the wake path.
    assert "BOOTSTRAP.md" in text and "TOOLS.md" in text, (
        "wake text must point the agent at both BOOTSTRAP.md and TOOLS.md "
        "for $BASE_URL and $AUTH_TOKEN — either is a valid credential source"
    )


def test_wakeup_text_forbids_text_shortcut_before_checkin():
    """Regression: the wake text must forbid ANY chat reply before the curl
    has returned a 2xx, not just the specific ``NO_REPLY`` / ``HEARTBEAT``
    strings we have seen so far. Enumerating specific shortcut strings
    leaves adversarial loopholes (``OK``, ``ACK``, greetings, status
    summaries) that models can still take.
    """
    agent = _AgentStub(name="Alice")

    text = agent_provisioning._wakeup_text(agent, verb="updated")

    # All the known text shortcuts must be explicitly enumerated as
    # forbidden so the model has no ambiguity about the default behavior.
    for shortcut in ("NO_REPLY", "HEARTBEAT", "HEARTBEAT_OK", "OK", "ACK"):
        assert shortcut in text, (
            f"wake text must explicitly name {shortcut!r} in its "
            "forbidden-reply list — models shortcut on any acknowledgement "
            "that is not ruled out"
        )
    lowered = text.lower()
    assert "do not send any chat response" in lowered, (
        "wake text must frame the rule as 'no chat reply at all until 2xx' "
        "rather than enumerating forbidden strings, so future shortcut "
        "variants are also caught by default"
    )
    assert "2xx" in text, (
        "wake text must state the 2xx gate so the agent knows what "
        "'successful check-in' means in transport terms"
    )


def test_should_consume_wake_strike_charges_first_wake_in_fresh_cycle():
    """The very first wake in a fresh escalation cycle (wake_attempts == 0)
    must consume a strike — otherwise reconcile would never advance the
    counter toward the 3-strike offline threshold.
    """
    from datetime import datetime, timedelta, timezone

    from app.services.openclaw.lifecycle_orchestrator import (
        should_consume_wake_strike,
    )

    now = datetime(2026, 4, 5, 16, 0, tzinfo=timezone.utc)
    assert should_consume_wake_strike(
        prev_wake_attempts=0,
        prev_checkin_deadline_at=None,
        now=now,
    )
    assert should_consume_wake_strike(
        prev_wake_attempts=0,
        prev_checkin_deadline_at=now - timedelta(minutes=1),
        now=now,
    )
    assert should_consume_wake_strike(
        prev_wake_attempts=0,
        prev_checkin_deadline_at=now + timedelta(minutes=30),
        now=now,
    )


def test_should_consume_wake_strike_charges_when_previous_deadline_expired():
    """A subsequent wake whose previous grace window has already elapsed
    without a successful check-in represents a real retry — it must
    consume a strike so the counter advances toward offline.
    """
    from datetime import datetime, timedelta, timezone

    from app.services.openclaw.lifecycle_orchestrator import (
        should_consume_wake_strike,
    )

    now = datetime(2026, 4, 5, 16, 0, tzinfo=timezone.utc)
    assert should_consume_wake_strike(
        prev_wake_attempts=1,
        prev_checkin_deadline_at=now - timedelta(seconds=1),
        now=now,
    )
    assert should_consume_wake_strike(
        prev_wake_attempts=2,
        prev_checkin_deadline_at=now - timedelta(hours=1),
        now=now,
    )


def test_should_consume_wake_strike_skips_wake_inside_grace_window():
    """Regression: explicit admin and coordination recovery wakes that
    land inside the current grace window must NOT double-charge an agent
    that was already on track to check in. Without this, a user pressing
    "recover" burns a strike even though the sweep had not yet decided
    the previous wake failed.
    """
    from datetime import datetime, timedelta, timezone

    from app.services.openclaw.lifecycle_orchestrator import (
        should_consume_wake_strike,
    )

    now = datetime(2026, 4, 5, 16, 0, tzinfo=timezone.utc)
    assert not should_consume_wake_strike(
        prev_wake_attempts=1,
        prev_checkin_deadline_at=now + timedelta(minutes=30),
        now=now,
    )
    assert not should_consume_wake_strike(
        prev_wake_attempts=2,
        prev_checkin_deadline_at=now + timedelta(seconds=1),
        now=now,
    )


def test_should_consume_wake_strike_charges_when_deadline_missing():
    """Defensive: if wake_attempts > 0 but the deadline is None, we cannot
    prove the previous wake is still mid-grace. Charge the strike because
    the safer failure mode is to count it — missing a legitimate retry is
    worse than under-counting the retry budget.
    """
    from datetime import datetime, timezone

    from app.services.openclaw.lifecycle_orchestrator import (
        should_consume_wake_strike,
    )

    now = datetime(2026, 4, 5, 16, 0, tzinfo=timezone.utc)
    assert should_consume_wake_strike(
        prev_wake_attempts=1,
        prev_checkin_deadline_at=None,
        now=now,
    )
    assert should_consume_wake_strike(
        prev_wake_attempts=2,
        prev_checkin_deadline_at=None,
        now=now,
    )


def test_wakeup_text_allows_error_report_on_curl_failure():
    """Regression: if the curl genuinely fails (exec blocked, auth 4xx,
    network 5xx, missing credentials), the agent must be allowed to send a
    short error report — otherwise we trade the NO_REPLY trap for a
    silent-failure trap where legitimate failures never surface.
    """
    agent = _AgentStub(name="Alice")

    text = agent_provisioning._wakeup_text(agent, verb="updated")

    lowered = text.lower()
    assert "fails" in lowered and "error report" in lowered, (
        "wake text must describe what the agent should do if the curl "
        "fails after a fresh attempt — silence-on-failure is worse than "
        "the original NO_REPLY bug for debuggability"
    )


def test_agent_lifecycle_workspace_path_preserves_tilde_in_workspace_root():
    assert (
        AgentLifecycleService.workspace_path("Alice", "~/.openclaw")
        == "~/.openclaw/workspace-alice"
    )


def test_updated_agent_list_keeps_disabled_heartbeat_entry_with_minimal_raw_shape():
    raw_list = [
        {
            "id": "mc-disabled",
            "workspace": "/tmp/workspace-mc-disabled",
            "heartbeat": {"every": "0m"},
        }
    ]

    new_list = agent_provisioning._updated_agent_list(
        raw_list,
        {
            "mc-disabled": (
                "/tmp/workspace-mc-disabled",
                {"every": "0m", "target": "last", "includeReasoning": False},
            ),
        },
    )

    assert new_list == raw_list


def test_updated_agent_list_keeps_disabled_heartbeat_entry_with_stale_model():
    raw_list = [
        {
            "id": "mc-disabled",
            "workspace": "/tmp/workspace-mc-disabled",
            "heartbeat": {
                "every": "0m",
                "target": "last",
                "includeReasoning": False,
                "model": "minimax/MiniMax-M2.7",
            },
        }
    ]

    new_list = agent_provisioning._updated_agent_list(
        raw_list,
        {
            "mc-disabled": (
                "/tmp/workspace-mc-disabled",
                {"every": "0m", "target": "last", "includeReasoning": False},
            ),
        },
    )

    assert new_list == raw_list


def test_heartbeat_configs_equal_canonicalizes_disabled_spellings():
    assert agent_provisioning._heartbeat_configs_equal(
        {"every": "disabled"},
        {"every": "0m", "target": "last", "includeReasoning": False},
    )


def test_templates_root_points_to_repo_templates_dir():
    root = agent_provisioning._templates_root()
    assert root.name == "templates"
    assert root.parent.name == "backend"
    assert (root / "BOARD_AGENTS.md.j2").exists()


def test_user_context_uses_email_fallback_when_name_is_missing():
    user = SimpleNamespace(
        name=None,
        preferred_name=None,
        pronouns=None,
        timezone=None,
        notes=None,
        context=None,
        email="jane.doe@example.com",
    )

    context = agent_provisioning._user_context(user)

    assert context["user_name"] == "jane.doe@example.com"
    assert context["user_preferred_name"] == "jane.doe"


def test_user_context_prefers_name_token_when_preferred_name_missing():
    user = SimpleNamespace(
        name="Jane Doe",
        preferred_name=None,
        pronouns=None,
        timezone=None,
        notes=None,
        context=None,
        email=None,
    )

    context = agent_provisioning._user_context(user)

    assert context["user_name"] == "Jane Doe"
    assert context["user_preferred_name"] == "Jane"


@dataclass
class _GatewayStub:
    id: UUID
    name: str
    url: str
    token: str | None
    workspace_root: str
    allow_insecure_tls: bool = False
    disable_device_pairing: bool = False


@pytest.mark.asyncio
async def test_apply_agent_lifecycle_writes_files_before_wake(monkeypatch):
    """Regression: apply_agent_lifecycle must complete all credential file
    writes BEFORE sending the wake message, AND it must verify credentials
    are visible to the gateway before delivering the wake.

    Otherwise the agent can receive the wake text (which instructs it to
    read ``$BASE_URL`` and ``$AUTH_TOKEN`` from ``BOOTSTRAP.md`` or
    ``TOOLS.md``) before those files are visible on the gateway side,
    which produces a guaranteed NO_REPLY and burns a wake attempt.
    """
    gateway_id = uuid4()
    session_key = GatewayAgentIdentity.session_key_for_id(gateway_id)
    gateway = _GatewayStub(
        id=gateway_id,
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = _AgentStub(name="Acme Gateway Agent", openclaw_session_id=session_key)

    call_log: list[str] = []

    async def _fake_ensure_agent_session(self, session_key, *, label=None):
        call_log.append("ensure_agent_session")

    async def _fake_upsert_agent(self, registration):
        call_log.append("upsert_agent")

    async def _fake_list_agent_files(self, agent_id):
        call_log.append("list_agent_files")
        # Return credentials visible so verify_credentials_visible passes
        return {
            "BOOTSTRAP.md": {"name": "BOOTSTRAP.md", "missing": False},
            "TOOLS.md": {"name": "TOOLS.md", "missing": False},
        }

    def _fake_render_agent_files(*args, **kwargs):
        return {"TOOLS.md": "contents", "BOOTSTRAP.md": "contents"}

    async def _fake_set_agent_files(self, **kwargs):
        call_log.append("set_agent_files")

    async def _fake_ensure_session(session_key, *, config, label=None):
        call_log.append("ensure_session")

    async def _fake_send_message(text, *, session_key, config, deliver):
        call_log.append("send_message")

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "ensure_agent_session",
        _fake_ensure_agent_session,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "upsert_agent",
        _fake_upsert_agent,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "_render_agent_files", _fake_render_agent_files)

    async def _fake_openclaw_call(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(
        agent_provisioning.BaseAgentLifecycleManager,
        "_set_agent_files",
        _fake_set_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "ensure_session", _fake_ensure_session)
    monkeypatch.setattr(agent_provisioning, "send_message", _fake_send_message)

    await agent_provisioning.OpenClawGatewayProvisioner().apply_agent_lifecycle(
        agent=agent,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        board=None,
        auth_token="secret-token",
        user=None,
        action="provision",
        wake=True,
    )

    assert "set_agent_files" in call_log, f"file sync must run; got {call_log}"
    assert "send_message" in call_log, f"wake must be delivered; got {call_log}"
    set_idx = call_log.index("set_agent_files")
    send_idx = call_log.index("send_message")
    assert set_idx < send_idx, (
        f"set_agent_files must run before send_message, but got {call_log}"
    )
    # verify_credentials_visible runs list_agent_files AFTER file sync
    # and BEFORE send_message — this is the read-back check that
    # guarantees the wake text has a valid credential source to quote.
    post_write_list = [
        i
        for i, name in enumerate(call_log)
        if name == "list_agent_files" and set_idx < i < send_idx
    ]
    assert post_write_list, (
        "verify_credentials_visible must call list_agent_files between "
        f"set_agent_files and send_message; got {call_log}"
    )


@pytest.mark.asyncio
async def test_apply_agent_lifecycle_skips_wake_when_credentials_missing(monkeypatch):
    """Regression: if the gateway cannot see BOOTSTRAP.md or TOOLS.md after
    the file sync step, the wake must be skipped entirely. Sending the
    wake anyway would instruct the agent to read credentials from files
    that aren't there, guaranteeing a NO_REPLY and burning a retry.
    """
    gateway_id = uuid4()
    session_key = GatewayAgentIdentity.session_key_for_id(gateway_id)
    gateway = _GatewayStub(
        id=gateway_id,
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = _AgentStub(name="Acme Gateway Agent", openclaw_session_id=session_key)

    call_log: list[str] = []

    async def _fake_ensure_agent_session(self, session_key, *, label=None):
        call_log.append("ensure_agent_session")

    async def _fake_upsert_agent(self, registration):
        call_log.append("upsert_agent")

    async def _fake_list_agent_files(self, agent_id):
        call_log.append("list_agent_files")
        # Simulate a broken file sync: credentials NOT visible on gateway.
        return {"USER.md": {"name": "USER.md", "missing": False}}

    def _fake_render_agent_files(*args, **kwargs):
        return {"TOOLS.md": "contents", "BOOTSTRAP.md": "contents"}

    async def _fake_set_agent_files(self, **kwargs):
        call_log.append("set_agent_files")

    async def _fake_ensure_session(session_key, *, config, label=None):
        call_log.append("ensure_session")

    async def _fake_send_message(text, *, session_key, config, deliver):
        call_log.append("send_message")

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "ensure_agent_session",
        _fake_ensure_agent_session,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "upsert_agent",
        _fake_upsert_agent,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "_render_agent_files", _fake_render_agent_files)

    async def _fake_openclaw_call(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(
        agent_provisioning.BaseAgentLifecycleManager,
        "_set_agent_files",
        _fake_set_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "ensure_session", _fake_ensure_session)
    monkeypatch.setattr(agent_provisioning, "send_message", _fake_send_message)

    result = await agent_provisioning.OpenClawGatewayProvisioner().apply_agent_lifecycle(
        agent=agent,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        board=None,
        auth_token="secret-token",
        user=None,
        action="provision",
        wake=True,
    )

    assert "set_agent_files" in call_log, f"file sync must still run; got {call_log}"
    assert "send_message" not in call_log, (
        "wake must be skipped when neither BOOTSTRAP.md nor TOOLS.md is "
        f"visible on the gateway; got {call_log}"
    )
    assert result.wake_delivered is False, (
        "LifecycleResult.wake_delivered must be False when the wake was "
        "skipped due to missing credentials — the orchestrator uses this "
        "flag to decide whether to consume a wake_attempts strike"
    )
    assert result.wake_skip_reason == "credentials_not_visible", (
        "skip reason must be set so last_provision_error can describe "
        f"the skip; got {result.wake_skip_reason!r}"
    )


@pytest.mark.asyncio
async def test_apply_agent_lifecycle_returns_wake_delivered_true_on_success(monkeypatch):
    """Positive-path regression for the LifecycleResult contract. When the
    wake is actually delivered, the result must report
    ``wake_delivered=True`` with no skip reason, so the orchestrator
    knows it is safe to consume a wake_attempts strike, arm a check-in
    deadline, mark the agent online, and enqueue the reconcile task.
    """
    gateway_id = uuid4()
    session_key = GatewayAgentIdentity.session_key_for_id(gateway_id)
    gateway = _GatewayStub(
        id=gateway_id,
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = _AgentStub(name="Acme Gateway Agent", openclaw_session_id=session_key)

    async def _fake_ensure_agent_session(self, session_key, *, label=None):
        return None

    async def _fake_upsert_agent(self, registration):
        return None

    async def _fake_list_agent_files(self, agent_id):
        return {
            "BOOTSTRAP.md": {"name": "BOOTSTRAP.md", "missing": False, "size": 42},
            "TOOLS.md": {"name": "TOOLS.md", "missing": False, "size": 128},
        }

    def _fake_render_agent_files(*args, **kwargs):
        return {"TOOLS.md": "contents", "BOOTSTRAP.md": "contents"}

    async def _fake_set_agent_files(self, **kwargs):
        return None

    async def _fake_ensure_session(session_key, *, config, label=None):
        return None

    async def _fake_send_message(text, *, session_key, config, deliver):
        return None

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "ensure_agent_session",
        _fake_ensure_agent_session,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "upsert_agent",
        _fake_upsert_agent,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "_render_agent_files", _fake_render_agent_files)

    async def _fake_openclaw_call(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(
        agent_provisioning.BaseAgentLifecycleManager,
        "_set_agent_files",
        _fake_set_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "ensure_session", _fake_ensure_session)
    monkeypatch.setattr(agent_provisioning, "send_message", _fake_send_message)

    result = await agent_provisioning.OpenClawGatewayProvisioner().apply_agent_lifecycle(
        agent=agent,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        board=None,
        auth_token="secret-token",
        user=None,
        action="provision",
        wake=True,
    )

    assert result.wake_delivered is True
    assert result.wake_skip_reason is None


@pytest.mark.asyncio
async def test_apply_agent_lifecycle_returns_wake_delivered_false_when_wake_not_requested(
    monkeypatch,
):
    """``wake=False`` must also yield ``wake_delivered=False`` (a wake
    that was never requested is indistinguishable from one that was
    skipped, from the caller's perspective — neither should cause
    wake-state mutations)."""
    gateway_id = uuid4()
    session_key = GatewayAgentIdentity.session_key_for_id(gateway_id)
    gateway = _GatewayStub(
        id=gateway_id,
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = _AgentStub(name="Acme Gateway Agent", openclaw_session_id=session_key)

    async def _fake_ensure_agent_session(self, session_key, *, label=None):
        return None

    async def _fake_upsert_agent(self, registration):
        return None

    async def _fake_list_agent_files(self, agent_id):
        return {}

    def _fake_render_agent_files(*args, **kwargs):
        return {}

    async def _fake_set_agent_files(self, **kwargs):
        return None

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "ensure_agent_session",
        _fake_ensure_agent_session,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "upsert_agent",
        _fake_upsert_agent,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "_render_agent_files", _fake_render_agent_files)

    async def _fake_openclaw_call(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(
        agent_provisioning.BaseAgentLifecycleManager,
        "_set_agent_files",
        _fake_set_agent_files,
    )

    result = await agent_provisioning.OpenClawGatewayProvisioner().apply_agent_lifecycle(
        agent=agent,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        board=None,
        auth_token="secret-token",
        user=None,
        action="provision",
        wake=False,
    )

    assert result.wake_delivered is False
    assert result.wake_skip_reason is None, (
        "wake=False is not a 'skip', it is a 'not requested' — skip "
        "reason should be None to distinguish the two cases"
    )


@pytest.mark.asyncio
async def test_verify_credentials_visible_retries_on_transient_empty_list(monkeypatch):
    """Regression: ``verify_credentials_visible`` must retry a few times
    before concluding credentials are not visible, because the gateway's
    ``agents.files.list`` RPC can briefly return a stale view right
    after a write. Without retries, a transient propagation lag would
    falsely skip a wake.
    """
    agent = _AgentStub(name="Worker", openclaw_session_id="agent:worker:main")
    attempts: list[int] = []

    async def _fake_list_agent_files(self, agent_id):
        attempts.append(len(attempts))
        # First two attempts return nothing; third attempt sees TOOLS.md.
        if len(attempts) < 3:
            return {}
        return {"TOOLS.md": {"name": "TOOLS.md", "missing": False, "size": 64}}

    async def _fake_sleep(seconds):
        return None

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning.asyncio, "sleep", _fake_sleep)

    class _ConcreteManager(agent_provisioning.BaseAgentLifecycleManager):
        def _agent_id(self, agent):
            return "worker-agent-id"

        def _build_context(self, *, agent, auth_token, user, board):
            return {}

    gateway = _GatewayStub(
        id=uuid4(),
        name="G",
        url="ws://gw",
        token=None,
        workspace_root="/tmp",
    )
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gw", token=None),
    )
    manager = _ConcreteManager(gateway, cp)  # type: ignore[arg-type]

    visible, present = await manager.verify_credentials_visible(
        agent=agent,  # type: ignore[arg-type]
        backoff_seconds=0.0,  # no real sleep in tests
    )

    assert visible is True
    assert "TOOLS.md" in present
    assert len(attempts) == 3, f"expected 3 retries, got {len(attempts)}"


@pytest.mark.asyncio
async def test_verify_credentials_visible_rejects_zero_byte_files(monkeypatch):
    """Regression: a zero-byte credential file must not count as visible.
    The curl in the wake text reads ``$AUTH_TOKEN`` from the file; an
    empty file gives the agent no token and causes a silent auth 4xx.
    """
    agent = _AgentStub(name="Worker", openclaw_session_id="agent:worker:main")

    async def _fake_list_agent_files(self, agent_id):
        return {
            "BOOTSTRAP.md": {"name": "BOOTSTRAP.md", "missing": False, "size": 0},
            "TOOLS.md": {"name": "TOOLS.md", "missing": False, "size": 0},
        }

    async def _fake_sleep(seconds):
        return None

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning.asyncio, "sleep", _fake_sleep)

    class _ConcreteManager(agent_provisioning.BaseAgentLifecycleManager):
        def _agent_id(self, agent):
            return "worker-agent-id"

        def _build_context(self, *, agent, auth_token, user, board):
            return {}

    gateway = _GatewayStub(
        id=uuid4(),
        name="G",
        url="ws://gw",
        token=None,
        workspace_root="/tmp",
    )
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gw", token=None),
    )
    manager = _ConcreteManager(gateway, cp)  # type: ignore[arg-type]

    visible, present = await manager.verify_credentials_visible(
        agent=agent,  # type: ignore[arg-type]
        backoff_seconds=0.0,
    )

    assert visible is False, (
        "zero-byte credential files must not count as visible — the curl "
        "needs a real token to work"
    )
    assert present == set()


@pytest.mark.asyncio
async def test_provision_main_agent_uses_dedicated_openclaw_agent_id(monkeypatch):
    gateway_id = uuid4()
    session_key = GatewayAgentIdentity.session_key_for_id(gateway_id)
    gateway = _GatewayStub(
        id=gateway_id,
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = _AgentStub(name="Acme Gateway Agent", openclaw_session_id=session_key)
    captured: dict[str, object] = {}

    async def _fake_ensure_agent_session(self, session_key, *, label=None):
        return None

    async def _fake_upsert_agent(self, registration):
        captured["patched_agent_id"] = registration.agent_id
        captured["workspace_path"] = registration.workspace_path

    async def _fake_list_agent_files(self, agent_id):
        captured["files_index_agent_id"] = agent_id
        return {}

    def _fake_render_agent_files(*args, **kwargs):
        return {}

    async def _fake_set_agent_files(self, **kwargs):
        return None

    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "ensure_agent_session",
        _fake_ensure_agent_session,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "upsert_agent",
        _fake_upsert_agent,
    )
    monkeypatch.setattr(
        agent_provisioning.OpenClawGatewayControlPlane,
        "list_agent_files",
        _fake_list_agent_files,
    )
    monkeypatch.setattr(agent_provisioning, "_render_agent_files", _fake_render_agent_files)

    async def _fake_openclaw_call(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)

    async def _fake_openclaw_call(*args, **kwargs):
        return {"ok": True, "enabled": True}
    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(
        agent_provisioning.BaseAgentLifecycleManager,
        "_set_agent_files",
        _fake_set_agent_files,
    )

    await agent_provisioning.OpenClawGatewayProvisioner().apply_agent_lifecycle(
        agent=agent,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        board=None,
        auth_token="secret-token",
        user=None,
        action="provision",
        wake=False,
    )

    expected_agent_id = GatewayAgentIdentity.openclaw_agent_id_for_id(gateway_id)
    assert captured["patched_agent_id"] == expected_agent_id
    assert captured["files_index_agent_id"] == expected_agent_id


@pytest.mark.asyncio
async def test_provision_overwrites_user_md_on_first_provision(monkeypatch):
    """Gateway may pre-create USER.md; we still want MC's template on first provision."""

    class _ControlPlaneStub:
        def __init__(self):
            self.writes: list[tuple[str, str]] = []

        async def ensure_agent_session(self, session_key, *, label=None):
            return None

        async def reset_agent_session(self, session_key):
            return None

        async def delete_agent_session(self, session_key):
            return None

        async def upsert_agent(self, registration):
            return None

        async def delete_agent(self, agent_id, *, delete_files=True):
            return None

        async def list_agent_files(self, agent_id):
            # Pretend gateway created USER.md already.
            return {"USER.md": {"name": "USER.md", "missing": False}}

        async def set_agent_file(self, *, agent_id, name, content):
            self.writes.append((name, content))

        async def patch_agent_heartbeats(self, entries):
            return None

    @dataclass
    class _GatewayTiny:
        id: UUID
        name: str
        url: str
        token: str | None
        workspace_root: str
        allow_insecure_tls: bool = False
        disable_device_pairing: bool = False

    class _Manager(agent_provisioning.BaseAgentLifecycleManager):
        def _agent_id(self, agent):
            return "agent-x"

        def _build_context(self, *, agent, auth_token, user, board):
            return {}

    gateway = _GatewayTiny(
        id=uuid4(),
        name="G",
        url="ws://x",
        token=None,
        workspace_root="/tmp",
    )
    cp = _ControlPlaneStub()
    mgr = _Manager(gateway, cp)  # type: ignore[arg-type]

    # Rendered content is non-empty; action is "provision" so we should overwrite.
    await mgr._set_agent_files(
        agent_id="agent-x",
        rendered={"USER.md": "from-mc"},
        existing_files={"USER.md": {"name": "USER.md", "missing": False}},
        action="provision",
    )
    assert ("USER.md", "from-mc") in cp.writes


@pytest.mark.asyncio
async def test_set_agent_files_update_preserves_user_md_even_when_size_zero():
    """Update should preserve editable files unless overwrite is explicitly requested."""

    class _ControlPlaneStub:
        def __init__(self):
            self.writes: list[tuple[str, str]] = []

        async def ensure_agent_session(self, session_key, *, label=None):
            return None

        async def reset_agent_session(self, session_key):
            return None

        async def delete_agent_session(self, session_key):
            return None

        async def upsert_agent(self, registration):
            return None

        async def delete_agent(self, agent_id, *, delete_files=True):
            return None

        async def list_agent_files(self, agent_id):
            return {}

        async def set_agent_file(self, *, agent_id, name, content):
            self.writes.append((name, content))

        async def patch_agent_heartbeats(self, entries):
            return None

    @dataclass
    class _GatewayTiny:
        id: UUID
        name: str
        url: str
        token: str | None
        workspace_root: str
        allow_insecure_tls: bool = False
        disable_device_pairing: bool = False

    class _Manager(agent_provisioning.BaseAgentLifecycleManager):
        def _agent_id(self, agent):
            return "agent-x"

        def _build_context(self, *, agent, auth_token, user, board):
            return {}

    gateway = _GatewayTiny(
        id=uuid4(),
        name="G",
        url="ws://x",
        token=None,
        workspace_root="/tmp",
    )
    cp = _ControlPlaneStub()
    mgr = _Manager(gateway, cp)  # type: ignore[arg-type]

    await mgr._set_agent_files(
        agent_id="agent-x",
        rendered={"USER.md": "filled"},
        existing_files={"USER.md": {"name": "USER.md", "missing": False, "size": 0}},
        action="update",
    )
    assert cp.writes == []


@pytest.mark.asyncio
async def test_set_agent_files_update_preserves_nonmissing_user_md():
    class _ControlPlaneStub:
        def __init__(self):
            self.writes: list[tuple[str, str]] = []

        async def ensure_agent_session(self, session_key, *, label=None):
            return None

        async def reset_agent_session(self, session_key):
            return None

        async def delete_agent_session(self, session_key):
            return None

        async def upsert_agent(self, registration):
            return None

        async def delete_agent(self, agent_id, *, delete_files=True):
            return None

        async def list_agent_files(self, agent_id):
            return {}

        async def set_agent_file(self, *, agent_id, name, content):
            self.writes.append((name, content))

        async def patch_agent_heartbeats(self, entries):
            return None

    @dataclass
    class _GatewayTiny:
        id: UUID
        name: str
        url: str
        token: str | None
        workspace_root: str
        allow_insecure_tls: bool = False
        disable_device_pairing: bool = False

    class _Manager(agent_provisioning.BaseAgentLifecycleManager):
        def _agent_id(self, agent):
            return "agent-x"

        def _build_context(self, *, agent, auth_token, user, board):
            return {}

    gateway = _GatewayTiny(
        id=uuid4(),
        name="G",
        url="ws://x",
        token=None,
        workspace_root="/tmp",
    )
    cp = _ControlPlaneStub()
    mgr = _Manager(gateway, cp)  # type: ignore[arg-type]

    await mgr._set_agent_files(
        agent_id="agent-x",
        rendered={"USER.md": "filled"},
        existing_files={"USER.md": {"name": "USER.md", "missing": False}},
        action="update",
    )
    assert cp.writes == []


@pytest.mark.asyncio
async def test_set_agent_files_update_overwrite_writes_preserved_user_md():
    class _ControlPlaneStub:
        def __init__(self):
            self.writes: list[tuple[str, str]] = []

        async def ensure_agent_session(self, session_key, *, label=None):
            return None

        async def reset_agent_session(self, session_key):
            return None

        async def delete_agent_session(self, session_key):
            return None

        async def upsert_agent(self, registration):
            return None

        async def delete_agent(self, agent_id, *, delete_files=True):
            return None

        async def list_agent_files(self, agent_id):
            return {}

        async def set_agent_file(self, *, agent_id, name, content):
            self.writes.append((name, content))

        async def patch_agent_heartbeats(self, entries):
            return None

    @dataclass
    class _GatewayTiny:
        id: UUID
        name: str
        url: str
        token: str | None
        workspace_root: str
        allow_insecure_tls: bool = False
        disable_device_pairing: bool = False

    class _Manager(agent_provisioning.BaseAgentLifecycleManager):
        def _agent_id(self, agent):
            return "agent-x"

        def _build_context(self, *, agent, auth_token, user, board):
            return {}

    gateway = _GatewayTiny(
        id=uuid4(),
        name="G",
        url="ws://x",
        token=None,
        workspace_root="/tmp",
    )
    cp = _ControlPlaneStub()
    mgr = _Manager(gateway, cp)  # type: ignore[arg-type]

    await mgr._set_agent_files(
        agent_id="agent-x",
        rendered={"USER.md": "filled"},
        existing_files={"USER.md": {"name": "USER.md", "missing": False}},
        action="update",
        overwrite=True,
    )
    assert ("USER.md", "filled") in cp.writes


@pytest.mark.asyncio
async def test_control_plane_upsert_agent_create_then_update(monkeypatch):
    calls: list[tuple[str, dict[str, object] | None]] = []

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        calls.append((method, params))
        if method == "agents.create":
            return {"ok": True}
        if method == "agents.update":
            return {"ok": True}
        if method == "config.get":
            return {"hash": None, "config": {"agents": {"list": []}}}
        if method == "config.patch":
            return {"ok": True}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )
    await cp.upsert_agent(
        agent_provisioning.GatewayAgentRegistration(
            agent_id="board-agent-a",
            name="Board Agent A",
            workspace_path="/tmp/workspace-board-agent-a",
            heartbeat={"every": "10m", "target": "last", "includeReasoning": False},
        ),
    )

    assert calls[0][0] == "agents.create"
    assert calls[1][0] == "agents.update"


@pytest.mark.asyncio
async def test_control_plane_upsert_agent_handles_already_exists(monkeypatch):
    calls: list[tuple[str, dict[str, object] | None]] = []

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        calls.append((method, params))
        if method == "agents.create":
            raise agent_provisioning.OpenClawGatewayError("already exists")
        if method == "agents.update":
            return {"ok": True}
        if method == "config.get":
            return {"hash": None, "config": {"agents": {"list": []}}}
        if method == "config.patch":
            return {"ok": True}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )
    await cp.upsert_agent(
        agent_provisioning.GatewayAgentRegistration(
            agent_id="board-agent-a",
            name="Board Agent A",
            workspace_path="/tmp/workspace-board-agent-a",
            heartbeat={"every": "10m", "target": "last", "includeReasoning": False},
        ),
    )

    assert calls[0][0] == "agents.create"
    assert calls[1][0] == "agents.update"


@pytest.mark.asyncio
async def test_control_plane_upsert_agent_retries_update_after_create_race(monkeypatch):
    calls: list[tuple[str, dict[str, object] | None]] = []
    sleeps: list[float] = []
    update_attempts = 0

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def _fake_openclaw_call(method, params=None, config=None):
        nonlocal update_attempts
        _ = config
        calls.append((method, params))
        if method == "agents.create":
            return {"ok": True}
        if method == "agents.update":
            update_attempts += 1
            if update_attempts < 3:
                raise agent_provisioning.OpenClawGatewayError('agent "board-agent-a" not found')
            return {"ok": True}
        if method == "config.get":
            return {"hash": None, "config": {"agents": {"list": []}}}
        if method == "config.patch":
            return {"ok": True}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(agent_provisioning.asyncio, "sleep", _fake_sleep)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )
    await cp.upsert_agent(
        agent_provisioning.GatewayAgentRegistration(
            agent_id="board-agent-a",
            name="Board Agent A",
            workspace_path="/tmp/workspace-board-agent-a",
            heartbeat={"every": "10m", "target": "last", "includeReasoning": False},
        ),
    )

    update_calls = [method for method, _ in calls if method == "agents.update"]
    assert len(update_calls) == 3
    assert sleeps == [0.75, 0.5, 1.0]


@pytest.mark.asyncio
async def test_patch_agent_heartbeats_skips_config_patch_for_disabled_semantic_match(monkeypatch):
    calls: list[tuple[str, dict[str, object] | None]] = []

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        calls.append((method, params))
        if method == "config.get":
            return {
                "hash": "abc123",
                "config": {
                    "agents": {
                        "list": [
                            {
                                "id": "mc-disabled",
                                "workspace": "/tmp/workspace-mc-disabled",
                                "heartbeat": {"every": "disabled"},
                            }
                        ]
                    },
                    "channels": {
                        "defaults": {
                            "heartbeat": {
                                "showOk": False,
                                "showAlerts": True,
                                "useIndicator": True,
                            }
                        }
                    },
                    "tools": {"exec": {"host": "gateway"}},
                },
            }
        if method == "config.patch":
            raise AssertionError("config.patch should be skipped")
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )

    await cp.patch_agent_heartbeats(
        [
            (
                "mc-disabled",
                "/tmp/workspace-mc-disabled",
                {"every": "0m", "target": "last", "includeReasoning": False},
            )
        ],
    )

    assert [method for method, _ in calls] == ["config.get"]


@pytest.mark.asyncio
async def test_patch_agent_heartbeats_adds_openclaw_426_runtime_guardrails(monkeypatch):
    calls: list[tuple[str, dict[str, object] | None]] = []

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        calls.append((method, params))
        if method == "config.get":
            return {
                "hash": "h-426",
                "config": {
                    "agents": {
                        "defaults": {
                            "compaction": {
                                "mode": "safeguard",
                                "model": "ollama/qwen3.5:cloud",
                                "notifyUser": False,
                            },
                            "subagents": {"maxConcurrent": 8, "runTimeoutSeconds": True},
                        },
                        "list": [
                            {
                                "id": "agent-x",
                                "workspace": "/tmp/workspace-agent-x",
                                "heartbeat": {"every": "10m"},
                            },
                        ],
                    },
                    "acp": {"dispatch": {"enabled": True}},
                    "channels": {
                        "defaults": {
                            "heartbeat": {
                                "showOk": False,
                                "showAlerts": True,
                                "useIndicator": True,
                            }
                        }
                    },
                    "tools": {"exec": {"host": "gateway"}},
                },
            }
        if method == "config.patch":
            return {"ok": True}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )

    await cp.patch_agent_heartbeats(
        [
            (
                "agent-x",
                "/tmp/workspace-agent-x",
                {"every": "10m"},
            )
        ],
    )

    assert [method for method, _ in calls] == ["config.get", "config.patch"]
    patch_params = calls[1][1]
    assert isinstance(patch_params, dict)
    assert patch_params["baseHash"] == "h-426"
    raw = patch_params["raw"]
    assert isinstance(raw, str)
    patch = json.loads(raw)

    compaction = patch["agents"]["defaults"]["compaction"]
    assert compaction["mode"] == "safeguard"
    assert compaction["model"] == "ollama/qwen3.5:cloud"
    assert compaction["notifyUser"] is False
    assert compaction["truncateAfterCompaction"] is True
    assert compaction["maxActiveTranscriptBytes"] == "20mb"

    subagents = patch["agents"]["defaults"]["subagents"]
    assert subagents["maxConcurrent"] == 8
    assert subagents["allowAgents"] == ["claude", "codex"]
    assert subagents["requireAgentId"] is True
    assert subagents["runTimeoutSeconds"] == 3600
    assert subagents["archiveAfterMinutes"] == 120

    assert patch["acp"]["dispatch"]["enabled"] is False


@pytest.mark.asyncio
async def test_patch_agent_heartbeats_preserves_existing_openclaw_426_runtime_choices(
    monkeypatch,
):
    calls: list[tuple[str, dict[str, object] | None]] = []

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        calls.append((method, params))
        if method == "config.get":
            return {
                "hash": "h-existing",
                "config": {
                    "agents": {
                        "defaults": {
                            "compaction": {
                                "truncateAfterCompaction": True,
                                "maxActiveTranscriptBytes": "64mb",
                            },
                            "subagents": {
                                "maxConcurrent": 8,
                                "allowAgents": ["research", "claude"],
                                "requireAgentId": True,
                                "runTimeoutSeconds": 1800,
                                "archiveAfterMinutes": 45,
                            },
                        },
                        "list": [
                            {
                                "id": "agent-x",
                                "workspace": "/tmp/workspace-agent-x",
                                "heartbeat": {"every": "10m"},
                            },
                        ],
                    },
                    "acp": {"dispatch": {"enabled": False}},
                    "channels": {
                        "defaults": {
                            "heartbeat": {
                                "showOk": False,
                                "showAlerts": True,
                                "useIndicator": True,
                            }
                        }
                    },
                    "tools": {"exec": {"host": "gateway"}},
                },
            }
        if method == "config.patch":
            return {"ok": True}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )

    await cp.patch_agent_heartbeats(
        [
            (
                "agent-x",
                "/tmp/workspace-agent-x",
                {"every": "10m"},
            )
        ],
    )

    assert [method for method, _ in calls] == ["config.get", "config.patch"]
    patch_params = calls[1][1]
    assert isinstance(patch_params, dict)
    raw = patch_params["raw"]
    assert isinstance(raw, str)
    patch = json.loads(raw)

    assert "compaction" not in patch["agents"]["defaults"]

    subagents = patch["agents"]["defaults"]["subagents"]
    assert subagents["allowAgents"] == ["research", "claude", "codex"]
    assert subagents["runTimeoutSeconds"] == 1800
    assert subagents["archiveAfterMinutes"] == 45


@pytest.mark.asyncio
async def test_control_plane_upsert_agent_missing_after_already_exists_fails_fast(monkeypatch):
    calls: list[tuple[str, dict[str, object] | None]] = []
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        calls.append((method, params))
        if method == "agents.create":
            raise agent_provisioning.OpenClawGatewayError("already exists")
        if method == "agents.update":
            raise agent_provisioning.OpenClawGatewayError('agent "board-agent-a" not found')
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr(agent_provisioning.asyncio, "sleep", _fake_sleep)
    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )

    with pytest.raises(agent_provisioning.OpenClawGatewayError):
        await cp.upsert_agent(
            agent_provisioning.GatewayAgentRegistration(
                agent_id="board-agent-a",
                name="Board Agent A",
                workspace_path="/tmp/workspace-board-agent-a",
                heartbeat={"every": "10m", "target": "last", "includeReasoning": False},
            ),
        )

    update_calls = [method for method, _ in calls if method == "agents.update"]
    assert len(update_calls) == 1
    assert sleeps == []


def test_is_missing_agent_error_matches_gateway_agent_not_found() -> None:
    assert agent_provisioning._is_missing_agent_error(
        agent_provisioning.OpenClawGatewayError('agent "mc-abc" not found'),
    )
    assert not agent_provisioning._is_missing_agent_error(
        agent_provisioning.OpenClawGatewayError("dial tcp: connection refused"),
    )


def test_select_role_soul_ref_prefers_exact_slug() -> None:
    refs = [
        SoulRef(handle="team", slug="security"),
        SoulRef(handle="team", slug="security-auditor"),
        SoulRef(handle="team", slug="security-auditor-pro"),
    ]

    selected = agent_provisioning._select_role_soul_ref(refs, role="Security Auditor")

    assert selected is not None
    assert selected.slug == "security-auditor"


@pytest.mark.asyncio
async def test_resolve_role_soul_markdown_returns_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = [SoulRef(handle="team", slug="data-scientist")]

    async def _fake_list_refs() -> list[SoulRef]:
        return refs

    async def _fake_fetch(*, handle: str, slug: str, client=None) -> str:
        _ = client
        assert handle == "team"
        assert slug == "data-scientist"
        return "# SOUL.md - Data Scientist"

    monkeypatch.setattr(
        agent_provisioning.souls_directory,
        "list_souls_directory_refs",
        _fake_list_refs,
    )
    monkeypatch.setattr(
        agent_provisioning.souls_directory,
        "fetch_soul_markdown",
        _fake_fetch,
    )

    markdown, source_url = await agent_provisioning._resolve_role_soul_markdown("Data Scientist")

    assert markdown == "# SOUL.md - Data Scientist"
    assert source_url == "https://souls.directory/souls/team/data-scientist"


@pytest.mark.asyncio
async def test_resolve_role_soul_markdown_returns_empty_on_directory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_list_refs() -> list[SoulRef]:
        raise RuntimeError("network down")

    monkeypatch.setattr(
        agent_provisioning.souls_directory,
        "list_souls_directory_refs",
        _fake_list_refs,
    )

    markdown, source_url = await agent_provisioning._resolve_role_soul_markdown("DevOps Engineer")

    assert markdown == ""
    assert source_url == ""


@pytest.mark.asyncio
async def test_delete_agent_lifecycle_ignores_missing_gateway_agent(monkeypatch) -> None:
    class _ControlPlaneStub:
        def __init__(self) -> None:
            self.deleted_sessions: list[str] = []

        async def delete_agent(self, agent_id: str, *, delete_files: bool = True) -> None:
            _ = (agent_id, delete_files)
            raise agent_provisioning.OpenClawGatewayError('agent "mc-abc" not found')

        async def delete_agent_session(self, session_key: str) -> None:
            self.deleted_sessions.append(session_key)

    gateway = _GatewayStub(
        id=uuid4(),
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = SimpleNamespace(
        id=uuid4(),
        name="Worker",
        board_id=uuid4(),
        openclaw_session_id=None,
        is_board_lead=False,
    )
    control_plane = _ControlPlaneStub()
    monkeypatch.setattr(agent_provisioning, "_control_plane_for_gateway", lambda _g: control_plane)

    await agent_provisioning.OpenClawGatewayProvisioner().delete_agent_lifecycle(
        agent=agent,  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        delete_files=True,
        delete_session=True,
    )

    assert len(control_plane.deleted_sessions) == 1


@pytest.mark.asyncio
async def test_delete_agent_lifecycle_raises_on_non_missing_agent_error(monkeypatch) -> None:
    class _ControlPlaneStub:
        async def delete_agent(self, agent_id: str, *, delete_files: bool = True) -> None:
            _ = (agent_id, delete_files)
            raise agent_provisioning.OpenClawGatewayError("gateway timeout")

        async def delete_agent_session(self, session_key: str) -> None:
            _ = session_key
            raise AssertionError("delete_agent_session should not be called")

    gateway = _GatewayStub(
        id=uuid4(),
        name="Acme",
        url="ws://gateway.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
    )
    agent = SimpleNamespace(
        id=uuid4(),
        name="Worker",
        board_id=uuid4(),
        openclaw_session_id=None,
        is_board_lead=False,
    )
    monkeypatch.setattr(
        agent_provisioning,
        "_control_plane_for_gateway",
        lambda _g: _ControlPlaneStub(),
    )

    with pytest.raises(agent_provisioning.OpenClawGatewayError):
        await agent_provisioning.OpenClawGatewayProvisioner().delete_agent_lifecycle(
            agent=agent,  # type: ignore[arg-type]
            gateway=gateway,  # type: ignore[arg-type]
            delete_files=True,
            delete_session=True,
        )


def test_default_heartbeat_config_has_isolation():
    from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG

    assert DEFAULT_HEARTBEAT_CONFIG["isolatedSession"] is True
    # Regression guard: lightContext MUST remain False. In lightweight
    # mode the gateway strips every bootstrap file except HEARTBEAT.md,
    # so the heartbeat session cannot resolve $BASE_URL / $AUTH_TOKEN /
    # $BOARD_ID, cannot read AGENTS.md/IDENTITY.md/MEMORY.md, and cannot
    # execute any check-in curl or follow any operating rule. This was a
    # real production incident in April 2026 (commit e37a34e flipped to
    # True for token savings and caused 22 heartbeat "ok" events with
    # zero nudges — see docs/NOTES.md §"Why the Supervisor heartbeat
    # says OK without nudging"). The post-refactor templates assume full
    # bootstrap context; flipping this default back to True MUST NOT
    # happen without also redesigning every template to be fully self-
    # contained in HEARTBEAT.md.
    assert DEFAULT_HEARTBEAT_CONFIG["lightContext"] is False


def test_board_lead_heartbeat_config_preserves_isolated_session():
    agent = _AgentStub(
        name="Supervisor",
        heartbeat_config={"isolatedSession": True, "lightContext": False},
        is_board_lead=True,
    )

    heartbeat = agent_provisioning._heartbeat_config(agent)  # type: ignore[arg-type]

    assert heartbeat["isolatedSession"] is True


def test_offline_threshold_exceeds_max_heartbeat():
    from app.core.durations import parse_every_to_seconds
    from app.services.openclaw.constants import (
        DEFAULT_HEARTBEAT_CONFIG,
        HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
        OFFLINE_AFTER,
    )

    configured_interval = parse_every_to_seconds(DEFAULT_HEARTBEAT_CONFIG["every"])
    assert OFFLINE_AFTER.total_seconds() > (
        configured_interval + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL.total_seconds()
    )


def test_offline_threshold_covers_30m_heartbeat_agents():
    """Regression: 30m-heartbeat agents must not be falsely marked offline."""
    from app.services.openclaw.constants import (
        HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
        OFFLINE_AFTER,
    )
    from app.core.durations import parse_every_to_seconds

    max_worker_interval = parse_every_to_seconds("30m")
    assert OFFLINE_AFTER.total_seconds() > (
        max_worker_interval + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL.total_seconds()
    )


@pytest.mark.asyncio
async def test_patch_agent_heartbeats_routes_through_openclaw_call(monkeypatch):
    # OpenClaw 2026.4.14 (#62006) made the model-facing gateway tool reject
    # config.patch/config.apply calls that newly enable dangerous flags.
    # MC's direct authenticated operator RPC path is unaffected, but only
    # while patch_agent_heartbeats keeps routing through openclaw_call().
    # This is the structural regression test: it exercises the real
    # provisioning caller (not the openclaw_call helper in isolation) and
    # asserts every gateway interaction goes through provisioning.openclaw_call,
    # not through any model-facing tool wrapper.
    from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
    from app.services.openclaw.provisioning import OpenClawGatewayControlPlane

    calls: list[tuple[str, object]] = []

    async def _fake_openclaw_call(method, params=None, *, config):
        del config
        calls.append((method, params))
        if method == "config.get":
            return {
                "hash": "h-base",
                "config": {
                    "agents": {
                        "list": [
                            {
                                "id": "agent-x",
                                "workspace": "/old/ws",
                                "heartbeat": {"every": "10m"},
                            },
                        ],
                    },
                },
            }
        if method == "config.patch":
            return {"ok": True}
        msg = f"unexpected gateway method: {method}"
        raise AssertionError(msg)

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)

    control_plane = OpenClawGatewayControlPlane(
        config=GatewayClientConfig(url="ws://gateway.example/ws"),
    )

    await control_plane.patch_agent_heartbeats(
        entries=[("agent-x", "/new/ws", {"every": "5m"})],
    )

    methods = [call[0] for call in calls]
    assert "config.get" in methods, "patch_agent_heartbeats must read config first"
    assert "config.patch" in methods, (
        "patch_agent_heartbeats must apply via config.patch through openclaw_call; "
        "if MC ever drifts to a model-facing tool wrapper, OpenClaw 4.14 #62006 "
        "would reject dangerous-flag changes silently"
    )
    # No other RPC methods should be involved in this code path. If a future
    # change adds one (e.g. a tool-facing wrapper, a session.* call, etc.),
    # make sure the new path is also operator-trusted before relaxing this.
    assert set(methods) == {"config.get", "config.patch"}, (
        f"unexpected gateway RPCs in patch_agent_heartbeats path: {methods}"
    )

    patch_call = next(call for call in calls if call[0] == "config.patch")
    patch_params = patch_call[1]
    assert isinstance(patch_params, dict)
    assert "raw" in patch_params, "config.patch must carry the 'raw' JSON payload"
    assert patch_params.get("baseHash") == "h-base", (
        "config.patch must include baseHash from the prior config.get for "
        "optimistic concurrency"
    )
