"""Schemas for task CRUD and task comment API payloads."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr
from app.schemas.tags import TagRef
from app.schemas.task_custom_fields import TaskCustomFieldValues

TaskStatus = Literal["inbox", "in_progress", "review", "rework", "done", "cancelled"]
ReviewPacketType = Literal[
    "frontend_ui",
    "backend_api",
    "review_only",
    "content_copy",
    "infra_ops",
    "mixed",
    "other",
]
ValidationTargetKind = Literal["live_url", "deploy_env", "workspace", "api_base", "other"]
ValidationTargetScope = Literal["review", "runtime", "deploy", "all"]
STATUS_REQUIRED_ERROR = "status is required"

# Phase V §I8: hex-SHA shape. Accepts abbreviated SHAs (git's default
# short form is 7 chars) through full 40-char SHA-1 digests. Rejects
# non-hex characters and lengths outside the git-plausible range so a
# fat-fingered branch name doesn't silently land in the packet field.
# Pre-compiled so the validator doesn't re-parse on every PATCH.
_SHA_HEX_RE = re.compile(r"^[0-9a-f]{7,40}$")

# Phase V §I8: validation_target is fetched server-side on every
# review/done transition (``deploy_truth.fetch_build_metadata`` issues
# an HTTP GET to ``{target}/__build``). That turns the field into an
# SSRF surface — a board writer who can PATCH a task can get MC to
# probe arbitrary internal URLs.
#
# MC's deployment is on a private LAN (Pi cluster + .64 prod box), so
# RFC1918 IPs are LEGITIMATE validation targets (e.g.
# ``http://192.168.2.60:3000``). We can't blanket-block private ranges.
# What we CAN block are:
#   * non-http(s) schemes (``file:``, ``ftp:``, ``gopher:``)
#   * loopback / link-local / cloud-metadata hosts that are never
#     legitimate targets but are attractive to a crafted-URL attacker
#     (IMDS, ``metadata.google.internal``, ``localhost``, etc.)
#   * missing hostnames, length bombs
_VALIDATION_TARGET_ALLOWED_SCHEMES = frozenset({"http", "https"})
_VALIDATION_TARGET_MAX_LENGTH = 2048
# Only these kinds are URL-shaped and fetched server-side by deploy-
# truth. ``workspace`` is a filesystem path, ``deploy_env`` is an env
# name, ``other`` is freeform — skip the SSRF guard for those.
_VALIDATION_TARGET_URL_KINDS: frozenset[str] = frozenset({"live_url", "api_base"})
# Hostnames and IP fragments that are never legitimate validation
# targets. Matched case-insensitively against the parsed hostname.
_VALIDATION_TARGET_BLOCKED_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        # AWS/Azure/GCP instance-metadata service:
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
    }
)
# Prefixes that shouldn't reach ``fetch_build_metadata`` — covers the
# full loopback / link-local / unspecified / IPv4-mapped-IPv6 ranges
# without dragging an ``ipaddress.ip_network`` import into schema-time
# validation.
_VALIDATION_TARGET_BLOCKED_PREFIXES: tuple[str, ...] = (
    "127.",           # 127.0.0.0/8 loopback
    "0.",             # 0.0.0.0/8 unspecified
    "169.254.",       # 169.254.0.0/16 link-local (incl. AWS IMDS)
    "fe80:",          # IPv6 link-local
    "fc00:",          # IPv6 unique-local
    "fd00:",          # IPv6 unique-local (alt)
    "::ffff:127.",    # IPv4-mapped loopback
    "::ffff:169.254.",  # IPv4-mapped link-local
)


def _strip_optional_text(value: object) -> object | None:
    """Shared blank→None + stripping for free-form optional strings."""

    if value is None:
        return None
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    return stripped or None


def _guard_url_shaped_target(
    target: str | None, kind: str | None, field_name: str
) -> None:
    """Schema-time SSRF guard.

    Fires only when ``kind`` says the target is a URL. Other kinds
    (``workspace``, ``deploy_env``, ``other``) are not server-side-
    fetched and keep their legacy free-form shape. Raises ``ValueError``
    on scheme / length / host-blocklist violations — Pydantic converts
    to a 422.
    """

    from urllib.parse import urlparse

    if target is None or kind not in _VALIDATION_TARGET_URL_KINDS:
        return
    if len(target) > _VALIDATION_TARGET_MAX_LENGTH:
        raise ValueError(
            f"{field_name} exceeds {_VALIDATION_TARGET_MAX_LENGTH} chars"
        )
    try:
        parsed = urlparse(target)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid URL: {exc}") from exc
    scheme = parsed.scheme.lower()
    if scheme not in _VALIDATION_TARGET_ALLOWED_SCHEMES:
        raise ValueError(
            f"{field_name} must use http:// or https:// when kind={kind!r} "
            f"(got {scheme!r})"
        )
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError(f"{field_name} is missing a hostname")
    if hostname in _VALIDATION_TARGET_BLOCKED_HOSTS:
        raise ValueError(
            f"{field_name} resolves to a blocked host ({hostname!r})"
        )
    for prefix in _VALIDATION_TARGET_BLOCKED_PREFIXES:
        if hostname.startswith(prefix):
            raise ValueError(
                f"{field_name} resolves to a blocked network prefix "
                f"({prefix!r})"
            )


def _normalise_and_validate_sha(value: object, field_name: str) -> object | None:
    """Shared by ``TaskBase`` + ``TaskUpdate`` — strips case, collapses
    blanks to None, and enforces the hex shape. Raising ``ValueError``
    here lets Pydantic turn the failure into a 422 on the API boundary.
    Non-string values pass through unchanged so Pydantic's built-in
    type check raises the canonical "string required" message.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        return value
    stripped = value.strip().lower()
    if not stripped:
        return None
    if not _SHA_HEX_RE.match(stripped):
        raise ValueError(f"{field_name} must be 7–40 lowercase hex characters")
    return stripped


