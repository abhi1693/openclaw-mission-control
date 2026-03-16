"""Model manager descriptor utilities for query-set style access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from sqlalchemy import false
from sqlmodel import SQLModel, col

from app.db.queryset import QuerySet, qs

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.sql.elements import ColumnElement

ModelT = TypeVar("ModelT", bound=SQLModel)


@dataclass(frozen=True)
class ModelManager(Generic[ModelT]):
    """Convenience query manager bound to a SQLModel class."""

    model: type[ModelT]
    id_field: str = "id"

    def all(self) -> QuerySet[ModelT]:
        """Return an unfiltered queryset for the bound model."""
        return qs(self.model)

    def none(self) -> QuerySet[ModelT]:
        """Return a queryset that yields no rows."""
        return qs(self.model).filter(false())

    def filter(
        self,
        *criteria: ColumnElement[bool] | bool,
    ) -> QuerySet[ModelT]:
        """Return queryset filtered by SQL criteria expressions."""
        return self.all().filter(*criteria)

    def where(
        self,
        *criteria: ColumnElement[bool] | bool,
    ) -> QuerySet[ModelT]:
        """Alias for `filter`."""
        return self.filter(*criteria)

    def filter_by(self, **kwargs: object) -> QuerySet[ModelT]:
        """Return queryset filtered by model field equality values."""
        queryset = self.all()
        for field_name, value in kwargs.items():
            queryset = queryset.filter(col(getattr(self.model, field_name)) == value)
        return queryset

    def by_id(self, obj_id: object) -> QuerySet[ModelT]:
        """Return queryset filtered by primary identifier field."""
        return self.by_field(self.id_field, obj_id)

    def by_ids(
        self,
        obj_ids: Iterable[object],
    ) -> QuerySet[ModelT]:
        """Return queryset filtered by a set/list/tuple of identifiers."""
        return self.by_field_in(self.id_field, obj_ids)

    def by_field(self, field_name: str, value: object) -> QuerySet[ModelT]:
        """Return queryset filtered by a single field equality check."""
        return self.filter(col(getattr(self.model, field_name)) == value)

    def by_field_in(
        self,
        field_name: str,
        values: Iterable[object],
    ) -> QuerySet[ModelT]:
        """Return queryset filtered by `field IN values` semantics."""
        seq = tuple(values)
        if not seq:
            return self.none()
        return self.filter(col(getattr(self.model, field_name)).in_(seq))


class ManagerDescriptor(Generic[ModelT]):
    """Descriptor that exposes a model-bound `ModelManager` as `.objects`."""

    # noinspection PyMethodMayBeStatic
    def __get__(self, instance: object, owner: type[ModelT]) -> ModelManager[ModelT]:
        """Return a fresh manager bound to the owning model class."""
        return ModelManager(owner)
