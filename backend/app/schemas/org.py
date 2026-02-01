from __future__ import annotations

from sqlmodel import SQLModel


class DepartmentCreate(SQLModel):
    name: str
    head_employee_id: int | None = None


class DepartmentUpdate(SQLModel):
    name: str | None = None
    head_employee_id: int | None = None


class EmployeeCreate(SQLModel):
    name: str
    employee_type: str
    department_id: int | None = None
    manager_id: int | None = None
    title: str | None = None
    status: str = "active"


class EmployeeUpdate(SQLModel):
    name: str | None = None
    employee_type: str | None = None
    department_id: int | None = None
    manager_id: int | None = None
    title: str | None = None
    status: str | None = None