# Central status-role registry. Each gate reads its membership set
# from one place so future phases can add a new key instead of a new
# module-level frozenset. Keys are referenced by name from api/tasks.py
# to keep the schema layer independent of handler-layer imports.
STATUS_GATES: dict[str, frozenset[str]] = {
    "delivery_contract": frozenset({"in_progress", "review", "done"}),
    "owner": frozenset({"in_progress", "done"}),
    # Phase 2: sync deploy-truth fires only on ``done`` transitions.
    # Review transitions use async deploy parity check instead
    # (pipeline-transition-gates design, 2026-04-25).
    "deploy_truth": frozenset({"done"}),
    # Pipeline-event POST gate: these statuses lack a valid in_progress
    # cycle anchor (rework/inbox) or are out of scope (cancelled), so
    # events posted under them are silently discarded or pollute audit
    # trails on dead work.
    "pipeline_event_rejected": frozenset({"rework", "inbox", "cancelled"}),
    # /deploy/notify webhook hard-rejects only cancelled (task removed
    # from scope; QA-ing it is unambiguously wrong). Other non-active
    # statuses (inbox/rework) are accepted with an audit row.
    "deploy_notify_rejected": frozenset({"cancelled"}),
}

DELIVERY_CONTRACT_REQUIRED_STATUSES = STATUS_GATES["delivery_contract"]
REVIEW_PACKET_TYPES_REQUIRING_VALIDATION_TARGET = frozenset(
    {"frontend_ui", "backend_api", "infra_ops", "mixed"}
)
# Keep these symbols as runtime globals so Pydantic can resolve
# deferred annotations reliably.
RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr, TagRef)


def status_requires_delivery_contract(status: TaskStatus | str | None) -> bool:
    return status in DELIVERY_CONTRACT_REQUIRED_STATUSES


def review_packet_type_requires_validation_target(
    review_packet_type: ReviewPacketType | str | None,
) -> bool:
    return review_packet_type in REVIEW_PACKET_TYPES_REQUIRING_VALIDATION_TARGET


