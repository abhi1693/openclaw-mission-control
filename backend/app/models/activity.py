from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Activity(SQLModel, table=True):
    __tablename__ = "activities"

    id: int | None = Field(default=None, primary_key=True)
    actor_employee_id: int | None = Field(default=None, foreign_key="employees.id")

    entity_type: str
    entity_id: int | None = None
    verb: str

    payload_json: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
