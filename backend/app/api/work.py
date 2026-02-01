from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.utils import log_activity
from app.db.session import get_session
from app.models.work import Task, TaskComment
from app.schemas.work import TaskCommentCreate, TaskCreate, TaskUpdate

router = APIRouter(tags=["work"])


@router.get("/tasks", response_model=list[Task])
def list_tasks(project_id: int | None = None, session: Session = Depends(get_session)):
    stmt = select(Task).order_by(Task.id.asc())
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    return session.exec(stmt).all()


@router.post("/tasks", response_model=Task)
def create_task(payload: TaskCreate, session: Session = Depends(get_session)):
    task = Task(**payload.model_dump())
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    log_activity(session, actor_employee_id=task.created_by_employee_id, entity_type="task", entity_id=task.id, verb="created", payload={"project_id": task.project_id, "title": task.title})
    session.commit()
    return task


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, payload: TaskUpdate, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(task, k, v)
    task.updated_at = datetime.utcnow()

    session.add(task)
    session.commit()
    session.refresh(task)
    log_activity(session, actor_employee_id=None, entity_type="task", entity_id=task.id, verb="updated", payload=data)
    session.commit()
    return task


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.commit()
    log_activity(session, actor_employee_id=None, entity_type="task", entity_id=task_id, verb="deleted")
    session.commit()
    return {"ok": True}


@router.get("/task-comments", response_model=list[TaskComment])
def list_task_comments(task_id: int, session: Session = Depends(get_session)):
    return session.exec(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.id.asc())).all()


@router.post("/task-comments", response_model=TaskComment)
def create_task_comment(payload: TaskCommentCreate, session: Session = Depends(get_session)):
    c = TaskComment(**payload.model_dump())
    session.add(c)
    session.commit()
    session.refresh(c)
    log_activity(session, actor_employee_id=c.author_employee_id, entity_type="task", entity_id=c.task_id, verb="commented")
    session.commit()
    return c
