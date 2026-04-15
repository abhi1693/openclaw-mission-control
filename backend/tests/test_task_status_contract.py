from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import tasks as tasks_api
from app.schemas.tasks import TaskUpdate


def test_task_update_accepts_rework_status() -> None:
    model = TaskUpdate(status="rework")
    assert model.status == "rework"


def test_task_update_accepts_cancelled_status() -> None:
    model = TaskUpdate(status="cancelled")
    assert model.status == "cancelled"


def test_status_filter_accepts_rework_and_cancelled() -> None:
    assert tasks_api._status_values("review,rework,cancelled") == [
        "review",
        "rework",
        "cancelled",
    ]


def test_status_filter_rejects_unknown_status() -> None:
    with pytest.raises(HTTPException) as exc:
        tasks_api._status_values("archived")

    assert exc.value.status_code == 422
    assert exc.value.detail == "Unsupported task status filter."
