# ruff: noqa: INP001
"""Webhook queue and dispatch worker tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.webhooks import dispatch
from app.services.webhooks.queue import (
    QueuedInboundDelivery,
    dequeue_webhook_delivery,
    enqueue_webhook_delivery,
    requeue_if_failed,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: list[str] = []

    def lpush(self, key: str, value: str) -> None:
        self.values.insert(0, value)

    def rpop(self, key: str) -> str | None:
        if not self.values:
            return None
        return self.values.pop()


@pytest.mark.parametrize("attempts", [0, 1, 2])
def test_webhook_queue_roundtrip(monkeypatch: pytest.MonkeyPatch, attempts: int) -> None:
    fake = _FakeRedis()

    def _fake_redis(*, redis_url: str | None = None) -> _FakeRedis:
        return fake

    board_id = uuid4()
    webhook_id = uuid4()
    payload_id = uuid4()
    payload = QueuedInboundDelivery(
        board_id=board_id,
        webhook_id=webhook_id,
        payload_id=payload_id,
        received_at=datetime.now(UTC),
        attempts=attempts,
    )

    monkeypatch.setattr("app.services.queue._redis_client", _fake_redis)
    assert enqueue_webhook_delivery(payload)

    dequeued = dequeue_webhook_delivery()
    assert dequeued is not None
    assert dequeued.board_id == board_id
    assert dequeued.webhook_id == webhook_id
    assert dequeued.payload_id == payload_id
    assert dequeued.attempts == attempts


def test_webhook_queue_dequeue_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()

    def _fake_redis(*, redis_url: str | None = None) -> _FakeRedis:
        return fake

    payload_id = uuid4()
    board_id = uuid4()
    webhook_id = uuid4()
    received_at = datetime.now(UTC)
    fake.values.append(
        json.dumps(
            {
                "board_id": str(board_id),
                "webhook_id": str(webhook_id),
                "payload_id": str(payload_id),
                "received_at": received_at.isoformat(),
                "attempts": 2,
            }
        )
    )

    monkeypatch.setattr("app.services.queue._redis_client", _fake_redis)
    dequeued = dequeue_webhook_delivery()

    assert dequeued is not None
    assert dequeued.board_id == board_id
    assert dequeued.webhook_id == webhook_id
    assert dequeued.payload_id == payload_id
    assert dequeued.attempts == 2


@pytest.mark.parametrize("attempts", [0, 1, 2, 3])
def test_requeue_respects_retry_cap(monkeypatch: pytest.MonkeyPatch, attempts: int) -> None:
    fake = _FakeRedis()

    def _fake_redis(*, redis_url: str | None = None) -> _FakeRedis:
        return fake

    monkeypatch.setattr("app.services.queue._redis_client", _fake_redis)

    payload = QueuedInboundDelivery(
        board_id=uuid4(),
        webhook_id=uuid4(),
        payload_id=uuid4(),
        received_at=datetime.now(UTC),
        attempts=attempts,
    )

    if attempts >= 3:
        assert requeue_if_failed(payload) is False
        assert fake.values == []
    else:
        assert requeue_if_failed(payload) is True
        requeued = dequeue_webhook_delivery()
        assert requeued is not None
        assert requeued.attempts == attempts + 1


class _FakeQueuedItem:
    def __init__(self, attempts: int = 0) -> None:
        self.payload_id = uuid4()
        self.webhook_id = uuid4()
        self.board_id = uuid4()
        self.attempts = attempts


def _patch_dequeue(
    monkeypatch: pytest.MonkeyPatch, items: list[QueuedInboundDelivery | None]
) -> None:
    def _dequeue() -> QueuedInboundDelivery | None:
        if not items:
            return None
        return items.pop(0)

    monkeypatch.setattr(dispatch, "dequeue_webhook_delivery", _dequeue)


@pytest.mark.asyncio
async def test_dispatch_flush_processes_items_and_throttles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items: list[QueuedInboundDelivery | None] = [
        _FakeQueuedItem(),
        _FakeQueuedItem(),
        None,
    ]
    _patch_dequeue(monkeypatch, items)

    processed: list[UUID] = []
    throttles: list[float] = []

    async def _process(item: QueuedInboundDelivery) -> None:
        processed.append(item.payload_id)

    monkeypatch.setattr(dispatch, "_process_single_item", _process)
    monkeypatch.setattr(dispatch.settings, "rq_dispatch_throttle_seconds", 0)
    monkeypatch.setattr(dispatch.time, "sleep", lambda seconds: throttles.append(seconds))

    await dispatch.flush_webhook_delivery_queue()

    assert len(processed) == 2
    assert throttles == [0.0, 0.0]


@pytest.mark.asyncio
async def test_dispatch_flush_requeues_on_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _FakeQueuedItem()
    _patch_dequeue(monkeypatch, [item, None])

    async def _process(_: QueuedInboundDelivery) -> None:
        raise RuntimeError("boom")

    requeued: list[QueuedInboundDelivery] = []

    def _requeue(payload: QueuedInboundDelivery) -> bool:
        requeued.append(payload)
        return True

    monkeypatch.setattr(dispatch, "_process_single_item", _process)
    monkeypatch.setattr(dispatch, "requeue_if_failed", _requeue)
    monkeypatch.setattr(dispatch.settings, "rq_dispatch_throttle_seconds", 0)
    monkeypatch.setattr(dispatch.time, "sleep", lambda seconds: None)

    await dispatch.flush_webhook_delivery_queue()

    assert len(requeued) == 1
    assert requeued[0].payload_id == item.payload_id


@pytest.mark.asyncio
async def test_dispatch_flush_recovers_from_dequeue_error(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _FakeQueuedItem()
    call_count = 0

    def _dequeue() -> QueuedInboundDelivery | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("dequeue broken")
        if call_count == 2:
            return item
        return None

    monkeypatch.setattr(dispatch, "dequeue_webhook_delivery", _dequeue)

    processed = 0

    async def _process(_: QueuedInboundDelivery) -> None:
        nonlocal processed
        processed += 1

    monkeypatch.setattr(dispatch, "_process_single_item", _process)
    monkeypatch.setattr(dispatch.settings, "rq_dispatch_throttle_seconds", 0)
    monkeypatch.setattr(dispatch.time, "sleep", lambda seconds: None)

    await dispatch.flush_webhook_delivery_queue()

    assert call_count == 3
    assert processed == 1


@pytest.mark.asyncio
async def test_notify_target_agent_prefers_mapped_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_id = uuid4()
    mapped_agent = SimpleNamespace(
        id=agent_id,
        name="Mapped Agent",
        openclaw_session_id="mapped:session",
    )
    lead_agent = SimpleNamespace(
        id=uuid4(),
        name="Lead Agent",
        openclaw_session_id="lead:session",
    )
    sent: list[dict[str, str]] = []

    class _FakeAgentObjects:
        def filter_by(self, **kwargs: object) -> _FakeAgentObjects:
            self._kwargs = kwargs
            return self

        async def first(self, session: object) -> object | None:
            del session
            if self._kwargs.get("id") == agent_id:
                return mapped_agent
            if self._kwargs.get("is_board_lead") is True:
                return lead_agent
            return None

    class _FakeDispatchService:
        def __init__(self, session: object) -> None:
            del session

        async def optional_gateway_config_for_board(self, board: object) -> object:
            del board
            return object()

        async def try_send_agent_message(
            self,
            *,
            session_key: str,
            config: object,
            agent_name: str,
            message: str,
            deliver: bool = False,
        ) -> None:
            del config, message, deliver
            sent.append({"session_key": session_key, "agent_name": agent_name})

    monkeypatch.setattr(dispatch.Agent, "objects", _FakeAgentObjects())
    monkeypatch.setattr(dispatch, "GatewayDispatchService", _FakeDispatchService)

    webhook = SimpleNamespace(id=uuid4(), description="desc", agent_id=agent_id)
    board = SimpleNamespace(id=uuid4(), name="Board")
    payload = SimpleNamespace(id=uuid4(), payload={"event": "test"})

    await dispatch._notify_target_agent(
        session=SimpleNamespace(),
        board=board,
        webhook=webhook,
        payload=payload,
    )

    assert sent == [{"session_key": "mapped:session", "agent_name": "Mapped Agent"}]


@pytest.mark.asyncio
async def test_notify_target_agent_falls_back_to_lead(monkeypatch: pytest.MonkeyPatch) -> None:
    lead_agent = SimpleNamespace(
        id=uuid4(),
        name="Lead Agent",
        openclaw_session_id="lead:session",
    )
    sent: list[dict[str, str]] = []

    class _FakeAgentObjects:
        def filter_by(self, **kwargs: object) -> _FakeAgentObjects:
            self._kwargs = kwargs
            return self

        async def first(self, session: object) -> object | None:
            del session
            if self._kwargs.get("is_board_lead") is True:
                return lead_agent
            return None

    class _FakeDispatchService:
        def __init__(self, session: object) -> None:
            del session

        async def optional_gateway_config_for_board(self, board: object) -> object:
            del board
            return object()

        async def try_send_agent_message(
            self,
            *,
            session_key: str,
            config: object,
            agent_name: str,
            message: str,
            deliver: bool = False,
        ) -> None:
            del config, message, deliver
            sent.append({"session_key": session_key, "agent_name": agent_name})

    monkeypatch.setattr(dispatch.Agent, "objects", _FakeAgentObjects())
    monkeypatch.setattr(dispatch, "GatewayDispatchService", _FakeDispatchService)

    webhook = SimpleNamespace(id=uuid4(), description="desc", agent_id=None)
    board = SimpleNamespace(id=uuid4(), name="Board")
    payload = SimpleNamespace(id=uuid4(), payload={"event": "test"})

    await dispatch._notify_target_agent(
        session=SimpleNamespace(),
        board=board,
        webhook=webhook,
        payload=payload,
    )

    assert sent == [{"session_key": "lead:session", "agent_name": "Lead Agent"}]


def test_dispatch_run_entrypoint_calls_async_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    async def _flush() -> None:
        called.append(True)

    monkeypatch.setattr(dispatch, "flush_webhook_delivery_queue", _flush)

    dispatch.run_flush_webhook_delivery_queue()

    assert called == [True]