def delivery_contract_missing_fields(
    *,
    status: TaskStatus | str | None,
    review_packet_type: ReviewPacketType | str | None,
    validation_target: str | None,
    validation_target_kind: ValidationTargetKind | str | None,
    validation_target_scope: ValidationTargetScope | str | None,
) -> list[str]:
    if not status_requires_delivery_contract(status):
        return []
    missing_fields: list[str] = []
    if review_packet_type is None:
        missing_fields.append("review_packet_type")
        return missing_fields
    if review_packet_type_requires_validation_target(review_packet_type):
        if validation_target is None:
            missing_fields.append("validation_target")
        if validation_target_kind is None:
            missing_fields.append("validation_target_kind")
        if validation_target_scope is None:
            missing_fields.append("validation_target_scope")
    return missing_fields


OWNER_REQUIRED_STATUSES = STATUS_GATES["owner"]


def status_requires_assigned_owner(status: TaskStatus | str | None) -> bool:
    """Phase IV §I2: owner required for active states where a specific
    agent is doing (or completed) the work.

    Excludes ``review`` because the codebase's review queue model
    explicitly unassigns on entry — the task awaits a reviewer, the
    assignment happens when they pick it up. Owner IS required for
    ``in_progress`` (someone is working) and ``done`` (someone did
    the work — preserves attribution).
    """

    return status in OWNER_REQUIRED_STATUSES


def actionability_missing_fields(
    *,
    status: TaskStatus | str | None,
    review_packet_type: ReviewPacketType | str | None,
    validation_target: str | None,
    validation_target_kind: ValidationTargetKind | str | None,
    validation_target_scope: ValidationTargetScope | str | None,
    assigned_agent_id: UUID | None,
) -> list[str]:
    """Phase IV §I2: union of delivery-contract fields + the
    assigned-owner check. Tasks entering ``in_progress`` / ``review``
    / ``done`` must carry the contract triplet; ``in_progress`` and
    ``done`` additionally require an owner (see
    ``status_requires_assigned_owner`` for the review-queue nuance).

    Returns the list of missing fields in stable order so callers can
    include it verbatim on the 409 payload without sorting.
    """

    if not status_requires_delivery_contract(status):
        return []
    missing: list[str] = []
    if status_requires_assigned_owner(status) and assigned_agent_id is None:
        missing.append("assigned_agent_id")
    missing.extend(
        delivery_contract_missing_fields(
            status=status,
            review_packet_type=review_packet_type,
            validation_target=validation_target,
            validation_target_kind=validation_target_kind,
            validation_target_scope=validation_target_scope,
        ),
    )
    return missing


