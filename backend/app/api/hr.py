from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from app.api.utils import log_activity, get_actor_employee_id
from app.db.session import get_session
from app.models.hr import EmploymentAction, HeadcountRequest, AgentOnboarding
from app.schemas.hr import EmploymentActionCreate, HeadcountRequestCreate, HeadcountRequestUpdate, AgentOnboardingCreate, AgentOnboardingUpdate

router = APIRouter(prefix="/hr", tags=["hr"])


@router.get("/headcount", response_model=list[HeadcountRequest])
def list_headcount_requests(session: Session = Depends(get_session)):
    return session.exec(select(HeadcountRequest).order_by(HeadcountRequest.id.desc())).all()


@router.post("/headcount", response_model=HeadcountRequest)
def create_headcount_request(payload: HeadcountRequestCreate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    req = HeadcountRequest(**payload.model_dump())
    session.add(req)
    session.commit()
    session.refresh(req)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="headcount_request", entity_id=req.id, verb="submitted")
    session.commit()
    return req


@router.patch("/headcount/{request_id}", response_model=HeadcountRequest)
def update_headcount_request(request_id: int, payload: HeadcountRequestUpdate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    req = session.get(HeadcountRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("status") == "fulfilled" and getattr(req, "fulfilled_at", None) is None:
        req.fulfilled_at = datetime.utcnow()
    for k, v in data.items():
        setattr(req, k, v)

    session.add(req)
    session.commit()
    session.refresh(req)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="headcount_request", entity_id=req.id, verb="updated", payload=data)
    session.commit()
    return req


@router.get("/actions", response_model=list[EmploymentAction])
def list_employment_actions(session: Session = Depends(get_session)):
    return session.exec(select(EmploymentAction).order_by(EmploymentAction.id.desc())).all()


@router.post("/actions", response_model=EmploymentAction)
def create_employment_action(
    payload: EmploymentActionCreate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    # Prefer explicit payload key; header can supply one for retry-safety.
    if payload.idempotency_key is None and idempotency_key is not None:
        payload = EmploymentActionCreate(**{**payload.model_dump(), "idempotency_key": idempotency_key})

    if payload.idempotency_key:
        existing = session.exec(select(EmploymentAction).where(EmploymentAction.idempotency_key == payload.idempotency_key)).first()
        if existing:
            return existing

    action = EmploymentAction(**payload.model_dump())
    session.add(action)

    try:
        session.flush()
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="employment_action",
            entity_id=action.id,
            verb=action.action_type,
            payload={"employee_id": action.employee_id},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        # if unique constraint on idempotency_key raced
        if payload.idempotency_key:
            existing = session.exec(select(EmploymentAction).where(EmploymentAction.idempotency_key == payload.idempotency_key)).first()
            if existing:
                return existing
        raise HTTPException(status_code=409, detail="Employment action violates constraints")

    session.refresh(action)
    return EmploymentAction.model_validate(action)

@router.get("/onboarding", response_model=list[AgentOnboarding])
def list_agent_onboarding(session: Session = Depends(get_session)):
    return session.exec(select(AgentOnboarding).order_by(AgentOnboarding.id.desc())).all()


@router.post("/onboarding", response_model=AgentOnboarding)
def create_agent_onboarding(payload: AgentOnboardingCreate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    item = AgentOnboarding(**payload.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="agent_onboarding", entity_id=item.id, verb="created", payload={"agent_name": item.agent_name, "status": item.status})
    session.commit()
    return item


@router.patch("/onboarding/{onboarding_id}", response_model=AgentOnboarding)
def update_agent_onboarding(onboarding_id: int, payload: AgentOnboardingUpdate, session: Session = Depends(get_session), actor_employee_id: int = Depends(get_actor_employee_id)):
    item = session.get(AgentOnboarding, onboarding_id)
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding record not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("status") == "fulfilled" and getattr(req, "fulfilled_at", None) is None:
        req.fulfilled_at = datetime.utcnow()
    for k, v in data.items():
        setattr(item, k, v)
    from datetime import datetime
    item.updated_at = datetime.utcnow()

    session.add(item)
    session.commit()
    session.refresh(item)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="agent_onboarding", entity_id=item.id, verb="updated", payload=data)
    session.commit()
    return item

