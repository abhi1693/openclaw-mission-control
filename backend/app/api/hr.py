from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.utils import get_actor_employee_id, log_activity
from app.db.session import get_session
from app.integrations.openclaw import OpenClawClient
from app.models.hr import AgentOnboarding, EmploymentAction, HeadcountRequest
from app.models.org import Employee
from app.schemas.hr import (
    AgentOnboardingCreate,
    AgentOnboardingUpdate,
    EmploymentActionCreate,
    HeadcountRequestCreate,
    HeadcountRequestUpdate,
)

router = APIRouter(prefix="/hr", tags=["hr"])


@router.get("/headcount", response_model=list[HeadcountRequest])
def list_headcount_requests(session: Session = Depends(get_session)):
    return session.exec(select(HeadcountRequest).order_by(HeadcountRequest.id.desc())).all()


@router.post("/headcount", response_model=HeadcountRequest)
def create_headcount_request(
    payload: HeadcountRequestCreate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    req = HeadcountRequest(**payload.model_dump())
    session.add(req)
    session.commit()
    session.refresh(req)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="headcount_request", entity_id=req.id, verb="submitted")
    session.commit()
    return req


@router.patch("/headcount/{request_id}", response_model=HeadcountRequest)
def update_headcount_request(
    request_id: int,
    payload: HeadcountRequestUpdate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
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
        # If unique constraint on idempotency_key raced
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
def create_agent_onboarding(
    payload: AgentOnboardingCreate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    item = AgentOnboarding(**payload.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="agent_onboarding",
        entity_id=item.id,
        verb="created",
        payload={"agent_name": item.agent_name, "status": item.status},
    )
    session.commit()
    return item


@router.patch("/onboarding/{onboarding_id}", response_model=AgentOnboarding)
def update_agent_onboarding(
    onboarding_id: int,
    payload: AgentOnboardingUpdate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    item = session.get(AgentOnboarding, onboarding_id)
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding record not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    item.updated_at = datetime.utcnow()

    session.add(item)
    session.commit()
    session.refresh(item)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="agent_onboarding", entity_id=item.id, verb="updated", payload=data)
    session.commit()
    return item


@router.post("/onboarding/{onboarding_id}/provision", response_model=AgentOnboarding)
def provision_agent_onboarding(
    onboarding_id: int,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    """Provision an agent *session* via OpenClaw and wire it back into Mission Control.

    This removes the need for cron-based HR provisioning.
    """

    item = session.get(AgentOnboarding, onboarding_id)
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding record not found")

    if item.employee_id is None:
        raise HTTPException(status_code=400, detail="Onboarding must be linked to an employee_id before provisioning")

    client = OpenClawClient.from_env()
    if client is None:
        raise HTTPException(status_code=503, detail="OPENCLAW_GATEWAY_URL/TOKEN not configured")

    # Mark as spawning
    item.status = "spawning"
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)

    label = f"onboarding:{item.id}:{item.agent_name}"

    try:
        resp = client.tools_invoke(
            "sessions_spawn",
            {
                "task": item.prompt,
                "label": label,
                "agentId": "main",
                "cleanup": "keep",
                "runTimeoutSeconds": 600,
            },
            timeout_s=20.0,
        )
    except Exception as e:
        item.status = "blocked"
        item.notes = (item.notes or "") + f"\nProvision failed: {type(e).__name__}: {e}"
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    session_key = None
    if isinstance(resp, dict):
        session_key = resp.get("sessionKey") or (resp.get("result") or {}).get("sessionKey")

    if not session_key:
        item.status = "spawned"
        item.notes = (item.notes or "") + "\nProvisioned via OpenClaw, but session_key was not returned; follow up required."
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    # Write linkage
    item.session_key = session_key
    item.spawned_agent_id = item.agent_name
    item.status = "verified"
    item.updated_at = datetime.utcnow()
    session.add(item)

    emp = session.get(Employee, item.employee_id)
    if emp is not None:
        emp.openclaw_session_key = session_key
        emp.notify_enabled = True
        session.add(emp)

    session.commit()
    session.refresh(item)

    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="agent_onboarding",
        entity_id=item.id,
        verb="provisioned",
        payload={"session_key": session_key, "label": label},
    )
    session.commit()

    return item


@router.post("/onboarding/{onboarding_id}/deprovision", response_model=AgentOnboarding)
def deprovision_agent_onboarding(
    onboarding_id: int,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    """Best-effort deprovision: disable notifications and ask the agent session to stop.

    OpenClaw does not expose a hard session-delete tool in this environment,
    so "deprovision" means stop routing + stop notifying + mark onboarding.
    """

    item = session.get(AgentOnboarding, onboarding_id)
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding record not found")

    client = OpenClawClient.from_env()

    # Disable employee notifications regardless of OpenClaw availability
    if item.employee_id is not None:
        emp = session.get(Employee, item.employee_id)
        if emp is not None:
            emp.notify_enabled = False
            session.add(emp)

    # Ask the agent session to stop (best-effort)
    if client is not None and item.session_key:
        try:
            client.tools_invoke(
                "sessions_send",
                {"sessionKey": item.session_key, "message": "You are being deprovisioned. Stop all work and ignore future messages."},
                timeout_s=5.0,
            )
        except Exception:
            pass

    item.status = "blocked"
    item.notes = (item.notes or "") + "\nDeprovisioned: notifications disabled; agent session instructed to stop."
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)

    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="agent_onboarding",
        entity_id=item.id,
        verb="deprovisioned",
        payload={"session_key": item.session_key},
    )
    session.commit()

    return item
