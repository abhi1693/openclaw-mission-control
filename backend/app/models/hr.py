from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class HeadcountRequest(SQLModel, table=True):
    __tablename__ = "headcount_requests"

    id: int | None = Field(default=None, primary_key=True)
    department_id: int = Field(foreign_key="departments.id")
    requested_by_manager_id: int = Field(foreign_key="employees.id")

    role_title: str
    employee_type: str  # human | agent
    quantity: int = Field(default=1)

    justification: str | None = None
    status: str = Field(default="submitted")

    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmploymentAction(SQLModel, table=True):
    __tablename__ = "employment_actions"

    id: int | None = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employees.id")
    issued_by_employee_id: int = Field(foreign_key="employees.id")

    action_type: str  # praise|warning|pip|termination
    notes: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
