"""RQ worker entrypoints for GitHub check reconciliation."""

from __future__ import annotations

import asyncio
import time

from app.core.logging import get_logger
from app.services.github.mission_control_approval_check import (
    github_approval_check_enabled,
    reconcile_mission_control_approval_checks_for_all_boards,
)

logger = get_logger(__name__)


def run_reconcile_mission_control_approval_checks() -> None:
    """RQ entrypoint for periodically reconciling mission-control/approval checks."""
    if not github_approval_check_enabled():
        logger.info("github.approval_check.reconcile.skipped_missing_token")
        return

    start = time.time()
    logger.info("github.approval_check.reconcile.started")
    count = asyncio.run(reconcile_mission_control_approval_checks_for_all_boards())
    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(
        "github.approval_check.reconcile.finished",
        extra={"duration_ms": elapsed_ms, "pr_urls": count},
    )
