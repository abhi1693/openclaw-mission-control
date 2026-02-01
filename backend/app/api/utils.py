from __future__ import annotations

import json
from typing import Any

from fastapi import Header, HTTPException
from sqlmodel import Session

from app.models.activity import Activity


def log_activity(
    session: Session,
    *,
    actor_employee_id: int | None,
    entity_type: str,
    entity_id: int | None,
    verb: str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        Activity(
            actor_employee_id=actor_employee_id,
            entity_type=entity_type,
            entity_id=entity_id,
            verb=verb,
            payload_json=json.dumps(payload) if payload is not None else None,
        )
    )


def get_actor_employee_id(
    x_actor_employee_id: int | None = Header(default=None, alias="X-Actor-Employee-Id"),
) -> int:
    if x_actor_employee_id is None:
        raise HTTPException(status_code=400, detail="X-Actor-Employee-Id required")
    return x_actor_employee_id
