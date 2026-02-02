from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.utils import log_activity, get_actor_employee_id
from app.db.session import get_session
from app.models.work import Task, TaskComment
from app.schemas.work import TaskCommentCreate, TaskCreate, TaskUpdate

router = APIRouter(tags=["work"])

ALLOWED_STATUSES = {"backlog", "ready", "in_progress", "review", "done", "blocked"}


@router.get("/tasks", response_model=list[Task])
def list_tasks(project_id: int | None = None, session: Session = Depends(get_session)):
    stmt = select(Task).order_by(Task.id.asc())
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    return session.exec(stmt).all()


@router.post("/tasks", response_model=Task)
def create_task(payload: TaskCreate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    if payload.created_by_employee_id is None:
        payload = TaskCreate(**{**payload.model_dump(), "created_by_employee_id": actor_employee_id})
    task = Task(**payload.model_dump())
    if task.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="task",
        entity_id=task.id,
        verb="created",
        payload={"project_id": task.project_id, "title": task.title},
    )
    session.commit()
    return task


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, payload: TaskUpdate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    for k, v in data.items():
        setattr(task, k, v)
    task.updated_at = datetime.utcnow()

    session.add(task)
    session.commit()
    session.refresh(task)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="task", entity_id=task.id, verb="updated", payload=data)
    session.commit()
    return task


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.commit()
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="task", entity_id=task_id, verb="deleted")
    session.commit()
    return {"ok": True}


@router.get("/task-comments", response_model=list[TaskComment])
def list_task_comments(task_id: int, session: Session = Depends(get_session)):
    return session.exec(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.id.asc())).all()


@router.post("/task-comments", response_model=TaskComment)
def create_task_comment(payload: TaskCommentCreate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    if payload.author_employee_id is None:
        payload = TaskCommentCreate(**{**payload.model_dump(), "author_employee_id": actor_employee_id})
    c = TaskComment(**payload.model_dump())

    # Validate reply target (must exist + belong to same task)
    if c.reply_to_comment_id is not None:
        parent = session.get(TaskComment, c.reply_to_comment_id)
        if parent is None or parent.task_id != c.task_id:
            raise HTTPException(status_code=400, detail="Invalid reply_to_comment_id")
    session.add(c)
    session.commit()
    session.refresh(c)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="task", entity_id=c.task_id, verb="commented")
    session.commit()
    return c
