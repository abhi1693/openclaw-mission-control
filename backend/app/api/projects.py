from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.utils import log_activity
from app.db.session import get_session
from app.models.projects import Project, ProjectMember
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


@router.get("/{project_id}/members", response_model=list[ProjectMember])
def list_project_members(project_id: int, session: Session = Depends(get_session)):
    return session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.id.asc())
    ).all()


@router.post("/{project_id}/members", response_model=ProjectMember)
def add_project_member(project_id: int, payload: ProjectMember, session: Session = Depends(get_session)):
    member = ProjectMember(project_id=project_id, employee_id=payload.employee_id, role=payload.role)
    session.add(member)
    session.commit()
    session.refresh(member)
    log_activity(
        session,
        actor_employee_id=None,
        entity_type="project_member",
        entity_id=member.id,
        verb="added",
        payload={"project_id": project_id, "employee_id": member.employee_id, "role": member.role},
    )
    session.commit()
    return member


@router.delete("/{project_id}/members/{member_id}")
def remove_project_member(project_id: int, member_id: int, session: Session = Depends(get_session)):
    member = session.get(ProjectMember, member_id)
    if not member or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project member not found")
    session.delete(member)
    session.commit()
    log_activity(
        session,
        actor_employee_id=None,
        entity_type="project_member",
        entity_id=member_id,
        verb="removed",
        payload={"project_id": project_id},
    )
    session.commit()
    return {"ok": True}


@router.patch("/{project_id}/members/{member_id}", response_model=ProjectMember)
def update_project_member(project_id: int, member_id: int, payload: ProjectMember, session: Session = Depends(get_session)):
    member = session.get(ProjectMember, member_id)
    if not member or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project member not found")

    if payload.role is not None:
        member.role = payload.role

    session.add(member)
    session.commit()
    session.refresh(member)
    log_activity(
        session,
        actor_employee_id=None,
        entity_type="project_member",
        entity_id=member.id,
        verb="updated",
        payload={"project_id": project_id, "role": member.role},
    )
    session.commit()
    return member
