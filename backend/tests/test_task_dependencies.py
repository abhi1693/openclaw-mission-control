# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.services import task_dependencies


def test_dedupe_uuid_list_preserves_order_and_removes_duplicates():
    a = uuid4()
    b = uuid4()
    c = uuid4()

    values = [a, b, a, c, b]
    assert task_dependencies._dedupe_uuid_list(values) == [a, b, c]


def test_blocked_by_dependency_ids_flags_not_done_and_missing_status():
    a = uuid4()
    b = uuid4()
    c = uuid4()

    status_by_id = {
        a: task_dependencies.DONE_STATUS,
        b: "in_progress",
        # c intentionally missing
    }

    assert task_dependencies.blocked_by_dependency_ids(
        dependency_ids=[a, b, c],
        status_by_id=status_by_id,
    ) == [b, c]


@pytest.mark.parametrize(
    ("nodes", "edges", "expected"),
    [
        # A -> B -> C (acyclic)
        (
            [UUID(int=1), UUID(int=2), UUID(int=3)],
            {UUID(int=1): {UUID(int=2)}, UUID(int=2): {UUID(int=3)}},
            False,
        ),
        # A -> B -> C -> A (cycle)
        (
            [UUID(int=1), UUID(int=2), UUID(int=3)],
            {UUID(int=1): {UUID(int=2)}, UUID(int=2): {UUID(int=3)}, UUID(int=3): {UUID(int=1)}},
            True,
        ),
        # Self-loop (cycle)
        (
            [UUID(int=1)],
            {UUID(int=1): {UUID(int=1)}},
            True,
        ),
    ],
)
def test_has_cycle(nodes, edges, expected):
    assert task_dependencies._has_cycle(nodes, edges) is expected


@dataclass
class _FakeSession:
    exec_results: list[object]
    executed: list[object] = field(default_factory=list)
    added: list[object] = field(default_factory=list)

    async def exec(self, _query):
        is_dml = _query.__class__.__name__ in {"Delete", "Update", "Insert"}
        if is_dml:
            self.executed.append(_query)
            return None
        if not self.exec_results:
            raise AssertionError("No more exec_results left for session.exec")
        return self.exec_results.pop(0)

    async def execute(self, statement):
        self.executed.append(statement)

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_dependency_ids_by_task_id_empty_short_circuit():
    session = _FakeSession(exec_results=[])
    result = await task_dependencies.dependency_ids_by_task_id(
        session,
        board_id=uuid4(),
        task_ids=[],
    )
    assert result == {}


@pytest.mark.asyncio
async def test_dependency_ids_by_task_id_groups_rows_by_task_id():
    task_id = uuid4()
    dep1 = uuid4()
    dep2 = uuid4()
    rows = [(task_id, dep1), (task_id, dep2)]

    session = _FakeSession(exec_results=[rows])
    result = await task_dependencies.dependency_ids_by_task_id(
        session,
        board_id=uuid4(),
        task_ids=[task_id],
    )
    assert result == {task_id: [dep1, dep2]}


@pytest.mark.asyncio
async def test_dependency_status_by_id_empty_short_circuit():
    session = _FakeSession(exec_results=[])
    result = await task_dependencies.dependency_status_by_id(
        session,
        board_id=uuid4(),
        dependency_ids=[],
    )
    assert result == {}


@pytest.mark.asyncio
async def test_dependency_status_by_id_maps_rows():
    dep = uuid4()
    session = _FakeSession(exec_results=[[(dep, "done")]])
    result = await task_dependencies.dependency_status_by_id(
        session,
        board_id=uuid4(),
        dependency_ids=[dep],
    )
    assert result == {dep: "done"}


@pytest.mark.asyncio
async def test_blocked_by_for_task_uses_passed_dependency_ids():
    board_id = uuid4()
    dep1 = uuid4()
    dep2 = uuid4()

    session = _FakeSession(exec_results=[[(dep1, "done"), (dep2, "inbox")]])
    blocked = await task_dependencies.blocked_by_for_task(
        session,
        board_id=board_id,
        task_id=uuid4(),
        dependency_ids=[dep1, dep2],
    )
    assert blocked == [dep2]


@pytest.mark.asyncio
async def test_blocked_by_for_task_fetches_dependency_ids_when_not_provided():
    board_id = uuid4()
    task_id = uuid4()
    dep = uuid4()

    # 1) dependency_ids_by_task_id -> {task_id: [dep]}
    # 2) dependency_status_by_id -> [(dep, "inbox")]
    session = _FakeSession(exec_results=[[(task_id, dep)], [(dep, "inbox")]])

    blocked = await task_dependencies.blocked_by_for_task(
        session,
        board_id=board_id,
        task_id=task_id,
        dependency_ids=None,
    )
    assert blocked == [dep]


