# ruff: noqa: S101
"""Unit tests for lifecycle coordination and onboarding messaging services."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status

import app.services.openclaw.coordination_service as coordination_lifecycle
import app.services.openclaw.lifecycle_orchestrator as lifecycle_orchestrator_module
import app.services.openclaw.onboarding_service as onboarding_lifecycle
import app.services.openclaw.provisioning as provisioning_module
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.provisioning import LifecycleResult
from app.services.openclaw.shared import GatewayAgentIdentity


@dataclass
class _FakeSession:
    committed: int = 0
    added: list[object] = field(default_factory=list)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1


@dataclass
class _AgentStub:
    id: UUID
    name: str
    openclaw_session_id: str | None = None
    board_id: UUID | None = None


@dataclass
class _BoardStub:
    id: UUID
    gateway_id: UUID | None
    name: str


@pytest.mark.asyncio
async def test_gateway_coordination_nudge_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    service = coordination_lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Lead Agent", board_id=board.id)
    target = _AgentStub(
        id=uuid4(),
        name="Worker Agent",
        openclaw_session_id="agent:worker:main",
        board_id=board.id,
    )
    captured: list[dict[str, Any]] = []

    async def _fake_board_agent_or_404(
        self: coordination_lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    async def _fake_require_gateway_config_for_board(
        self: coordination_lifecycle.GatewayDispatchService,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        _ = self
        gateway = SimpleNamespace(id=uuid4(), url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_agent_message(self, **kwargs: Any) -> None:
        _ = self
        captured.append(kwargs)
        return None

    monkeypatch.setattr(
        coordination_lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )
    monkeypatch.setattr(
        coordination_lifecycle.GatewayDispatchService,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        coordination_lifecycle.GatewayDispatchService,
        "send_agent_message",
        _fake_send_agent_message,
    )

    await service.nudge_board_agent(
        board=board,  # type: ignore[arg-type]
        actor_agent=actor,  # type: ignore[arg-type]
        target_agent_id=str(target.id),
        message="Please run session startup checklist",
        correlation_id="nudge-corr-id",
    )

    assert len(captured) == 1
    assert captured[0]["session_key"] == "agent:worker:main"
    assert captured[0]["agent_name"] == "Worker Agent"
    assert captured[0]["deliver"] is True
    assert session.committed == 1


@pytest.mark.asyncio
async def test_gateway_coordination_nudge_maps_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = coordination_lifecycle.GatewayCoordinationService(session)  # type: ignore[arg-type]
    board = _BoardStub(id=uuid4(), gateway_id=uuid4(), name="Roadmap")
    actor = _AgentStub(id=uuid4(), name="Lead Agent", board_id=board.id)
    target = _AgentStub(
        id=uuid4(),
        name="Worker Agent",
        openclaw_session_id="agent:worker:main",
        board_id=board.id,
    )

    async def _fake_board_agent_or_404(
        self: coordination_lifecycle.GatewayCoordinationService,
        *,
        board: object,
        agent_id: str,
    ) -> _AgentStub:
        _ = (self, board, agent_id)
        return target

    async def _fake_require_gateway_config_for_board(
        self: coordination_lifecycle.GatewayDispatchService,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        _ = self
        gateway = SimpleNamespace(id=uuid4(), url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_agent_message(self, **_kwargs: Any) -> None:
        _ = self
        raise OpenClawGatewayError("dial tcp: connection refused")

    monkeypatch.setattr(
        coordination_lifecycle.GatewayCoordinationService,
        "_board_agent_or_404",
        _fake_board_agent_or_404,
    )
    monkeypatch.setattr(
        coordination_lifecycle.GatewayDispatchService,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        coordination_lifecycle.GatewayDispatchService,
        "send_agent_message",
        _fake_send_agent_message,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.nudge_board_agent(
            board=board,  # type: ignore[arg-type]
            actor_agent=actor,  # type: ignore[arg-type]
            target_agent_id=str(target.id),
            message="Please run session startup checklist",
            correlation_id="nudge-corr-id",
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Gateway nudge failed:" in str(exc_info.value.detail)
    assert session.committed == 1


@pytest.mark.asyncio
async def test_board_onboarding_dispatch_start_returns_session_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = onboarding_lifecycle.BoardOnboardingMessagingService(session)  # type: ignore[arg-type]
    gateway_id = uuid4()
    board = _BoardStub(id=uuid4(), gateway_id=gateway_id, name="Roadmap")
    captured: list[dict[str, Any]] = []

    async def _fake_require_gateway_config_for_board(
        self: onboarding_lifecycle.GatewayDispatchService,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        _ = self
        gateway = SimpleNamespace(id=gateway_id, url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_agent_message(self, **kwargs: Any) -> None:
        _ = self
        captured.append(kwargs)
        return None

    monkeypatch.setattr(
        onboarding_lifecycle.GatewayDispatchService,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        coordination_lifecycle.GatewayDispatchService,
        "send_agent_message",
        _fake_send_agent_message,
    )

    session_key = await service.dispatch_start_prompt(
        board=board,  # type: ignore[arg-type]
        prompt="BOARD ONBOARDING REQUEST",
        correlation_id="onboarding-corr-id",
    )

    assert session_key == GatewayAgentIdentity.session_key_for_id(gateway_id)
    assert len(captured) == 1
    assert captured[0]["agent_name"] == "Gateway Agent"
    assert captured[0]["deliver"] is False


@pytest.mark.asyncio
async def test_board_onboarding_dispatch_answer_maps_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = onboarding_lifecycle.BoardOnboardingMessagingService(session)  # type: ignore[arg-type]
    gateway_id = uuid4()
    board = _BoardStub(id=uuid4(), gateway_id=gateway_id, name="Roadmap")
    onboarding = SimpleNamespace(
        id=uuid4(),
        session_key=GatewayAgentIdentity.session_key_for_id(gateway_id),
    )

    async def _fake_require_gateway_config_for_board(
        self: onboarding_lifecycle.GatewayDispatchService,
        _board: object,
    ) -> tuple[object, GatewayClientConfig]:
        _ = self
        gateway = SimpleNamespace(id=gateway_id, url="ws://gateway.example/ws")
        return gateway, GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_send_agent_message(self, **_kwargs: Any) -> None:
        _ = self
        raise TimeoutError("gateway timeout")

    monkeypatch.setattr(
        onboarding_lifecycle.GatewayDispatchService,
        "require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        coordination_lifecycle.GatewayDispatchService,
        "send_agent_message",
        _fake_send_agent_message,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.dispatch_answer(
            board=board,  # type: ignore[arg-type]
            onboarding=onboarding,
            answer_text="I prefer concise updates.",
            correlation_id="onboarding-answer-corr-id",
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Gateway onboarding answer dispatch failed:" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# run_lifecycle wake-skipped contract
# ---------------------------------------------------------------------------


def _make_orchestrator_stub_agent() -> SimpleNamespace:
    """Build an in-memory Agent stub with every field ``run_lifecycle``
    touches on the happy path plus the skipped-wake branch.
    """

    return SimpleNamespace(
        id=uuid4(),
        name="Programmer-Backend",
        openclaw_session_id="agent:mc-pb:main",
        board_id=uuid4(),
        gateway_id=uuid4(),
        is_board_lead=False,
        status="online",
        wake_attempts=0,
        last_wake_sent_at=None,
        checkin_deadline_at=None,
        last_provision_error=None,
        lifecycle_generation=5,
        agent_token_hash=None,  # forces mint_agent_token — simpler than the TOOLS.md read path
        provision_requested_at=None,
        provision_action=None,
        provision_confirm_token_hash=None,
        heartbeat_config={"every": "15m"},
        updated_at=None,
    )


class _OrchestratorFakeSession:
    """Fake AsyncSession sufficient for AgentLifecycleOrchestrator.run_lifecycle."""

    def __init__(self) -> None:
        self.committed = 0
        self.flushed = 0
        self.refreshed: list[object] = []
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_run_lifecycle_skipped_wake_does_not_mark_online_or_strike_or_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH-PRIORITY regression: when the provisioner returns
    ``LifecycleResult(wake_delivered=False)`` because credentials are
    not visible on the gateway, the orchestrator MUST NOT mark the
    agent online, MUST NOT increment ``wake_attempts``, MUST NOT arm a
    ``checkin_deadline_at``, and MUST NOT enqueue a follow-up reconcile.
    It must record the skip reason on ``last_provision_error``.

    Previously the orchestrator incremented ``wake_attempts`` BEFORE the
    gateway call and then unconditionally finalized as online on the
    success path — so a skipped wake was recorded exactly like a real
    wake and the agent drifted into the permanent-offline dead state
    after three skips. The fix is that wake-state mutations only happen
    when ``LifecycleResult.wake_delivered`` is True.
    """

    agent = _make_orchestrator_stub_agent()
    agent.agent_token_hash = "existing"  # avoid the mint path on update

    board = SimpleNamespace(
        id=agent.board_id,
        gateway_id=agent.gateway_id,
        name="Dev Squad",
    )
    gateway = SimpleNamespace(
        id=agent.gateway_id,
        url="ws://gw.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
        organization_id=uuid4(),
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )

    # Bypass the DB SELECT ... FOR UPDATE by returning our stub directly.
    async def _fake_lock_agent(self, *, agent_id):
        return agent

    monkeypatch.setattr(
        lifecycle_orchestrator_module.AgentLifecycleOrchestrator,
        "_lock_agent",
        _fake_lock_agent,
    )

    # Agent already has agent_token_hash set, so run_lifecycle takes the
    # TOOLS.md re-read path. Stub that helper to return a valid token so
    # we reach apply_agent_lifecycle.
    async def _fake_get_existing_auth_token(*, agent_gateway_id, control_plane):
        return "existing-raw-token"

    import app.services.openclaw.provisioning_db as provisioning_db_module

    monkeypatch.setattr(
        provisioning_db_module,
        "_get_existing_auth_token",
        _fake_get_existing_auth_token,
    )

    # The token verification step calls hash_agent_token / verify_agent_token.
    # Make verify_agent_token always return True so we don't rehash the DB.
    import app.core.agent_tokens as agent_tokens_module

    monkeypatch.setattr(agent_tokens_module, "verify_agent_token", lambda raw, hashed: True)

    # Optional gateway client config must return a truthy value so the
    # orchestrator actually invokes _get_existing_auth_token.
    import app.services.openclaw.gateway_resolver as gateway_resolver_module

    monkeypatch.setattr(
        gateway_resolver_module,
        "optional_gateway_client_config",
        lambda gw: GatewayClientConfig(url="ws://gw.example/ws", token=None),
    )

    # The critical mock: apply_agent_lifecycle returns wake_delivered=False.
    async def _fake_apply_agent_lifecycle(self, **kwargs):
        return LifecycleResult(
            wake_delivered=False,
            wake_skip_reason="credentials_not_visible",
        )

    monkeypatch.setattr(
        provisioning_module.OpenClawGatewayProvisioner,
        "apply_agent_lifecycle",
        _fake_apply_agent_lifecycle,
    )

    # Record any reconcile enqueue calls so we can assert there are none.
    enqueued: list[object] = []

    def _fake_enqueue(task):
        enqueued.append(task)

    monkeypatch.setattr(
        lifecycle_orchestrator_module,
        "enqueue_lifecycle_reconcile",
        _fake_enqueue,
    )

    orchestrator = lifecycle_orchestrator_module.AgentLifecycleOrchestrator(
        _OrchestratorFakeSession(),  # type: ignore[arg-type]
    )

    initial_wake_attempts = agent.wake_attempts
    initial_last_wake_sent_at = agent.last_wake_sent_at

    result_agent = await orchestrator.run_lifecycle(
        gateway=gateway,  # type: ignore[arg-type]
        agent_id=agent.id,
        board=board,  # type: ignore[arg-type]
        user=None,
        action="update",
        wake=True,
        wakeup_verb="updated",
    )

    # --- CRITICAL ASSERTIONS ON THE SKIPPED-WAKE CONTRACT ---

    assert result_agent is agent
    assert agent.wake_attempts == initial_wake_attempts, (
        "wake_attempts MUST NOT be incremented when the wake was skipped; "
        f"was {initial_wake_attempts}, became {agent.wake_attempts}"
    )
    assert (
        agent.last_wake_sent_at == initial_last_wake_sent_at
    ), "last_wake_sent_at MUST NOT be set when no wake was sent"
    assert agent.checkin_deadline_at is None, (
        "checkin_deadline_at MUST be None on skip — otherwise the sweep "
        "would schedule a missed-checkin reconcile for a wake that "
        "never happened"
    )
    assert agent.status != "online", (
        f"agent MUST NOT be marked online when the wake was skipped; " f"status is {agent.status!r}"
    )
    assert (
        agent.last_provision_error is not None
    ), "last_provision_error must describe why the wake was skipped"
    assert "skip" in agent.last_provision_error.lower() or (
        "credential" in agent.last_provision_error.lower()
    ), f"skip reason should mention credentials/skip; got {agent.last_provision_error!r}"
    assert enqueued == [], (
        "no reconcile task should be enqueued for a skipped wake; got " f"{enqueued!r}"
    )


