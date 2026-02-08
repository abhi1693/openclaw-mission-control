from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Field, SQLModel

from app.db import crud
from app.db import session as db_session


class _Thing(SQLModel, table=True):
    __tablename__ = "_test_thing"

    id: int | None = Field(default=None, primary_key=True)
    name: str


@dataclass
class _SessionCtx:
    session: Any
    entered: int = 0
    exited: int = 0

    async def __aenter__(self) -> Any:
        self.entered += 1
        return self.session

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> bool:
        self.exited += 1
        return False


@dataclass
class _Maker:
    ctx: _SessionCtx

    def __call__(self) -> _SessionCtx:
        return self.ctx


@pytest.mark.asyncio
async def test_get_session_rolls_back_on_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class _FakeDependencySession:
        rollbacks: int = 0

        def in_transaction(self) -> bool:
            return True

        async def rollback(self) -> None:
            self.rollbacks += 1

    fake_session = _FakeDependencySession()
    ctx = _SessionCtx(fake_session)
    monkeypatch.setattr(db_session, "async_session_maker", _Maker(ctx))

    generator = db_session.get_session()
    yielded = await generator.__anext__()
    assert yielded is fake_session

    with pytest.raises(RuntimeError, match="boom"):
        await generator.athrow(RuntimeError("boom"))

    assert fake_session.rollbacks == 1
    assert ctx.entered == 1
    assert ctx.exited == 1


@pytest.mark.asyncio
async def test_create_rolls_back_when_commit_fails() -> None:
    class _CommitError(SQLAlchemyError):
        pass

    @dataclass
    class _FailCommitSession:
        rollback_calls: int = 0
        added: list[Any] = None

        def __post_init__(self) -> None:
            if self.added is None:
                self.added = []

        def add(self, value: Any) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            raise _CommitError("commit failed")

        async def rollback(self) -> None:
            self.rollback_calls += 1

        async def refresh(self, _value: Any) -> None:
            return None

    session = _FailCommitSession()

    with pytest.raises(SQLAlchemyError, match="commit failed"):
        await crud.create(session, _Thing, name="demo")

    assert session.rollback_calls == 1
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_delete_where_rolls_back_when_commit_fails() -> None:
    class _CommitError(SQLAlchemyError):
        pass

    @dataclass
    class _FailCommitDmlSession:
        rollback_calls: int = 0
        exec_calls: int = 0

        async def exec(self, _statement: Any) -> Any:
            self.exec_calls += 1
            return SimpleNamespace(rowcount=3)

        async def commit(self) -> None:
            raise _CommitError("commit failed")

        async def rollback(self) -> None:
            self.rollback_calls += 1

    session = _FailCommitDmlSession()

    with pytest.raises(SQLAlchemyError, match="commit failed"):
        await crud.delete_where(session, _Thing, commit=True)

    assert session.exec_calls == 1
    assert session.rollback_calls == 1
