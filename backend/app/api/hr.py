from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.utils import log_activity
from app.db.session import get_session
from app.models.hr import EmploymentAction, HeadcountRequest
from app.schemas.hr import EmploymentActionCreate, HeadcountRequestCreate, HeadcountRequestUpdate

router = APIRouter(prefix="/hr", tags=["hr"])


@router.get("/headcount", response_model=list[HeadcountRequest])
def list_headcount_requests(session: Session = Depends(get_session)):
    return session.exec(select(HeadcountRequest).order_by(HeadcountRequest.id.desc())).all()


@router.post("/headcount", response_model=HeadcountRequest)
def create_headcount_request(payload: HeadcountRequestCreate, session: Session = Depends(get_session)):
    req = HeadcountRequest(**payload.model_dump())
    session.add(req)
    session.commit()
    session.refresh(req)
    log_activity(session, actor_employee_id=req.requested_by_manager_id, entity_type="headcount_request", entity_id=req.id, verb="submitted")
    session.commit()
    return req


@router.patch("/headcount/{request_id}", response_model=HeadcountRequest)
def update_headcount_request(request_id: int, payload: HeadcountRequestUpdate, session: Session = Depends(get_session)):
    req = session.get(HeadcountRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(req, k, v)

    session.add(req)
    session.commit()
    session.refresh(req)
    log_activity(session, actor_employee_id=req.requested_by_manager_id, entity_type="headcount_request", entity_id=req.id, verb="updated", payload=data)
    session.commit()
    return req


@router.get("/actions", response_model=list[EmploymentAction])
def list_employment_actions(session: Session = Depends(get_session)):
    return session.exec(select(EmploymentAction).order_by(EmploymentAction.id.desc())).all()


@router.post("/actions", response_model=EmploymentAction)
def create_employment_action(payload: EmploymentActionCreate, session: Session = Depends(get_session)):
    action = EmploymentAction(**payload.model_dump())
    session.add(action)
    session.commit()
    session.refresh(action)
    log_activity(session, actor_employee_id=action.issued_by_employee_id, entity_type="employment_action", entity_id=action.id, verb=action.action_type, payload={"employee_id": action.employee_id})
    session.commit()
    return action
