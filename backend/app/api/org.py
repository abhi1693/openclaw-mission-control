from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.utils import get_actor_employee_id, log_activity
from app.core.urls import public_api_base_url
from app.db.session import get_session
from app.integrations.openclaw import OpenClawClient
from app.models.org import Department, Employee, Team
from app.schemas.org import (
    DepartmentCreate,
    DepartmentUpdate,
    EmployeeCreate,
    EmployeeUpdate,
    TeamCreate,
    TeamUpdate,
)

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
        f"- Base URL: {public_api_base_url()}\n"
        "- Auth: none. REQUIRED header on ALL write operations: X-Actor-Employee-Id: <your_employee_id>\n"
        f"  Example for you: X-Actor-Employee-Id: {emp.id}\n\n"
        "How to execute writes from an OpenClaw agent (IMPORTANT):\n"
        "- Use the exec tool to run curl against the Base URL above.\n"
        "- Example: start a task\n"
        "  curl -sS -X PATCH $BASE/tasks/<TASK_ID> -H 'X-Actor-Employee-Id: <your_employee_id>' -H 'Content-Type: application/json' -d '{\"status\":\"in_progress\"}'\n"
        "- Example: add a progress comment\n"
        "  curl -sS -X POST $BASE/task-comments -H 'X-Actor-Employee-Id: <your_employee_id>' -H 'Content-Type: application/json' -d '{\"task_id\":<TASK_ID>,\"body\":\"...\"}'\n\n"
        "Common endpoints (JSON):\n"
        "- GET /tasks, POST /tasks\n"
        "- GET /task-comments, POST /task-comments\n"
        "- GET /projects, GET /employees, GET /departments\n"
        "- OpenAPI schema: GET /openapi.json\n\n"
        "Rules:\n"
        "- Use the Mission Control API only (no UI).\n"
        "- You are responsible for driving assigned work to completion.\n"
        "- For every task you own: (1) read it, (2) plan next steps, (3) post progress comments, (4) update status as it moves (backlog/ready/in_progress/review/done/blocked).\n"
        "- Always leave an audit trail: add a comment whenever you start work, whenever you learn something important, and whenever you change status.\n"
        "- If blocked, set status=blocked and comment what you need (missing access, unclear requirements, etc.).\n"
        "- When notified about tasks/comments, respond with concise, actionable updates and immediately sync the task state in Mission Control.\n"
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


@router.get("/teams", response_model=list[Team])
def list_teams(department_id: int | None = None, session: Session = Depends(get_session)):
    q = select(Team)
    if department_id is not None:
        q = q.where(Team.department_id == department_id)
    return session.exec(q.order_by(Team.name.asc())).all()


@router.post("/teams", response_model=Team)
def create_team(
    payload: TeamCreate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    team = Team(**payload.model_dump())
    session.add(team)

    try:
        session.flush()
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="team",
            entity_id=team.id,
            verb="created",
            payload={
                "name": team.name,
                "department_id": team.department_id,
                "lead_employee_id": team.lead_employee_id,
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Team already exists or violates constraints")

    session.refresh(team)
    return team


@router.patch("/teams/{team_id}", response_model=Team)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    session: Session = Depends(get_session),
    actor_employee_id: int = Depends(get_actor_employee_id),
):
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(team, k, v)

    session.add(team)
    try:
        session.flush()
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="team",
            entity_id=team.id,
            verb="updated",
            payload=data,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Team update violates constraints")

    session.refresh(team)
    return team


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
        raise HTTPException(
            status_code=409, detail="Department already exists or violates constraints"
        )

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
    log_activity(
        session,
        actor_employee_id=actor_employee_id,
        entity_type="department",
        entity_id=dept.id,
        verb="updated",
        payload=data,
    )
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
        log_activity(
            session,
            actor_employee_id=actor_employee_id,
            entity_type="employee",
            entity_id=emp.id,
            verb="updated",
            payload=data,
        )
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
                {
                    "sessionKey": emp.openclaw_session_key,
                    "message": "You are being deprovisioned. Stop all work and ignore future messages.",
                },
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
