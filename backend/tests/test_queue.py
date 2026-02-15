# ruff: noqa: INP001
"""Generic RQ queue helper tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.services.queue import QueuedTask, dequeue_task, enqueue_task, requeue_if_failed


class _FakeRedis:
    def __init__(self) -> None:
        self.values: list[str] = []

    def lpush(self, key: str, value: str) -> None:
        del key
        self.values.insert(0, value)

    def rpop(self, key: str) -> str | None:
        del key
        if not self.values:
            return None
        return self.values.pop()


@pytest.mark.parametrize("attempts", [0, 1, 2])
def test_generic_queue_roundtrip(monkeypatch: pytest.MonkeyPatch, attempts: int) -> None:
    fake = _FakeRedis()

    def _fake_redis(*, redis_url: str | None = None) -> _FakeRedis:
        return fake

    monkeypatch.setattr("app.services.queue._redis_client", _fake_redis)
    payload = QueuedTask(
        task_type="generic-task",
        payload={"name": "webhook.delivery"},
        created_at=datetime.now(UTC),
        attempts=attempts,
    )

    assert enqueue_task(payload, "generic-queue")
    item = dequeue_task("generic-queue")
    assert item is not None
    assert item.task_type == payload.task_type
    assert item.payload == payload.payload
    assert item.attempts == attempts


@pytest.mark.parametrize("attempts", [0, 1, 2, 3])
def test_generic_requeue_respects_retry_cap(monkeypatch: pytest.MonkeyPatch, attempts: int) -> None:
    fake = _FakeRedis()

    def _fake_redis(*, redis_url: str | None = None) -> _FakeRedis:
        return fake

    monkeypatch.setattr("app.services.queue._redis_client", _fake_redis)
    payload = QueuedTask(
        task_type="generic-task",
        payload={"attempt": attempts},
        created_at=datetime.now(UTC),
        attempts=attempts,
    )

    if attempts >= 3:
        assert requeue_if_failed(payload, "generic-queue", max_retries=3) is False
        assert fake.values == []
    else:
        assert requeue_if_failed(payload, "generic-queue", max_retries=3) is True
        requeued = dequeue_task("generic-queue")
        assert requeued is not None
        assert requeued.attempts == attempts + 1


def test_dequeue_task_tolerates_legacy_payload_without_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()

    def _fake_redis(*, redis_url: str | None = None) -> _FakeRedis:
        return fake

    monkeypatch.setattr("app.services.queue._redis_client", _fake_redis)
    created_at = datetime.now(UTC)
    fake.values.append(
        json.dumps(
            {
                "board_id": "6f3ab1ec-3ef6-4f4d-a6a7-e2d6e5d6f7a8",
                "webhook_id": "e5cf5d2a-3f7d-4f3a-b2b0-b3b4f6f3a8ad",
                "payload_id": "3f1f0b9e-4f7a-4fbe-b0f1-1a6f0f4f9e70",
                "payload_event": "push",
                "received_at": created_at.isoformat(),
                "attempts": 2,
            }
        )
    )

    task = dequeue_task("generic-queue")

    assert task is not None
    assert task.task_type == "legacy"
    assert task.attempts == 2
    assert task.payload["board_id"] == "6f3ab1ec-3ef6-4f4d-a6a7-e2d6e5d6f7a8"
