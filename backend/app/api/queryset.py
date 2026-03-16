"""API-level thin wrapper around query-set helpers with HTTP conveniences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from fastapi import HTTPException, status

from app.db.queryset import QuerySet, qs

if TYPE_CHECKING:
    from sqlalchemy.orm import Mapped
    from sqlalchemy.sql.elements import ColumnElement
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import SelectOfScalar

ModelT = TypeVar("ModelT")


@dataclass(frozen=True)
class APIQuerySet(Generic[ModelT]):
    """Immutable query-set wrapper tailored for API-layer usage."""

    queryset: QuerySet[ModelT]

    @property
    def statement(self) -> SelectOfScalar[ModelT]:
        """Expose the underlying SQL statement for advanced composition."""
        return self.queryset.statement

    def filter(
        self,
        *criteria: ColumnElement[bool] | bool,
    ) -> APIQuerySet[ModelT]:
        """Return a new queryset with additional SQL criteria applied."""
        return APIQuerySet(self.queryset.filter(*criteria))

    def order_by(
        self,
        *ordering: Mapped[Any] | ColumnElement[Any] | str,
    ) -> APIQuerySet[ModelT]:
        """Return a new queryset with ordering clauses applied."""
        return APIQuerySet(self.queryset.order_by(*ordering))

    def limit(self, value: int) -> APIQuerySet[ModelT]:
        """Return a new queryset with a row limit applied."""
        return APIQuerySet(self.queryset.limit(value))

    def offset(self, value: int) -> APIQuerySet[ModelT]:
        """Return a new queryset with an offset applied."""
        return APIQuerySet(self.queryset.offset(value))

    async def all(self, session: AsyncSession) -> list[ModelT]:
        """Fetch all rows for the current queryset."""
        return await self.queryset.all(session)

    async def first(self, session: AsyncSession) -> ModelT | None:
        """Fetch the first row for the current queryset, if present."""
        return await self.queryset.first(session)

    async def first_or_404(
        self,
        session: AsyncSession,
        *,
        detail: str | None = None,
    ) -> ModelT:
        """Fetch the first row or raise HTTP 404 when no row exists."""
        obj = await self.first(session)
        if obj is not None:
            return obj
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def api_qs(model: type[ModelT]) -> APIQuerySet[ModelT]:
    """Create an APIQuerySet for a SQLModel class."""
    return APIQuerySet(qs(model))