@pytest.mark.asyncio
async def test_run_lifecycle_delivered_wake_consumes_strike_and_enqueues_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive-path mirror: when the provisioner confirms the wake was
    actually delivered, the orchestrator MUST consume a strike (first
    wake in cycle → 0→1), arm a check-in deadline, mark the agent
    online, and enqueue a reconcile for the new deadline. This test
    guards against a regression where the skip-path fix accidentally
    suppresses the normal wake state transitions.
    """

    agent = _make_orchestrator_stub_agent()
    agent.agent_token_hash = "existing"
    agent.status = "online"
    agent.wake_attempts = 0
    agent.checkin_deadline_at = None

    board = SimpleNamespace(
        id=agent.board_id,
        gateway_id=agent.gateway_id,
        name="Dev Squad",
    )
    gateway = SimpleNamespace(
        id=agent.gateway_id,
        url="ws://gw.example/ws",
        token=None,
        workspace_root="/tmp/openclaw",
        organization_id=uuid4(),
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )

    async def _fake_lock_agent(self, *, agent_id):
        return agent

    monkeypatch.setattr(
        lifecycle_orchestrator_module.AgentLifecycleOrchestrator,
        "_lock_agent",
        _fake_lock_agent,
    )

    async def _fake_get_existing_auth_token(*, agent_gateway_id, control_plane):
        return "existing-raw-token"

    import app.services.openclaw.provisioning_db as provisioning_db_module

    monkeypatch.setattr(
        provisioning_db_module,
        "_get_existing_auth_token",
        _fake_get_existing_auth_token,
    )

    import app.core.agent_tokens as agent_tokens_module

    monkeypatch.setattr(agent_tokens_module, "verify_agent_token", lambda raw, hashed: True)

    import app.services.openclaw.gateway_resolver as gateway_resolver_module

    monkeypatch.setattr(
        gateway_resolver_module,
        "optional_gateway_client_config",
        lambda gw: GatewayClientConfig(url="ws://gw.example/ws", token=None),
    )

    async def _fake_apply_agent_lifecycle(self, **kwargs):
        return LifecycleResult(wake_delivered=True, wake_skip_reason=None)

    monkeypatch.setattr(
        provisioning_module.OpenClawGatewayProvisioner,
        "apply_agent_lifecycle",
        _fake_apply_agent_lifecycle,
    )

    enqueued: list[object] = []

    def _fake_enqueue(task):
        enqueued.append(task)

    monkeypatch.setattr(
        lifecycle_orchestrator_module,
        "enqueue_lifecycle_reconcile",
        _fake_enqueue,
    )

    orchestrator = lifecycle_orchestrator_module.AgentLifecycleOrchestrator(
        _OrchestratorFakeSession(),  # type: ignore[arg-type]
    )

    await orchestrator.run_lifecycle(
        gateway=gateway,  # type: ignore[arg-type]
        agent_id=agent.id,
        board=board,  # type: ignore[arg-type]
        user=None,
        action="update",
        wake=True,
        wakeup_verb="updated",
    )

    assert agent.wake_attempts == 1, "first wake in a fresh cycle must consume a strike"
    assert agent.last_wake_sent_at is not None, "last_wake_sent_at must be set"
    assert agent.checkin_deadline_at is not None, "a delivered wake must arm a check-in deadline"
    assert agent.status == "online"
    assert agent.last_provision_error is None
    assert len(enqueued) == 1, f"exactly one reconcile task should be enqueued; got {len(enqueued)}"
