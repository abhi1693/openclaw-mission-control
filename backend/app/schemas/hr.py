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


class AgentOnboardingCreate(SQLModel):
    agent_name: str
    role_title: str
    prompt: str
    cron_interval_ms: int | None = None
    tools_json: str | None = None
    owner_hr_id: int | None = None
    status: str = "planned"
    spawned_agent_id: str | None = None
    session_key: str | None = None
    notes: str | None = None


class AgentOnboardingUpdate(SQLModel):
    agent_name: str | None = None
    role_title: str | None = None
    prompt: str | None = None
    cron_interval_ms: int | None = None
    tools_json: str | None = None
    owner_hr_id: int | None = None
    status: str | None = None
    spawned_agent_id: str | None = None
    session_key: str | None = None
    notes: str | None = None

