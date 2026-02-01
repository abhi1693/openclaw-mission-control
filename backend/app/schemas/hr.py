from __future__ import annotations

from sqlmodel import SQLModel


class HeadcountRequestCreate(SQLModel):
    department_id: int
    requested_by_manager_id: int
    role_title: str
    employee_type: str
    quantity: int = 1
    justification: str | None = None


class HeadcountRequestUpdate(SQLModel):
    status: str | None = None
    justification: str | None = None


class EmploymentActionCreate(SQLModel):
    employee_id: int
    issued_by_employee_id: int
    action_type: str
    notes: str | None = None
