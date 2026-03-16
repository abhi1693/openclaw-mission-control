# ruff: noqa: S101
"""Unit tests for deterministic OpenClaw session-key helpers."""

from __future__ import annotations

from uuid import UUID

from app.services.openclaw.internal.session_keys import (
    board_agent_session_key,
    board_lead_session_key,
    board_scoped_session_key,
    gateway_main_session_key,
)
from app.services.openclaw.shared import GatewayAgentIdentity


def test_gateway_main_session_key_matches_gateway_identity() -> None:
    gateway_id = UUID("00000000-0000-0000-0000-000000000123")
    assert gateway_main_session_key(gateway_id) == GatewayAgentIdentity.session_key_for_id(
        gateway_id
    )


def test_board_lead_session_key_format() -> None:
    board_id = UUID("00000000-0000-0000-0000-000000000456")
    assert board_lead_session_key(board_id) == f"agent:lead-{board_id}:main"


def test_board_agent_session_key_format() -> None:
    agent_id = UUID("00000000-0000-0000-0000-000000000789")
    assert board_agent_session_key(agent_id) == f"agent:mc-{agent_id}:main"


def test_board_scoped_session_key_selects_lead() -> None:
    agent_id = UUID("00000000-0000-0000-0000-000000000001")
    board_id = UUID("00000000-0000-0000-0000-000000000002")
    assert board_scoped_session_key(
        agent_id=agent_id, board_id=board_id, is_board_lead=True
    ) == board_lead_session_key(board_id)


def test_board_scoped_session_key_selects_non_lead() -> None:
    agent_id = UUID("00000000-0000-0000-0000-000000000001")
    board_id = UUID("00000000-0000-0000-0000-000000000002")
    assert board_scoped_session_key(
        agent_id=agent_id, board_id=board_id, is_board_lead=False
    ) == board_agent_session_key(agent_id)