@pytest.mark.asyncio
async def test_blocked_by_for_task_returns_empty_when_no_deps():
    board_id = uuid4()
    task_id = uuid4()

    # dependency_ids_by_task_id -> empty rows => no deps
    session = _FakeSession(exec_results=[[]])
    blocked = await task_dependencies.blocked_by_for_task(
        session,
        board_id=board_id,
        task_id=task_id,
        dependency_ids=None,
    )
    assert blocked == []


@pytest.mark.asyncio
async def test_validate_dependency_update_returns_empty_when_no_dependencies():
    session = _FakeSession(exec_results=[])
    result = await task_dependencies.validate_dependency_update(
        session,
        board_id=uuid4(),
        task_id=uuid4(),
        depends_on_task_ids=[],
    )
    assert result == []


@pytest.mark.asyncio
async def test_validate_dependency_update_rejects_self_dependency():
    task_id = uuid4()
    session = _FakeSession(exec_results=[])

    with pytest.raises(task_dependencies.HTTPException) as exc:
        await task_dependencies.validate_dependency_update(
            session,
            board_id=uuid4(),
            task_id=task_id,
            depends_on_task_ids=[task_id],
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_validate_dependency_update_rejects_missing_dependency_tasks():
    board_id = uuid4()
    task_id = uuid4()
    dep_id = uuid4()

    # existing_ids should not include dep_id
    session = _FakeSession(exec_results=[set()])

    with pytest.raises(task_dependencies.HTTPException) as exc:
        await task_dependencies.validate_dependency_update(
            session,
            board_id=board_id,
            task_id=task_id,
            depends_on_task_ids=[dep_id],
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["missing_task_ids"] == [str(dep_id)]


@pytest.mark.asyncio
async def test_validate_dependency_update_rejects_cycles(monkeypatch):
    board_id = uuid4()
    task_a = uuid4()
    task_b = uuid4()

    # existing_ids contains dependency
    existing_ids = {task_b}

    # task_ids list on board
    all_task_ids = [task_a, task_b]

    # existing edges: B depends on A, then set A depends on B => cycle
    existing_edges = [(task_b, task_a)]

    session = _FakeSession(exec_results=[existing_ids, all_task_ids, existing_edges])

    with pytest.raises(task_dependencies.HTTPException) as exc:
        await task_dependencies.validate_dependency_update(
            session,
            board_id=board_id,
            task_id=task_a,
            depends_on_task_ids=[task_b],
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_validate_dependency_update_returns_deduped_ids_when_ok():
    board_id = uuid4()
    task_id = uuid4()
    dep1 = uuid4()
    dep2 = uuid4()

    existing_ids = {dep1, dep2}
    all_task_ids = [task_id, dep1, dep2]
    existing_edges: list[tuple[UUID, UUID]] = []

    session = _FakeSession(exec_results=[existing_ids, all_task_ids, existing_edges])

    normalized = await task_dependencies.validate_dependency_update(
        session,
        board_id=board_id,
        task_id=task_id,
        depends_on_task_ids=[dep1, dep2, dep1],
    )

    assert normalized == [dep1, dep2]


@pytest.mark.asyncio
async def test_replace_task_dependencies_deletes_then_adds(monkeypatch):
    board_id = uuid4()
    task_id = uuid4()
    dep1 = uuid4()
    dep2 = uuid4()

    async def _fake_validate(*_args, **_kwargs):
        return [dep1, dep2]

    monkeypatch.setattr(task_dependencies, "validate_dependency_update", _fake_validate)

    session = _FakeSession(exec_results=[])
    normalized = await task_dependencies.replace_task_dependencies(
        session,
        board_id=board_id,
        task_id=task_id,
        depends_on_task_ids=[dep1, dep2],
    )

    assert normalized == [dep1, dep2]
    assert len(session.executed) == 1
    assert len(session.added) == 2


@pytest.mark.asyncio
async def test_dependent_task_ids_returns_rows_as_list():
    board_id = uuid4()
    dep_task_id = uuid4()
    dependent_id = uuid4()

    session = _FakeSession(exec_results=[[dependent_id]])
    result = await task_dependencies.dependent_task_ids(
        session,
        board_id=board_id,
        dependency_task_id=dep_task_id,
    )
    assert result == [dependent_id]
