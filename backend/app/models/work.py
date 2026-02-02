from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: int | None = Field(default=None, primary_key=True)

    project_id: int = Field(foreign_key="projects.id", index=True)
    title: str
    description: str | None = None

    status: str = Field(default="backlog", index=True)

    assignee_employee_id: int | None = Field(default=None, foreign_key="employees.id")
    reviewer_employee_id: int | None = Field(default=None, foreign_key="employees.id")
    created_by_employee_id: int | None = Field(default=None, foreign_key="employees.id")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TaskComment(SQLModel, table=True):
    __tablename__ = "task_comments"

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="tasks.id", index=True)
    author_employee_id: int | None = Field(default=None, foreign_key="employees.id")

    # Optional reply threading
    reply_to_comment_id: int | None = Field(default=None, foreign_key="task_comments.id")

    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
