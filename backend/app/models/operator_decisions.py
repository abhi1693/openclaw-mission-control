"""OperatorDecision + OperatorDecisionTaskLink models (plan §I3).

Phase III §I3: operator decisions become first-class entities. The
legacy ``Task.operator_decision_required`` + ``operator_decision_summary``
flags keep working during the migration — this phase adds the new
entity without removing the old shape. The is_blocked derivation
will OR over both sources so a task is blocked if either the flag
or a pending ``OperatorDecision`` linked through this sidecar is open.

See docs/plans/2026-04-16-mc-delivery-enforcement-plan.md §I3 and
§"Phase III — Operator-decision compatibility bridge".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class OperatorDecision(TenantScoped, table=True):
    """First-class operator decision blocking one or more tasks."""

    __tablename__ = "operator_decisions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'cancelled')",
            name="ck_operator_decisions_status_values",
        ),
        # Hot dashboard lookup: "pending decisions on this board".
        # Phase III inbox routing + is_blocked bridge both filter on
        # ``status = 'pending'``, so a partial index beats a full
        # ``(board_id, status)`` b-tree on both size and selectivity.
        Index(
            "ix_operator_decisions_board_id_pending",
            "board_id",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    question: str
    # Who owns the decision. Null when the system escalates without
    # assignment — the operator picks it up from the inbox.
    owner_user_id: UUID | None = Field(
        default=None, foreign_key="users.id", index=True
    )
    # Free-text description of when / how this unblocks the linked
    # tasks. Not machine-evaluated in Phase III; becomes structured in
    # Phase IV once actionability enforcement lands.
    unblock_rule: str | None = None
    # Fine-grained reason code complementing the free-text ``unblock_rule``.
    # See ``app.services.blocker_reason_codes`` for the canonical recognised
    # registry; the schema is open-vocabulary so new codes can be added
    # without a migration.
    reason_code: str | None = Field(default=None, max_length=64)
    # Status isn't individually indexed — migration b10ca1ab1e04 dropped
    # the standalone ``ix_operator_decisions_status`` once the partial
    # ``ix_operator_decisions_board_id_pending`` above covers the only
    # access pattern that cares. Keep them in sync: do not re-add
    # ``index=True`` here.
    status: str = Field(default="pending")
    resolved_value: str | None = None
    # Who escalated the decision (agent or null for operator-authored).
    created_by_agent_id: UUID | None = Field(
        default=None, foreign_key="agents.id", index=True
    )
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class OperatorDecisionTaskLink(TenantScoped, table=True):
    """Join row linking an OperatorDecision to the tasks it blocks.

    Separate from ``Task.operator_decision_required`` (the legacy
    bool flag) so a single decision can block N tasks without writing
    to N rows, and so the compatibility bridge can preserve the flag
    while the entity graduates to source of truth.
    """

    __tablename__ = "operator_decision_task_links"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "decision_id",
            "task_id",
            name="uq_operator_decision_task_links_decision_id_task_id",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Prefix column of the unique constraint already indexes decision_id.
    decision_id: UUID = Field(foreign_key="operator_decisions.id")
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
