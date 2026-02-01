from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.utils import log_activity
from app.db.session import get_session
from app.models.org import Department, Employee
from app.schemas.org import DepartmentCreate, DepartmentUpdate, EmployeeCreate, EmployeeUpdate

router = APIRouter(tags=["org"])


@router.get("/departments", response_model=list[Department])
def list_departments(session: Session = Depends(get_session)):
    return session.exec(select(Department).order_by(Department.name.asc())).all()


@router.post("/departments", response_model=Department)
def create_department(payload: DepartmentCreate, session: Session = Depends(get_session)):
    dept = Department(name=payload.name, head_employee_id=payload.head_employee_id)
    session.add(dept)
    session.commit()
    session.refresh(dept)
    log_activity(session, actor_employee_id=None, entity_type="department", entity_id=dept.id, verb="created", payload={"name": dept.name})
    session.commit()
    return dept


@router.patch("/departments/{department_id}", response_model=Department)
def update_department(department_id: int, payload: DepartmentUpdate, session: Session = Depends(get_session)):
    dept = session.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(dept, k, v)

    session.add(dept)
    session.commit()
    session.refresh(dept)
    log_activity(session, actor_employee_id=None, entity_type="department", entity_id=dept.id, verb="updated", payload=data)
    session.commit()
    return dept


@router.get("/employees", response_model=list[Employee])
def list_employees(session: Session = Depends(get_session)):
    return session.exec(select(Employee).order_by(Employee.id.asc())).all()


@router.post("/employees", response_model=Employee)
def create_employee(payload: EmployeeCreate, session: Session = Depends(get_session)):
    emp = Employee(**payload.model_dump())
    session.add(emp)
    session.commit()
    session.refresh(emp)
    log_activity(session, actor_employee_id=None, entity_type="employee", entity_id=emp.id, verb="created", payload={"name": emp.name, "type": emp.employee_type})
    session.commit()
    return emp


@router.patch("/employees/{employee_id}", response_model=Employee)
def update_employee(employee_id: int, payload: EmployeeUpdate, session: Session = Depends(get_session)):
    emp = session.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(emp, k, v)

    session.add(emp)
    session.commit()
    session.refresh(emp)
    log_activity(session, actor_employee_id=None, entity_type="employee", entity_id=emp.id, verb="updated", payload=data)
    session.commit()
    return emp
