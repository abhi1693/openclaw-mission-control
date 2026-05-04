"""Operator-side ``send_session_message`` routing tests.

Covers the ``interrupt_if_active`` payload flag added on top of OpenClaw
2026.5.3 ``sessions.steer``: when set, MC must route through the steer
helper (which aborts active work first) instead of plain ``send_message``
which queues the prompt for the next turn.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import app.services.openclaw.session_service as session_service
from app.services.openclaw.gateway_rpc import GatewayConfig
from app.services.openclaw.session_service import GatewaySessionService
from app.schemas.gateway_api import GatewaySessionMessageRequest


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    service: GatewaySessionService,
    *,
    config: GatewayConfig,
    main_session: str | None,
) -> None:
    async def fake_require_gateway(board_id: str | None, *, user: object | None = None):
        _ = (board_id, user)
        return object(), config, main_session

    def fake_require_same_org(board: object, organization_id):
        _ = (board, organization_id)
        return None

    async def fake_require_board_access(session, *, user: object, board: object, write: bool):
        _ = (session, user, board, write)
        return None

    async def fake_ensure_session(*args, **kwargs):
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(service, "require_gateway", fake_require_gateway)
    monkeypatch.setattr(service, "_require_same_org", fake_require_same_org)
    monkeypatch.setattr(session_service, "require_board_access", fake_require_board_access)
    monkeypatch.setattr(session_service, "ensure_session", fake_ensure_session)


@pytest.mark.asyncio
async def test_send_session_message_default_routes_to_send_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default behaviour (no ``interrupt_if_active``): plain queue-and-deliver
    via ``chat.send`` — must not invoke the operator-scoped ``sessions.steer``
    helper which would interrupt running work."""

    observed: dict[str, object] = {}
    config = GatewayConfig(url="ws://gateway.example/ws", token="tok")
    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    _patch_common(monkeypatch, service, config=config, main_session=None)

    async def fake_send_message(message: str, *, session_key: str, config, deliver: bool = False):
        _ = (config, deliver)
        observed["send_message"] = (message, session_key)

    async def fake_steer_session(*args, **kwargs):
        observed["steer"] = (args, kwargs)

    monkeypatch.setattr(session_service, "send_message", fake_send_message)
    monkeypatch.setattr(session_service, "steer_session", fake_steer_session)

    await service.send_session_message(
        session_id="agent:lead:main",
        payload=GatewaySessionMessageRequest(content="hi"),
        board_id=str(uuid4()),
        organization_id=uuid4(),
        user=object(),  # type: ignore[arg-type]
    )

    assert observed.get("send_message") == ("hi", "agent:lead:main")
    assert "steer" not in observed


@pytest.mark.asyncio
async def test_send_session_message_interrupt_if_active_routes_to_steer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``interrupt_if_active=True``: route through ``sessions.steer`` so a
    stuck or long-running agent run is aborted before the new prompt
    lands. ``send_message`` must NOT also fire — that would re-queue the
    same message and the agent would see it twice."""

    observed: dict[str, object] = {}
    config = GatewayConfig(url="ws://gateway.example/ws", token="tok")
    service = GatewaySessionService(session=object())  # type: ignore[arg-type]
    _patch_common(monkeypatch, service, config=config, main_session=None)

    async def fake_send_message(*args, **kwargs):
        observed["send_message"] = (args, kwargs)

    async def fake_steer_session(message: str, *, session_key: str, config):
        _ = config
        observed["steer"] = (message, session_key)

    monkeypatch.setattr(session_service, "send_message", fake_send_message)
    monkeypatch.setattr(session_service, "steer_session", fake_steer_session)

    await service.send_session_message(
        session_id="agent:lead:main",
        payload=GatewaySessionMessageRequest(content="get unstuck", interrupt_if_active=True),
        board_id=str(uuid4()),
        organization_id=uuid4(),
        user=object(),  # type: ignore[arg-type]
    )

    assert observed.get("steer") == ("get unstuck", "agent:lead:main")
    assert "send_message" not in observed
