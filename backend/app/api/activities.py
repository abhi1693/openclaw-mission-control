from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.activity import Activity

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("")
def list_activities(limit: int = 50, session: Session = Depends(get_session)):
    items = session.exec(select(Activity).order_by(Activity.id.desc()).limit(max(1, min(limit, 200)))).all()
    out = []
    for a in items:
        out.append(
            {
                "id": a.id,
                "actor_employee_id": a.actor_employee_id,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "verb": a.verb,
                "payload": json.loads(a.payload_json) if a.payload_json else None,
                "created_at": a.created_at,
            }
        )
    return out
