"""Blocker model — structured routing object for stuck work.

Phase II §I1: a task cannot be marked or treated as blocked purely by
free-text comment. Blockers are first-class records with category,
ownership, required artifact, and lifecycle columns so the Supervisor
can route from structured state rather than parsing prose.

Review-emitted blockers attach to a Review via ``review_blockers``
(Phase II §I4); ad-hoc blockers posted by the task owner or operator
stand alone. Both forms share this table.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Blocker(TenantScoped, table=True):
    """Structured blocker record attached to a task."""

    __tablename__ = "blockers"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "category IN ('source', 'deploy', 'runtime', 'contract', 'operator')",
            name="ck_blockers_category_values",
        ),
        # Single composite partial: board_id is always known at query
        # time (every endpoint is nested under /boards/{board_id}) so
        # both the per-task and board-wide "any open blocker" scans can
        # seek through this one index instead of BitmapAnd'ing two
        # separate partials.
        Index(
            "ix_blockers_board_id_task_id_open",
            "board_id",
            "task_id",
            sqlite_where=text("resolved_at IS NULL"),
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "uq_blockers_supersedes_blocker_id_open",
            "supersedes_blocker_id",
            unique=True,
            sqlite_where=text("supersedes_blocker_id IS NOT NULL"),
            postgresql_where=text("supersedes_blocker_id IS NOT NULL"),
        ),
        # Part D.1 feeder dedupe: closes the check-then-insert race on
        # subagent-failure ingest. Keyed on owner_role (the requested
        # child-agent role); covers (board_id, task_id) for partial-
        # index selection.
        Index(
            "uq_blockers_runtime_owner_open",
            "board_id",
            "task_id",
            "owner_role",
            unique=True,
            sqlite_where=text("category = 'runtime' AND resolved_at IS NULL"),
            postgresql_where=text("category = 'runtime' AND resolved_at IS NULL"),
        ),
        # Part D.2 feeder dedupe: closes the check-then-insert race on
        # stale-agent-session ingest. Keyed on required_artifact (the
        # operator-routing string); filters out NULL so ad-hoc operator
        # blockers without an artifact stay unconstrained.
        Index(
            "uq_blockers_operator_artifact_open",
            "board_id",
            "task_id",
            "required_artifact",
            unique=True,
            sqlite_where=text(
                "category = 'operator' "
                "AND resolved_at IS NULL "
                "AND required_artifact IS NOT NULL"
            ),
            postgresql_where=text(
                "category = 'operator' "
                "AND resolved_at IS NULL "
                "AND required_artifact IS NOT NULL"
            ),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    category: str
    # Fine-grained reason code complementing the coarse 5-value ``category``.
    # See ``app.services.blocker_reason_codes`` for the canonical recognised
    # registry; the schema is open-vocabulary so new codes can be added
    # without a migration.
    reason_code: str | None = Field(default=None, max_length=64)
    owner_role: str
    required_artifact: str | None = None
    target_env: str | None = None
    reopen_condition: str | None = None
    # Plan §I4: review-emitted blockers may carry a per-row citation
    # (quote / link / evidence). Null for ad-hoc blockers filed
    # through POST /blockers where the review-level narrative is
    # irrelevant.
    citation: str | None = None
    # Part E.4: structured request_id extracted from 4.20+
    # PAIRING_REQUIRED remediation messages. Promotion from the
    # free-form citation text makes the id searchable/sortable even
    # when the 512-char citation truncation clips it; the citation
    # itself retains the id verbatim for human readability.
    citation_request_id: str | None = Field(default=None, max_length=128)
    created_by_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    # Acknowledgement signals the receiving owner accepted the blocker.
    # Lane quieting (Phase VI §I6) keys off this.
    acknowledged_at: datetime | None = None
    acknowledged_by_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    # While open (resolved_at IS NULL), the is_blocked derivation
    # treats this row as active.
    resolved_at: datetime | None = None
    # Allows filing a sharper restatement of a prior blocker without
    # losing the audit trail. The superseding row should close the
    # prior row in the same transaction.
    supersedes_blocker_id: UUID | None = Field(default=None, foreign_key="blockers.id")
