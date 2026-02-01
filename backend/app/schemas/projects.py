from __future__ import annotations

from sqlmodel import SQLModel


class ProjectCreate(SQLModel):
    name: str
    status: str = "active"


class ProjectUpdate(SQLModel):
    name: str | None = None
    status: str | None = None
