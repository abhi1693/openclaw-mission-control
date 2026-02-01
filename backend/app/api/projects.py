from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.utils import log_activity
from app.db.session import get_session
from app.models.projects import Project
from app.schemas.projects import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[Project])
def list_projects(session: Session = Depends(get_session)):
    return session.exec(select(Project).order_by(Project.name.asc())).all()


@router.post("", response_model=Project)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)):
    proj = Project(**payload.model_dump())
    session.add(proj)
    session.commit()
    session.refresh(proj)
    log_activity(session, actor_employee_id=None, entity_type="project", entity_id=proj.id, verb="created", payload={"name": proj.name})
    session.commit()
    return proj


@router.patch("/{project_id}", response_model=Project)
def update_project(project_id: int, payload: ProjectUpdate, session: Session = Depends(get_session)):
    proj = session.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(proj, k, v)

    session.add(proj)
    session.commit()
    session.refresh(proj)
    log_activity(session, actor_employee_id=None, entity_type="project", entity_id=proj.id, verb="updated", payload=data)
    session.commit()
    return proj
