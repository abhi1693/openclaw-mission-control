from __future__ import annotations

from uuid import uuid4

import pytest

import app.services.openclaw.session_service as session_service
from app.schemas.gateway_api import (
    GatewayEvalApprovalResolveRequest,
    GatewayEvalSessionEnsureRequest,
    GatewaySessionMessageRequest,
)
from app.services.openclaw.gateway_rpc import GatewayConfig
from app.services.openclaw.session_service import GatewaySessionService


@pytest.mark.asyncio
async def test_send_eval_session_message_delivers_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    config = GatewayConfig(
        url="ws://gateway.example/ws",
        token="tok",
        disable_device_pairing=True,
    )
    service = GatewaySessionService(session=object())  # type: ignore[arg-type]

    async def fake_require_gateway(board_id: str | None, *, user: object | None = None):
        _ = user
        return object(), config, None

    def fake_require_same_org(board: object, organization_id):
        _ = (board, organization_id)
        return None

    async def fake_require_board_access(session, *, user: object, board: object, write: bool):
        _ = (session, user, board, write)
        return None

    async def fake_send_message(
        message: str,
        *,
        session_key: str,
        config: GatewayConfig,
        deliver: bool = False,
    ) -> None:
        observed["message"] = message
        observed["session_key"] = session_key
        observed["config"] = config
        observed["deliver"] = deliver

    monkeypatch.setattr(service, "require_gateway", fake_require_gateway)
    monkeypatch.setattr(service, "_require_same_org", fake_require_same_org)
    monkeypatch.setattr(session_service, "require_board_access", fake_require_board_access)
    monkeypatch.setattr(session_service, "send_message", fake_send_message)

    await service.send_eval_session_message(
        session_id="eval-programmer-frontend-1",
        payload=GatewaySessionMessageRequest(content="run this eval"),
        board_id=str(uuid4()),
        organization_id=uuid4(),
        user=object(),
    )

    assert observed["message"] == "run this eval"
    assert observed["session_key"] == "eval-programmer-frontend-1"
    assert observed["deliver"] is True
    observed_config = observed.get("config")
    assert isinstance(observed_config, GatewayConfig)
    assert observed_config.url == config.url
    assert observed_config.token == config.token
    assert observed_config.disable_device_pairing is False


@pytest.mark.asyncio
async def test_resolve_eval_session_exec_approval_uses_gateway_operator_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    config = GatewayConfig(
        url="ws://gateway.example/ws",
        token="tok",
        disable_device_pairing=True,
    )
    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    approval_id = "a6da1eb3-269d-4916-a706-48fd5cf1d2ec"

    async def fake_require_gateway(board_id: str | None, *, user: object | None = None):
        _ = user
        return object(), config, None

    def fake_require_same_org(board: object, organization_id):
        _ = (board, organization_id)
        return None

    async def fake_require_board_access(session, *, user: object, board: object, write: bool):
        _ = (session, user, board, write)
        return None

    async def fake_get_chat_history(session_key: str, *, config: GatewayConfig):
        observed["history_session_key"] = session_key
        observed["history_config"] = config
        return {
            "messages": [
                {
                    "role": "toolResult",
                    "content": [
                        {
                            "type": "text",
                            "text": ("Approval required (id a6da1eb3, full " f"{approval_id})."),
                        }
                    ],
                }
            ]
        }

    async def fake_openclaw_call(method: str, params: dict[str, object], *, config: GatewayConfig):
        observed["method"] = method
        observed["params"] = params
        observed["resolve_config"] = config
        return {"ok": True}

    monkeypatch.setattr(service, "require_gateway", fake_require_gateway)
    monkeypatch.setattr(service, "_require_same_org", fake_require_same_org)
    monkeypatch.setattr(session_service, "require_board_access", fake_require_board_access)
    monkeypatch.setattr(session_service, "get_chat_history", fake_get_chat_history)
    monkeypatch.setattr(session_service, "openclaw_call", fake_openclaw_call)

    await service.resolve_eval_session_exec_approval(
        session_id="eval-programmer-frontend-1",
        payload=GatewayEvalApprovalResolveRequest(approval_id=approval_id),
        board_id=str(uuid4()),
        organization_id=uuid4(),
        user=object(),
    )

    assert observed["history_session_key"] == "eval-programmer-frontend-1"
    history_config = observed.get("history_config")
    assert isinstance(history_config, GatewayConfig)
    assert history_config.disable_device_pairing is False
    assert observed["method"] == "exec.approval.resolve"
    assert observed["params"] == {"id": approval_id, "decision": "allow-once"}
    resolve_config = observed.get("resolve_config")
    assert isinstance(resolve_config, GatewayConfig)
    assert resolve_config.url == config.url
    assert resolve_config.token == config.token
    assert resolve_config.disable_device_pairing is True


@pytest.mark.asyncio
async def test_ensure_eval_session_binds_to_agent_workspace_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    config = GatewayConfig(
        url="ws://gateway.example/ws",
        token="tok",
        disable_device_pairing=True,
    )
    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    board = object()

    async def fake_require_gateway(board_id: str | None, *, user: object | None = None):
        _ = user
        return board, config, None

    def fake_require_same_org(board_obj: object, organization_id):
        _ = (board_obj, organization_id)
        return None

    async def fake_require_board_access(session, *, user: object, board: object, write: bool):
        _ = (session, user, board, write)
        return None

    async def fake_resolve_eval_agent_gateway_id(*, board: object, agent_id: str) -> str:
        _ = board
        observed["agent_id"] = agent_id
        return "programmer-frontend"

    async def fake_openclaw_call(method: str, params: dict[str, object], *, config: GatewayConfig):
        observed["method"] = method
        observed["params"] = params
        observed["config"] = config
        if method == "sessions.create":
            return {
                "key": "agent:programmer-frontend:eval-programmer-frontend-1",
                "label": "Eval PF",
            }
        if method == "sessions.reset":
            return {"ok": True}
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(service, "require_gateway", fake_require_gateway)
    monkeypatch.setattr(service, "_require_same_org", fake_require_same_org)
    monkeypatch.setattr(
        service, "_resolve_eval_agent_gateway_id", fake_resolve_eval_agent_gateway_id
    )
    monkeypatch.setattr(session_service, "require_board_access", fake_require_board_access)
    monkeypatch.setattr(session_service, "openclaw_call", fake_openclaw_call)

    response = await service.ensure_eval_session(
        session_id="eval-programmer-frontend-1",
        payload=GatewayEvalSessionEnsureRequest(
            label="Eval PF",
            reset=True,
            agent_id="3461451b-5824-4ed0-872c-d14d5d2be107",
        ),
        board_id=str(uuid4()),
        organization_id=uuid4(),
        user=object(),
    )

    assert observed["agent_id"] == "3461451b-5824-4ed0-872c-d14d5d2be107"
    assert observed["method"] == "sessions.reset"
    assert observed["params"] == {"key": "agent:programmer-frontend:eval-programmer-frontend-1"}
    observed_config = observed.get("config")
    assert isinstance(observed_config, GatewayConfig)
    assert observed_config.disable_device_pairing is False
    assert response.session == {
        "key": "agent:programmer-frontend:eval-programmer-frontend-1",
        "label": "Eval PF",
    }
