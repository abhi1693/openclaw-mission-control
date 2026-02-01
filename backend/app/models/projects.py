from __future__ import annotations

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    status: str = Field(default="active")


class ProjectMember(SQLModel, table=True):
    __tablename__ = "project_members"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id")
    employee_id: int = Field(foreign_key="employees.id")
    role: str | None = None