class TaskBase(SQLModel):
    """Shared task fields used by task create/read payloads."""

    title: str
    description: str | None = None
    status: TaskStatus = "inbox"
    priority: str = "medium"
    due_at: datetime | None = None
    assigned_agent_id: UUID | None = None
    review_packet_type: ReviewPacketType | None = None
    validation_target: str | None = None
    validation_target_kind: ValidationTargetKind | None = None
    validation_target_scope: ValidationTargetScope | None = None
    packet_commit_sha: str | None = None
    packet_build_sha: str | None = None
    supports_build_metadata: bool | None = None
    operator_decision_required: bool = False
    operator_decision_summary: str | None = None
    depends_on_task_ids: list[UUID] = Field(default_factory=list)
    tag_ids: list[UUID] = Field(default_factory=list)
    # Phase V: parent task in a decomposition relationship. NULL on
    # standalone tasks. Set by ``lead-inbox-routing`` when creating
    # subtasks from a parent's decomposition plan; the cascade service
    # surfaces non-terminal children of terminal parents for cleanup.
    parent_task_id: UUID | None = None

    @field_validator(
        "validation_target",
        "operator_decision_summary",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        return _strip_optional_text(value)

    @field_validator("packet_commit_sha", mode="before")
    @classmethod
    def normalize_commit_sha(cls, value: object) -> object | None:
        return _normalise_and_validate_sha(value, "packet_commit_sha")

    @field_validator("packet_build_sha", mode="before")
    @classmethod
    def normalize_build_sha(cls, value: object) -> object | None:
        return _normalise_and_validate_sha(value, "packet_build_sha")

    @model_validator(mode="after")
    def validate_validation_target_triplet(self) -> Self:
        pieces = (
            self.validation_target,
            self.validation_target_kind,
            self.validation_target_scope,
        )
        if any(piece is not None for piece in pieces) and not all(piece is not None for piece in pieces):
            raise ValueError(
                "validation_target, validation_target_kind, and validation_target_scope must be provided together"
            )
        _guard_url_shaped_target(
            self.validation_target,
            self.validation_target_kind,
            "validation_target",
        )
        return self


class TaskCreate(TaskBase):
    """Payload for creating a task."""

    created_by_user_id: UUID | None = None
    custom_field_values: TaskCustomFieldValues = Field(default_factory=dict)


class TaskUpdate(SQLModel):
    """Payload for partial task updates."""

    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: str | None = None
    due_at: datetime | None = None
    assigned_agent_id: UUID | None = None
    review_packet_type: ReviewPacketType | None = None
    validation_target: str | None = None
    validation_target_kind: ValidationTargetKind | None = None
    validation_target_scope: ValidationTargetScope | None = None
    packet_commit_sha: str | None = None
    packet_build_sha: str | None = None
    supports_build_metadata: bool | None = None
    operator_decision_required: bool | None = None
    operator_decision_summary: str | None = None
    depends_on_task_ids: list[UUID] | None = None
    tag_ids: list[UUID] | None = None
    custom_field_values: TaskCustomFieldValues | None = None
    comment: NonEmptyStr | None = None

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: object) -> object | None:
        """Normalize blank comment strings to `None`."""
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "validation_target",
        "operator_decision_summary",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object | None:
        return _strip_optional_text(value)

    @field_validator("packet_commit_sha", mode="before")
    @classmethod
    def normalize_commit_sha(cls, value: object) -> object | None:
        return _normalise_and_validate_sha(value, "packet_commit_sha")

    @field_validator("packet_build_sha", mode="before")
    @classmethod
    def normalize_build_sha(cls, value: object) -> object | None:
        return _normalise_and_validate_sha(value, "packet_build_sha")

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """Ensure explicitly supplied status is not null."""
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(STATUS_REQUIRED_ERROR)
        triplet_fields = {
            "validation_target",
            "validation_target_kind",
            "validation_target_scope",
        }
        provided = triplet_fields.intersection(self.model_fields_set)
        if provided and provided != triplet_fields:
            raise ValueError(
                "validation_target, validation_target_kind, and validation_target_scope must be updated together"
            )
        # Apply the SSRF guard when the triplet is being set — PATCH is
        # the main surface for ``validation_target`` drift, so the check
        # must fire here too (not just TaskBase creation).
        if provided == triplet_fields:
            _guard_url_shaped_target(
                self.validation_target,
                self.validation_target_kind,
                "validation_target",
            )
        return self


class TaskRead(TaskBase):
    """Task payload returned from read endpoints."""

    id: UUID
    board_id: UUID | None
    created_by_user_id: UUID | None
    in_progress_at: datetime | None
    previous_in_progress_at: datetime | None = None
    rework_started_at: datetime | None = None
    rework_entry_commit_sha: str | None = None
    source_memory_id: UUID | None = None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    blocked_by_task_ids: list[UUID] = Field(default_factory=list)
    is_blocked: bool = False
    tags: list[TagRef] = Field(default_factory=list)
    custom_field_values: TaskCustomFieldValues | None = None
    # Phase V — non-terminal child tasks of this task. Populated only
    # for terminal (done/cancelled) tasks; empty list otherwise.
    # Surfaces orphans for the operator/lead so they can decide
    # whether each child still has independent work to do.
    orphan_child_task_ids: list[UUID] = Field(default_factory=list)


class TaskCommentCreate(SQLModel):
    """Payload for creating a task comment."""

    message: NonEmptyStr


class TaskCommentRead(SQLModel):
    """Task comment payload returned from read endpoints."""

    id: UUID
    message: str | None
    agent_id: UUID | None
    task_id: UUID | None
    created_at: datetime
    # Phase I: classifier flags stamped at write time. None = not
    # classified; [] = classified, no flags; [str, ...] = flagged.
    classifier_flags: list[str] | None = None
