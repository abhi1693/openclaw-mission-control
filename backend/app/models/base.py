"""Base model mixins and shared SQLModel abstractions."""

from __future__ import annotations

from typing import ClassVar, Self

from sqlmodel import SQLModel

from app.db.query_manager import ManagerDescriptor


class QueryModel(SQLModel, table=False):
    """Base SQLModel with a shared query manager descriptor."""

    objects: ClassVar[ManagerDescriptor[Self]] = ManagerDescriptor()
