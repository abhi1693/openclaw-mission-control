"""Lightweight immutable query-set wrapper for SQLModel statements."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from sqlmodel import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Mapped
    from sqlalchemy.sql.elements import ColumnElement
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import SelectOfScalar

ModelT = TypeVar("ModelT")


@dataclass(frozen=True)
class QuerySet(Generic[ModelT]):
    """Composable immutable wrapper around a SQLModel scalar select statement."""

    statement: SelectOfScalar[ModelT]

    def filter(
        self,
        *criteria: ColumnElement[bool] | bool,
    ) -> QuerySet[ModelT]:
        """Return a new queryset with additional SQL criteria."""
        statement = self.statement.where(*criteria)
        return replace(self, statement=statement)

    def where(
        self,
        *criteria: ColumnElement[bool] | bool,
    ) -> QuerySet[ModelT]:
        """Alias for `filter` to mirror SQLAlchemy naming."""
        return self.filter(*criteria)

    def filter_by(self, **kwargs: object) -> QuerySet[ModelT]:
        """Return a new queryset filtered by keyword-equality criteria."""
        statement = self.statement.filter_by(**kwargs)
        return replace(self, statement=statement)

    def order_by(
        self,
        *ordering: Mapped[Any] | ColumnElement[Any] | str,
    ) -> QuerySet[ModelT]:
        """Return a new queryset with ordering clauses applied."""
        statement = self.statement.order_by(*ordering)
        return replace(self, statement=statement)

    def limit(self, value: int) -> QuerySet[ModelT]:
        """Return a new queryset with a SQL row limit."""
        return replace(self, statement=self.statement.limit(value))

    def offset(self, value: int) -> QuerySet[ModelT]:
        """Return a new queryset with a SQL row offset."""
        return replace(self, statement=self.statement.offset(value))

    async def all(self, session: AsyncSession) -> list[ModelT]:
        """Execute and return all rows for the current queryset."""
        return list(await session.exec(self.statement))

    async def first(self, session: AsyncSession) -> ModelT | None:
        """Execute and return the first row, if available."""
        return (await session.exec(self.statement)).first()

    async def one_or_none(self, session: AsyncSession) -> ModelT | None:
        """Execute and return one row or `None`."""
        return (await session.exec(self.statement)).one_or_none()

    async def exists(self, session: AsyncSession) -> bool:
        """Return whether the queryset yields at least one row."""
        return await self.limit(1).first(session) is not None


def qs(model: type[ModelT]) -> QuerySet[ModelT]:
    """Create a base queryset for a SQLModel class."""
    return QuerySet(select(model))
