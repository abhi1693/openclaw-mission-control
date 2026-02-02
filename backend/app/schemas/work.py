from __future__ import annotations

from sqlmodel import SQLModel


class TaskCreate(SQLModel):
    project_id: int
    title: str
    description: str | None = None
    status: str = "backlog"
    assignee_employee_id: int | None = None
    reviewer_employee_id: int | None = None
    created_by_employee_id: int | None = None


class TaskUpdate(SQLModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    assignee_employee_id: int | None = None
    reviewer_employee_id: int | None = None


class TaskCommentCreate(SQLModel):
    task_id: int
    author_employee_id: int | None = None
    reply_to_comment_id: int | None = None
    body: str
