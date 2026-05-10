"""Agent-facing schemas for Part D.1 subagent-failure self-reporting.

Parent agents that detect a delegated child-agent failure (timeout,
tool-use error, unhandled exception) POST a report to the
``subagent-failure`` endpoint. MC converts the report into a
``runtime``-category ``Blocker`` row via
``app/services/subagent_failure_blocker.py``.

See ``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-
amendments.md`` Part D.1 for the wire contract.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field
from sqlmodel import SQLModel


class SubagentFailureReport(SQLModel):
    """Agent-self-reported subagent failure.

    Wire shape matches the eventual 4.20+ gateway push payload
    (``requested_role``, ``runtime_ms``, ``error_class``,
    ``parent_turn_id``). Used today by the parent agent's own
    delegation-failure path so D.1 ships without waiting for the
    gateway push-channel upgrade.
    """

    requested_role: str = Field(
        description=(
            "Role name of the child agent that failed — becomes the " "Blocker's owner_role."
        ),
        examples=["codex", "claude-haiku"],
        max_length=64,
    )
    runtime_ms: int = Field(
        ge=0,
        description="Elapsed ms from subagent dispatch to failure.",
    )
    error_class: str = Field(
        description=(
            "Short error class / tag (e.g. ``TimeoutError``, "
            "``BadGateway``). Surfaces in the Blocker citation."
        ),
        max_length=256,
    )
    parent_turn_id: str | None = Field(
        default=None,
        description=(
            "Optional gateway turn id for log correlation. Not " "load-bearing for routing."
        ),
        max_length=128,
    )


class SubagentFailureReportResponse(SQLModel):
    """Result of a self-report call.

    ``blocker_id`` is None when the report was accepted but no
    Blocker was filed — either because the board has not graduated
    ``structured_blockers_v1`` or because an open dedupe-matching
    Blocker already exists. The caller treats both as "recorded, no
    new routing object to act on".
    """

    blocker_id: UUID | None
