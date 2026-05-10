# ruff: noqa: INP001
"""Regression tests for deterministic operator memory intake."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.models.board_memory import BoardMemory
from app.models.tasks import Task
from app.services.board_memory_intake import (
    is_actionable_operator_memory,
    reconcile_board_memory_intake,
)


class _ExecResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, memories: list[BoardMemory]) -> None:
        self.memories = memories
        self.tasks: list[Task] = []
        self._pending: Task | None = None
        self.commits = 0
        self.exec_calls = 0

    async def exec(self, statement: object) -> _ExecResult:
        del statement
        self.exec_calls += 1
        if self.exec_calls == 1:
            return _ExecResult(list(self.memories))
        memory_ids = {memory.id for memory in self.memories}
        linked = [
            task.id
            for task in self.tasks
            if task.source_memory_id in memory_ids
            or any(
                f"source_memory_id={memory_id}" in (task.description or "")
                for memory_id in memory_ids
            )
        ]
        return _ExecResult(linked)

    def add(self, task: Task) -> None:
        self._pending = task

    async def flush(self) -> None:
        if self._pending is not None:
            self.tasks.append(self._pending)
            self._pending = None

    async def commit(self) -> None:
        self.commits += 1

    @asynccontextmanager
    async def begin_nested(self):
        yield


def _memory(
    *, tags: list[str], content: str = "Operator findings\n\nhttps://example.test"
) -> BoardMemory:
    return BoardMemory(
        board_id=uuid4(),
        content=content,
        tags=tags,
        source="operator",
    )


def test_actionable_operator_memory_excludes_e2e_canaries() -> None:
    assert is_actionable_operator_memory(_memory(tags=["operator", "findings"]))
    assert is_actionable_operator_memory(_memory(tags=["operator", "marketing_site_review"]))
    assert not is_actionable_operator_memory(_memory(tags=["operator", "findings", "e2e_canary"]))
    assert not is_actionable_operator_memory(_memory(tags=["handoff", "findings"]))


@pytest.mark.asyncio
async def test_reconcile_board_memory_intake_creates_one_linked_inbox_task() -> None:
    board_id = uuid4()
    memory = _memory(
        tags=["operator", "findings", "marketing_site_review"],
        content=(
            "Marketing review: visual findings\n\n"
            "Inspect https://example.test/taskflow and decompose the issues."
        ),
    )
    memory.board_id = board_id
    session = _FakeSession([memory])

    result = await reconcile_board_memory_intake(session, board_id=board_id)

    assert result.created == 1
    assert len(session.tasks) == 1
    task = session.tasks[0]
    assert task.title == "Marketing review: visual findings"
    assert task.description == memory.content
    assert task.status == "inbox"
    assert task.assigned_agent_id is None
    assert task.source_memory_id == memory.id
    assert task.review_packet_type == "frontend_ui"
    assert task.validation_target == "https://example.test/taskflow"
    assert task.validation_target_kind == "live_url"
    assert task.validation_target_scope == "review"


@pytest.mark.asyncio
async def test_reconcile_board_memory_intake_ignores_e2e_canary_memory() -> None:
    board_id = uuid4()
    memory = _memory(tags=["operator", "findings", "e2e_canary"])
    memory.board_id = board_id
    session = _FakeSession([memory])

    result = await reconcile_board_memory_intake(session, board_id=board_id)

    assert result.created == 0
    assert session.tasks == []


@pytest.mark.asyncio
async def test_reconcile_board_memory_intake_skips_legacy_description_link() -> None:
    board_id = uuid4()
    memory = _memory(tags=["operator", "findings"])
    memory.board_id = board_id
    legacy_task = Task(
        id=uuid4(),
        board_id=board_id,
        title="Decompose existing findings",
        description=f"source_memory_id={memory.id}\nAlready decomposed.",
        status="review",
    )
    session = _FakeSession([memory])
    session.tasks.append(legacy_task)

    result = await reconcile_board_memory_intake(session, board_id=board_id)

    assert result.created == 0
    assert result.skipped_existing == 1
    assert session.tasks == [legacy_task]
