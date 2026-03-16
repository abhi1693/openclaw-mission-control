# ruff: noqa

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.models.tags import Tag
from app.services import tags


@dataclass
class _FakeSession:
    exec_results: list[object]
    executed: list[object] = field(default_factory=list)
    added: list[object] = field(default_factory=list)

    async def exec(self, query):
        self.executed.append(query)
        if not self.exec_results:
            raise AssertionError("No more exec_results left for session.exec")
        return self.exec_results.pop(0)

    def add(self, value):
        self.added.append(value)


def test_slugify_tag_normalizes_text():
    assert tags.slugify_tag("Release / QA") == "release-qa"
    assert tags.slugify_tag("  ###  ") == "tag"


@pytest.mark.asyncio
async def test_validate_tag_ids_dedupes_and_preserves_order():
    org_id = uuid4()
    tag_a = uuid4()
    tag_b = uuid4()
    session = _FakeSession(exec_results=[{tag_a, tag_b}])
    result = await tags.validate_tag_ids(
        session,
        organization_id=org_id,
        tag_ids=[tag_a, tag_b, tag_a],
    )
    assert result == [tag_a, tag_b]


@pytest.mark.asyncio
async def test_validate_tag_ids_rejects_missing_tags():
    org_id = uuid4()
    tag_a = uuid4()
    missing = uuid4()
    session = _FakeSession(exec_results=[{tag_a}])
    with pytest.raises(tags.HTTPException) as exc:
        await tags.validate_tag_ids(
            session,
            organization_id=org_id,
            tag_ids=[tag_a, missing],
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["missing_tag_ids"] == [str(missing)]


@pytest.mark.asyncio
async def test_load_tag_state_groups_rows_by_task_id():
    task_a = uuid4()
    task_b = uuid4()
    tag_a = uuid4()
    tag_b = uuid4()
    session = _FakeSession(
        exec_results=[
            [
                (
                    task_a,
                    Tag(
                        id=tag_a,
                        organization_id=uuid4(),
                        name="Backend",
                        slug="backend",
                        color="0f172a",
                    ),
                ),
                (
                    task_a,
                    Tag(
                        id=tag_b,
                        organization_id=uuid4(),
                        name="Urgent",
                        slug="urgent",
                        color="dc2626",
                    ),
                ),
                (
                    task_b,
                    Tag(
                        id=tag_b,
                        organization_id=uuid4(),
                        name="Urgent",
                        slug="urgent",
                        color="dc2626",
                    ),
                ),
            ],
        ],
    )
    state = await tags.load_tag_state(
        session,
        task_ids=[task_a, task_b],
    )
    assert state[task_a].tag_ids == [tag_a, tag_b]
    assert [tag.name for tag in state[task_a].tags] == ["Backend", "Urgent"]
    assert state[task_b].tag_ids == [tag_b]


@pytest.mark.asyncio
async def test_replace_tags_replaces_existing_links():
    task_id = uuid4()
    tag_a = uuid4()
    tag_b = uuid4()
    session = _FakeSession(exec_results=[None])
    await tags.replace_tags(
        session,
        task_id=task_id,
        tag_ids=[tag_a, tag_b, tag_a],
    )
    assert len(session.executed) == 1
    assert len(session.added) == 2
