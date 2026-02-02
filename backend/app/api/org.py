from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.utils import get_actor_employee_id, log_activity
from app.db.session import get_session
from app.integrations.openclaw import OpenClawClient
from app.models.org import Department, Employee
from app.schemas.org import DepartmentCreate, DepartmentUpdate, EmployeeCreate, EmployeeUpdate

router = APIRouter(tags=["org"])


def _default_agent_prompt(emp: Employee) -> str:
    """Generate a conservative default prompt for a newly-created agent employee.

    We keep this short and deterministic; the human can refine later.
    """

    title = emp.title or "Agent"
    dept = str(emp.department_id) if emp.department_id is not None else "(unassigned)"

    return (
        f"You are {emp.name}, an AI agent employee in Mission Control.\n"
        f"Your employee_id is {emp.id}.\n"
        f"Title: {title}. Department id: {dept}.\n\n"
        "Mission Control API access (no UI):\n"
        "- Base URL: http://127.0.0.1:8000 (if running locally) OR http://<dev-machine-ip>:8000\n"
        "- Auth: none. REQUIRED header on write operations: X-Actor-Employee-Id: <your employee_id>\n"
        f"  For you: X-Actor-Employee-Id: {emp.id}\n\n"
        "Common endpoints (JSON):\n"
        "- GET /tasks, POST /tasks\n"
        "- GET /task-comments, POST /task-comments\n"
        "- GET /projects, GET /employees, GET /departments\n"
        "- OpenAPI schema: GET /openapi.json\n\n"
        "Rules:\n"
        "- Use the Mission Control API only (no UI).\n"
        "- When notified about tasks/comments, respond with concise, actionable updates.\n"
        "- Do not invent facts; ask for missing context.\n"
    )


def _maybe_auto_provision_agent(session: Session, *, emp: Employee, actor_employee_id: int) -> None:
    """Auto-provision an OpenClaw session for an agent employee.

    This is intentionally best-effort. If OpenClaw is not configured or the call fails,
    we leave the employee as-is (openclaw_session_key stays null).
    """

    if emp.employee_type != "agent":
        return
    if emp.status != "active":
        return
    if not emp.notify_enabled:
        return
    if emp.openclaw_session_key:
        return

    client = OpenClawClient.from_env()
    if client is None:
        return

    label = f"employee:{emp.id}:{emp.name}"
    try:
        resp = client.tools_invoke(
            "sessions_spawn",
            {
                "task": _default_agent_prompt(emp),
                "label": label,
                "agentId": "main",
                "cleanup": "keep",
                "runTimeoutSeconds": 600,
            },
            timeout_s=20.0,
        )
    except Exception as e:
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="employee",
            entity_id=emp.id,
            verb="provision_failed",
            payload={"error": f"{type(e).__name__}: {e}"},
        )
        return

    session_key = None
    if isinstance(resp, dict):
        session_key = resp.get("sessionKey")
    if not session_key:
        result = resp.get("result") or {}
        if isinstance(result, dict):
            session_key = result.get("sessionKey") or result.get("childSessionKey")
        details = (result.get("details") if isinstance(result, dict) else None) or {}
        if isinstance(details, dict):
            session_key = session_key or details.get("sessionKey") or details.get("childSessionKey")

    if not session_key:
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="employee",
            entity_id=emp.id,
            verb="provision_incomplete",
            payload={"label": label},
        )
        return

    emp.openclaw_session_key = session_key
    session.add(emp)
    session.flush()

    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="employee",
        entity_id=emp.id,
        verb="provisioned",
        payload={"session_key": session_key, "label": label},
    )


@router.get("/departments", response_model=list[Department])
def list_departments(session: Session = Depends(get_session)):
    return session.exec(select(Department).order_by(Department.name.asc())).all()


@router.post("/departments", response_model=Department)
def create_department(
    payload: DepartmentCreate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    """Create a department.

    Important: keep the operation atomic. We flush to get dept.id, log the activity,
    then commit once. We also translate common DB integrity errors into 409s.
    """

    dept = Department(name=payload.name, head_employee_id=payload.head_employee_id)
    session.add(dept)

    try:
        session.flush()  # assigns dept.id without committing
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="department",
            entity_id=dept.id,
            verb="created",
            payload={"name": dept.name},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Department already exists or violates constraints")

    session.refresh(dept)
    return dept


@router.patch("/departments/{department_id}", response_model=Department)
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    dept = session.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(dept, k, v)

    session.add(dept)
    session.commit()
    session.refresh(dept)
    log_activity(session, actor_employee_id=actor_employee_id, entity_type="department", entity_id=dept.id, verb="updated", payload=data)
    session.commit()
    return dept


@router.get("/employees", response_model=list[Employee])
def list_employees(session: Session = Depends(get_session)):
    return session.exec(select(Employee).order_by(Employee.id.asc())).all()


@router.post("/employees", response_model=Employee)
def create_employee(
    payload: EmployeeCreate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    emp = Employee(**payload.model_dump())
    session.add(emp)

    try:
        session.flush()
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="employee",
            entity_id=emp.id,
            verb="created",
            payload={"name": emp.name, "type": emp.employee_type},
        )

        # AUTO-PROVISION: if this is an agent employee, try to create an OpenClaw session.
        _maybe_auto_provision_agent(session, emp=emp, actor_employee_id=actor_employee_id)

        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Employee create violates constraints")

    session.refresh(emp)
    return Employee.model_validate(emp)


@router.patch("/employees/{employee_id}", response_model=Employee)
def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    emp = session.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(emp, k, v)

    session.add(emp)
    try:
        session.flush()
        log_activity(session, actor_employee_id=actor_employee_id, entity_type="employee", entity_id=emp.id, verb="updated", payload=data)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Employee update violates constraints")

    session.refresh(emp)
    return Employee.model_validate(emp)


@router.post("/employees/{employee_id}/provision", response_model=Employee)
def provision_employee_agent(
    employee_id: int,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    emp = session.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if emp.employee_type != "agent":
        raise HTTPException(status_code=400, detail="Only agent employees can be provisioned")

    _maybe_auto_provision_agent(session, emp=emp, actor_employee_id=actor_employee_id)
    session.commit()
    session.refresh(emp)
    return Employee.model_validate(emp)


@router.post("/employees/{employee_id}/deprovision", response_model=Employee)
def deprovision_employee_agent(
    employee_id: int,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    emp = session.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if emp.employee_type != "agent":
        raise HTTPException(status_code=400, detail="Only agent employees can be deprovisioned")

    client = OpenClawClient.from_env()
    if client is not None and emp.openclaw_session_key:
        try:
            client.tools_invoke(
                "sessions_send",
                {"sessionKey": emp.openclaw_session_key, "message": "You are being deprovisioned. Stop all work and ignore future messages."},
                timeout_s=5.0,
            )
        except Exception:
            pass

    emp.notify_enabled = False
    emp.openclaw_session_key = None
    session.add(emp)
    session.flush()

    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="employee",
        entity_id=emp.id,
        verb="deprovisioned",
        payload={},
    )

    session.commit()
    session.refresh(emp)
    return Employee.model_validate(emp)
