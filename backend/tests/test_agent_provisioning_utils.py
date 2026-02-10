# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.services.openclaw import GatewayAgentIdentity
from app.services.openclaw import provisioning as agent_provisioning


def test_slugify_normalizes_and_trims():
    assert agent_provisioning._slugify("Hello, World") == "hello-world"
    assert agent_provisioning._slugify("  A   B  ") == "a-b"


def test_slugify_falls_back_to_uuid_hex(monkeypatch):
    class _FakeUuid:
        hex = "deadbeef"

    monkeypatch.setattr(agent_provisioning, "uuid4", lambda: _FakeUuid())
    assert agent_provisioning._slugify("!!!") == "deadbeef"


def test_extract_agent_id_supports_lists_and_dicts():
    assert agent_provisioning._extract_agent_id(["", "  ", "abc"]) == "abc"
    assert agent_provisioning._extract_agent_id([{"agent_id": "xyz"}]) == "xyz"

    payload = {
        "defaultAgentId": "dflt",
        "agents": [{"id": "ignored"}],
    }
    assert agent_provisioning._extract_agent_id(payload) == "dflt"

    payload2 = {
        "agents": [{"id": ""}, {"agentId": "foo"}],
    }
    assert agent_provisioning._extract_agent_id(payload2) == "foo"


def test_extract_agent_id_returns_none_for_unknown_shapes():
    assert agent_provisioning._extract_agent_id("nope") is None
    assert agent_provisioning._extract_agent_id({"agents": "not-a-list"}) is None


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


def test_agent_key_uses_session_key_when_present(monkeypatch):
    agent = _AgentStub(name="Alice", openclaw_session_id="agent:alice:main")
    assert agent_provisioning._agent_key(agent) == "alice"

    monkeypatch.setattr(agent_provisioning, "_slugify", lambda value: "slugged")
    agent2 = _AgentStub(name="Alice", openclaw_session_id=None)
    assert agent_provisioning._agent_key(agent2) == "slugged"


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

    async def _fake_list_supported_files(self):
        return set()

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
        "list_supported_files",
        _fake_list_supported_files,
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

    await agent_provisioning.provision_main_agent(
        agent,
        agent_provisioning.MainAgentProvisionRequest(
            gateway=gateway,
            auth_token="secret-token",
            user=None,
            session_key=session_key,
        ),
    )

    expected_agent_id = GatewayAgentIdentity.openclaw_agent_id_for_id(gateway_id)
    assert captured["patched_agent_id"] == expected_agent_id
    assert captured["files_index_agent_id"] == expected_agent_id
