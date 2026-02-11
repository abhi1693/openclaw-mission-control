from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.api import approvals
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.boards import Board
from app.schemas.approvals import ApprovalRead, ApprovalUpdate
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig


class _ByIdQuery:
    def __init__(self, approval: Approval | None) -> None:
        self._approval = approval

    async def first(self, _session: object) -> Approval | None:
        return self._approval


class _ApprovalObjects:
    def __init__(self, approval: Approval | None) -> None:
        self._approval = approval

    def by_id(self, _approval_id: str) -> _ByIdQuery:
        return _ByIdQuery(self._approval)


@dataclass
class _FakeSession:
    commits: int = 0
    refreshed: int = 0
    added: list[object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.added is None:
            self.added = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _value: object) -> None:
        self.refreshed += 1


def _board() -> Board:
    return Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Ops",
        slug="ops",
    )


def _approval(*, board_id: UUID, status: str = "pending") -> Approval:
    return Approval(
        id=uuid4(),
        board_id=board_id,
        action_type="task.execute",
        confidence=91,
        status=status,
        payload={"target": "deployment"},
    )


@pytest.mark.asyncio
async def test_update_approval_notifies_lead_when_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board()
    approval = _approval(board_id=board.id, status="pending")
    lead = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=uuid4(),
        name="Lead Agent",
        is_board_lead=True,
        openclaw_session_id="agent:lead:session",
    )
    session = _FakeSession()
    captured: dict[str, Any] = {}

    fake_approval_model = type("FakeApprovalModel", (), {"objects": _ApprovalObjects(approval)})
    monkeypatch.setattr(approvals, "Approval", fake_approval_model)

    async def _fake_resolve_lead(*_args: Any, **_kwargs: Any) -> Agent:
        return lead

    async def _fake_optional_gateway_config_for_board(
        self: approvals.GatewayDispatchService,
        _board: Board,
    ) -> GatewayClientConfig:
        _ = self
        return GatewayClientConfig(url="ws://gateway.example/ws", token=None)

    async def _fake_try_send_agent_message(
        self: approvals.GatewayDispatchService,
        **kwargs: Any,
    ) -> None:
        _ = self
        captured.update(kwargs)
        return None

    monkeypatch.setattr(approvals, "_resolve_board_lead", _fake_resolve_lead)
    monkeypatch.setattr(
        approvals.GatewayDispatchService,
        "optional_gateway_config_for_board",
        _fake_optional_gateway_config_for_board,
    )
    monkeypatch.setattr(
        approvals.GatewayDispatchService,
        "try_send_agent_message",
        _fake_try_send_agent_message,
    )

    async def _fake_load_task_ids_by_approval(
        _session: object,
        *,
        approval_ids: list[UUID],
    ) -> dict[UUID, list[UUID]]:
        _ = approval_ids
        return {approval.id: []}

    monkeypatch.setattr(approvals, "load_task_ids_by_approval", _fake_load_task_ids_by_approval)

    async def _fake_reads(_session: object, _approvals: list[Approval]) -> list[ApprovalRead]:
        return [ApprovalRead.model_validate(approval, from_attributes=True)]

    monkeypatch.setattr(
        approvals,
        "_approval_reads",
        _fake_reads,
    )

    updated = await approvals.update_approval(
        approval_id=str(approval.id),
        payload=ApprovalUpdate(status="approved"),
        board=board,
        session=session,  # type: ignore[arg-type]
    )

    assert updated.status == "approved"
    assert captured["session_key"] == "agent:lead:session"
    assert captured["agent_name"] == "Lead Agent"
    assert "APPROVAL RESOLVED" in captured["message"]
    assert "Decision: approved" in captured["message"]

    event_types = [item.event_type for item in session.added if hasattr(item, "event_type")]
    assert "approval.lead_notified" in event_types
    assert session.commits >= 2


@pytest.mark.asyncio
async def test_update_approval_skips_notify_when_status_not_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board()
    approval = _approval(board_id=board.id, status="pending")
    session = _FakeSession()
    called = {"notify": 0}

    fake_approval_model = type("FakeApprovalModel", (), {"objects": _ApprovalObjects(approval)})
    monkeypatch.setattr(approvals, "Approval", fake_approval_model)

    async def _fake_notify(**_kwargs: Any) -> None:
        called["notify"] += 1

    monkeypatch.setattr(approvals, "_notify_lead_on_approval_resolution", _fake_notify)

    async def _fake_reads(_session: object, _approvals: list[Approval]) -> list[ApprovalRead]:
        return [ApprovalRead.model_validate(approval, from_attributes=True)]

    monkeypatch.setattr(
        approvals,
        "_approval_reads",
        _fake_reads,
    )

    updated = await approvals.update_approval(
        approval_id=str(approval.id),
        payload=ApprovalUpdate(status="pending"),
        board=board,
        session=session,  # type: ignore[arg-type]
    )

    assert updated.status == "pending"
    assert called["notify"] == 0


def test_approval_resolution_message_uses_rejected_enum_value() -> None:
    board = _board()
    approval = _approval(board_id=board.id, status="rejected")
    message = approvals._approval_resolution_message(board=board, approval=approval)
    assert "APPROVAL RESOLVED" in message
    assert f"Approval ID: {approval.id}" in message
    assert "Decision: rejected" in message
