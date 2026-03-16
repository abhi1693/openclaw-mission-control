# ruff: noqa: INP001
"""Queue worker registration tests for lifecycle reconcile tasks."""

from __future__ import annotations

from app.services.openclaw.lifecycle_queue import TASK_TYPE as LIFECYCLE_TASK_TYPE
from app.services.queue_worker import _TASK_HANDLERS


def test_worker_registers_lifecycle_reconcile_handler() -> None:
    assert LIFECYCLE_TASK_TYPE in _TASK_HANDLERS
