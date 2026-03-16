"""Typed wrapper around fastapi-pagination for backend query helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi_pagination.ext.sqlalchemy import paginate as _paginate

from app.schemas.pagination import DefaultLimitOffsetPage

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import Select, SelectOfScalar

T = TypeVar("T")

Transformer = Callable[
    [Sequence[Any]],
    Sequence[Any] | Awaitable[Sequence[Any]],
]


async def paginate(
    session: AsyncSession,
    statement: Select[Any] | SelectOfScalar[Any],
    *,
    transformer: Transformer | None = None,
) -> LimitOffsetPage[T]:
    """Execute a paginated query and cast to the project page type alias."""
    page = await _paginate(session, statement, transformer=transformer)
    return DefaultLimitOffsetPage[T].model_validate(page)
