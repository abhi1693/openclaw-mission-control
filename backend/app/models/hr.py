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


class AgentOnboarding(SQLModel, table=True):
    __tablename__ = "agent_onboardings"

    id: int | None = Field(default=None, primary_key=True)
    agent_name: str
    role_title: str
    prompt: str
    cron_interval_ms: int | None = None
    tools_json: str | None = None
    owner_hr_id: int | None = Field(default=None, foreign_key="employees.id")

    status: str = Field(default="planned")  # planned|spawning|spawned|verified|blocked
    spawned_agent_id: str | None = None
    session_key: str | None = None

    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
