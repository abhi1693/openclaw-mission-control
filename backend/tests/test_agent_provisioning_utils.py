# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app.services.openclaw.internal.agent_key as agent_key_mod
import app.services.openclaw.provisioning as agent_provisioning
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.services.openclaw.shared import GatewayAgentIdentity


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


def test_agent_lifecycle_workspace_path_preserves_tilde_in_workspace_root():
    assert (
        AgentLifecycleService.workspace_path("Alice", "~/.openclaw")
        == "~/.openclaw/workspace-alice"
    )


def test_templates_root_points_to_repo_templates_dir():
    root = agent_provisioning._templates_root()
    assert root.name == "templates"
    assert root.parent.name == "backend"
    assert (root / "AGENTS.md").exists()


@dataclass
class _GatewayStub:
    id: UUID
    name: str
    url: str
    token: str | None
    workspace_root: str


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
async def test_set_agent_files_update_writes_zero_size_user_md():
    """Treat empty placeholder files as missing during update."""

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
            heartbeat={"every": "10m", "target": "none", "includeReasoning": False},
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
            heartbeat={"every": "10m", "target": "none", "includeReasoning": False},
        ),
    )

    assert calls[0][0] == "agents.create"
    assert calls[1][0] == "agents.update"


def test_is_missing_agent_error_matches_gateway_agent_not_found() -> None:
    assert agent_provisioning._is_missing_agent_error(
        agent_provisioning.OpenClawGatewayError('agent "mc-abc" not found'),
    )
    assert not agent_provisioning._is_missing_agent_error(
        agent_provisioning.OpenClawGatewayError("dial tcp: connection refused"),
    )


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
