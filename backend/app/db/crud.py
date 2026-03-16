"""Generic asynchronous CRUD helpers for SQLModel entities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import SQLModel, select

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlmodel.sql.expression import SelectOfScalar

ModelT = TypeVar("ModelT", bound=SQLModel)


class DoesNotExistError(LookupError):
    """Raised when a query expected one row but found none."""


class MultipleObjectsReturnedError(LookupError):
    """Raised when a query expected one row but found many."""


DoesNotExist = DoesNotExistError
MultipleObjectsReturned = MultipleObjectsReturnedError


async def _flush_or_rollback(session: AsyncSession) -> None:
    """Flush changes and rollback on SQLAlchemy errors."""
    try:
        await session.flush()
    except SQLAlchemyError:
        await session.rollback()
        raise


async def _commit_or_rollback(session: AsyncSession) -> None:
    """Commit transaction and rollback on SQLAlchemy errors."""
    try:
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise


def _lookup_statement(
    model: type[ModelT],
    lookup: Mapping[str, Any],
) -> SelectOfScalar[ModelT]:
    """Build a select statement with equality filters from lookup values."""
    stmt = select(model)
    for key, value in lookup.items():
        stmt = stmt.where(getattr(model, key) == value)
    return stmt


async def get_by_id(
    session: AsyncSession,
    model: type[ModelT],
    obj_id: object,
) -> ModelT | None:
    """Fetch one model instance by id or return None."""
    stmt = _lookup_statement(model, {"id": obj_id}).limit(1)
    return (await session.exec(stmt)).first()


async def get(
    session: AsyncSession,
    model: type[ModelT],
    **lookup: object,
) -> ModelT:
    """Fetch exactly one model instance by lookup values."""
    stmt = _lookup_statement(model, lookup).limit(2)
    items = (await session.exec(stmt)).all()
    if not items:
        message = f"{model.__name__} matching query does not exist."
        raise DoesNotExist(message)
    if len(items) > 1:
        message = f"Multiple {model.__name__} objects returned for lookup {lookup!r}."
        raise MultipleObjectsReturned(message)
    return items[0]


async def get_one_by(
    session: AsyncSession,
    model: type[ModelT],
    **lookup: object,
) -> ModelT | None:
    """Fetch the first model instance matching lookup values."""
    stmt = _lookup_statement(model, lookup)
    return (await session.exec(stmt)).first()


async def create(
    session: AsyncSession,
    model: type[ModelT],
    *,
    commit: bool = True,
    refresh: bool = True,
    **data: object,
) -> ModelT:
    """Create, flush, optionally commit, and optionally refresh an object."""
    obj = model.model_validate(data)
    session.add(obj)
    await _flush_or_rollback(session)
    if commit:
        await _commit_or_rollback(session)
    if refresh:
        await session.refresh(obj)
    return obj


async def save(
    session: AsyncSession,
    obj: ModelT,
    *,
    commit: bool = True,
    refresh: bool = True,
) -> ModelT:
    """Persist an existing object with optional commit and refresh."""
    session.add(obj)
    await _flush_or_rollback(session)
    if commit:
        await _commit_or_rollback(session)
    if refresh:
        await session.refresh(obj)
    return obj


async def delete(session: AsyncSession, obj: SQLModel, *, commit: bool = True) -> None:
    """Delete an object with optional commit."""
    await session.delete(obj)
    if commit:
        await _commit_or_rollback(session)


async def list_by(
    session: AsyncSession,
    model: type[ModelT],
    *,
    order_by: Iterable[Any] = (),
    limit: int | None = None,
    offset: int | None = None,
    **lookup: object,
) -> list[ModelT]:
    """List objects by lookup values with optional ordering and pagination."""
    stmt = _lookup_statement(model, lookup)
    for ordering in order_by:
        stmt = stmt.order_by(ordering)
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(await session.exec(stmt))


async def exists(session: AsyncSession, model: type[ModelT], **lookup: object) -> bool:
    """Return whether any object exists for lookup values."""
    return (await session.exec(_lookup_statement(model, lookup).limit(1))).first() is not None


def _criteria_statement(
    model: type[ModelT],
    criteria: tuple[Any, ...],
) -> SelectOfScalar[ModelT]:
    """Build a select statement from variadic where criteria."""
    stmt = select(model)
    if criteria:
        stmt = stmt.where(*criteria)
    return stmt


async def list_where(
    session: AsyncSession,
    model: type[ModelT],
    *criteria: object,
    order_by: Iterable[Any] = (),
) -> list[ModelT]:
    """List objects filtered by explicit SQL criteria."""
    stmt = _criteria_statement(model, criteria)
    for ordering in order_by:
        stmt = stmt.order_by(ordering)
    return list(await session.exec(stmt))


async def delete_where(
    session: AsyncSession,
    model: type[ModelT],
    *criteria: object,
    commit: bool = False,
) -> int:
    """Delete rows matching criteria and return affected row count."""
    stmt: Any = sql_delete(model)
    if criteria:
        stmt = stmt.where(*criteria)
    result = await session.exec(stmt)
    if commit:
        await _commit_or_rollback(session)
    rowcount = getattr(result, "rowcount", None)
    return int(rowcount) if isinstance(rowcount, int) else 0


async def update_where(
    session: AsyncSession,
    model: type[ModelT],
    *criteria: object,
    updates: Mapping[str, Any] | None = None,
    **options: object,
) -> int:
    """Apply bulk updates by criteria and return affected row count."""
    commit = bool(options.pop("commit", False))
    exclude_none = bool(options.pop("exclude_none", False))
    allowed_fields_raw = options.pop("allowed_fields", None)
    allowed_fields = allowed_fields_raw if isinstance(allowed_fields_raw, set) else None
    source_updates: dict[str, Any] = {}
    if updates:
        source_updates.update(dict(updates))
    if options:
        source_updates.update(options)

    values: dict[str, Any] = {}
    for key, value in source_updates.items():
        if allowed_fields is not None and key not in allowed_fields:
            continue
        if exclude_none and value is None:
            continue
        values[key] = value
    if not values:
        return 0

    stmt: Any = sql_update(model).values(**values)
    if criteria:
        stmt = stmt.where(*criteria)
    result = await session.exec(stmt)
    if commit:
        await _commit_or_rollback(session)
    rowcount = getattr(result, "rowcount", None)
    return int(rowcount) if isinstance(rowcount, int) else 0


def apply_updates(
    obj: ModelT,
    updates: Mapping[str, Any],
    *,
    exclude_none: bool = False,
    allowed_fields: set[str] | None = None,
) -> ModelT:
    """Apply a mapping of field updates onto an object."""
    for key, value in updates.items():
        if allowed_fields is not None and key not in allowed_fields:
            continue
        if exclude_none and value is None:
            continue
        setattr(obj, key, value)
    return obj


async def patch(
    session: AsyncSession,
    obj: ModelT,
    updates: Mapping[str, Any],
    **options: object,
) -> ModelT:
    """Apply partial updates and persist object."""
    exclude_none = bool(options.pop("exclude_none", False))
    allowed_fields_raw = options.pop("allowed_fields", None)
    allowed_fields = allowed_fields_raw if isinstance(allowed_fields_raw, set) else None
    commit = bool(options.pop("commit", True))
    refresh = bool(options.pop("refresh", True))
    apply_updates(
        obj,
        updates,
        exclude_none=exclude_none,
        allowed_fields=allowed_fields,
    )
    return await save(session, obj, commit=commit, refresh=refresh)


async def get_or_create(
    session: AsyncSession,
    model: type[ModelT],
    *,
    defaults: Mapping[str, Any] | None = None,
    commit: bool = True,
    refresh: bool = True,
    **lookup: object,
) -> tuple[ModelT, bool]:
    """Get one object by lookup, or create it with defaults."""
    stmt = _lookup_statement(model, lookup)

    existing = (await session.exec(stmt)).first()
    if existing is not None:
        return existing, False

    payload: dict[str, Any] = dict(lookup)
    if defaults:
        for key, value in defaults.items():
            payload.setdefault(key, value)

    obj = model.model_validate(payload)
    session.add(obj)
    try:
        await session.flush()
        if commit:
            await session.commit()
    except IntegrityError:
        # If another concurrent request inserted the same unique row, surface that row.
        await session.rollback()
        existing = (await session.exec(stmt)).first()
        if existing is not None:
            return existing, False
        raise
    except SQLAlchemyError:
        await session.rollback()
        raise

    if refresh:
        await session.refresh(obj)
    return obj, True
