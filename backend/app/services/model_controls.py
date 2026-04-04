"""Service layer for per-agent model assignment, fallback policy, and recommendation state.

Design principles:
- Admin intent (manual selections) is never silently overwritten by recommendation refresh.
- Invalid overrides are preserved in storage and surfaced via validation fields.
- Effective config is recomputed after every write; clients receive the same aggregate shape.
- Full-list replacement is used for manual fallback overrides to reduce ordering/race bugs.
- Recommendation state is stored separately from admin intent to support stale detection.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from app.core.time import utcnow

logger = logging.getLogger(__name__)
from app.models.agents import Agent
from app.models.gateway_model_profiles import GatewayModelProfileDefaults
from app.models.model_controls import (
    AgentModelFallbackEntry,
    AgentModelProfile,
    AgentModelRecommendationRun,
)
from app.schemas.model_controls import (
    AgentModelAssignmentRead,
    FallbackEntry,
    FallbackSection,
    PatchPrimaryRequest,
    PrimarySection,
    PutFallbackOverrideRequest,
    RecommendationSection,
    RegenerateRecommendationRequest,
    ValidationIssue,
    ValidationSection,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Dynamic model catalog — fetched from gateway via models.list RPC
# ---------------------------------------------------------------------------
# No static fallback: if the gateway is unreachable the catalog is empty.
# Results are cached in-memory with a short TTL to avoid hitting the gateway
# on every request.

import time as _time

from app.schemas.model_controls import CatalogEntry

_CATALOG_CACHE_TTL_SECONDS = 60
_catalog_cache: dict[str, tuple[list[CatalogEntry], float]] = {}


_ROUTING_LABELS: dict[str, str] = {
    "cc": "Anthropic",
    "cx": "Codex",
    "gh": "GitHub",
    "ag": "Agentic",
}

_TIER_HINTS: dict[str, str] = {
    "opus": "premium",
    "gpt-5.4": "premium",
    "sonnet": "balanced",
    "codex-spark": "budget",
    "codex-none": "balanced",
    "codex": "specialized",
    "mini": "budget",
    "haiku": "budget",
}

_CAPABILITY_HINTS: dict[str, str] = {
    "opus": "reasoning",
    "gpt-5.4": "reasoning",
    "sonnet": "general",
    "codex": "coding",
    "codex-spark": "coding",
    "codex-none": "coding",
    "mini": "fast",
    "haiku": "fast",
}


def _infer_tier(model_name: str) -> str:
    """Infer tier from model name patterns."""
    for hint, tier in _TIER_HINTS.items():
        if hint in model_name:
            return tier
    return "balanced"


def _infer_capability(model_name: str) -> str:
    """Infer capability class from model name patterns."""
    for hint, cap in _CAPABILITY_HINTS.items():
        if hint in model_name:
            return cap
    return "general"


def _build_display_name(model_name: str, routing: str) -> str:
    """Build a human-readable display name from model name and routing family.

    Examples:
        ("claude-opus-4-6", "cc") -> "Claude Opus 4.6 (Anthropic)"
        ("gpt-5.4", "cx") -> "GPT 5.4 (Codex)"
        ("gpt-5.4", "gh") -> "GPT 5.4 (GitHub)"
        ("gpt-5.3-codex-spark", "cx") -> "GPT 5.3 Codex Spark (Codex)"
    """
    # Convert hyphens to spaces, handle version numbers (4-6 -> 4.6)
    import re
    # Replace version-like patterns: digits-digits -> digits.digits
    name = re.sub(r"(\d+)-(\d+)$", r"\1.\2", model_name)
    name = re.sub(r"(\d+)-(\d+)-", r"\1.\2-", name)
    # Title-case the rest
    name = name.replace("-", " ").title()
    # Fix common casing: GPT not Gpt, etc.
    name = re.sub(r"\bGpt\b", "GPT", name)
    name = re.sub(r"\bClaude\b", "Claude", name)

    routing_label = _ROUTING_LABELS.get(routing)
    if routing_label:
        return f"{name} ({routing_label})"
    return name


def _infer_role_fit(model_name: str) -> list[str]:
    """Infer role fit from model name patterns."""
    if "opus" in model_name or "gpt-5.4" in model_name:
        return ["lead", "coding", "review"]
    if "sonnet" in model_name:
        return ["lead", "worker", "review"]
    if "codex" in model_name:
        return ["coding", "worker", "automation"]
    if "mini" in model_name or "haiku" in model_name:
        return ["automation", "worker"]
    return ["worker"]


def _parse_model_entry(raw: object) -> CatalogEntry | None:
    """Best-effort parse of a single model entry from gateway models.list response.

    Handles both rich dict entries and plain string model IDs.
    """
    if isinstance(raw, str):
        model_id = raw
        parts = model_id.split("/")
        provider = parts[0] if len(parts) >= 3 else "9router"
        routing = parts[1] if len(parts) >= 3 else "unknown"
        model_name = parts[-1] if parts else raw
        family = model_name.split("-")[0] if "-" in model_name else model_name

        return CatalogEntry(
            model_id=model_id,
            display_name=_build_display_name(model_name, routing),
            provider_family=provider,
            routing_family=routing,
            family=family,
            tier=_infer_tier(model_name),
            capability_class=_infer_capability(model_name),
            role_fit=_infer_role_fit(model_name),
            supports_primary=True,
            supports_fallback=True,
            status="active",
            fallback_candidates=[],
        )

    if isinstance(raw, dict):
        model_id = raw.get("model_id") or raw.get("id") or raw.get("name")
        if not model_id or not isinstance(model_id, str):
            return None

        parts = model_id.split("/")
        provider = raw.get("provider_family") or raw.get("provider") or (parts[0] if len(parts) >= 3 else "9router")
        routing = raw.get("routing_family") or raw.get("routing") or (parts[1] if len(parts) >= 3 else "unknown")
        model_name = parts[-1] if parts else model_id
        family = raw.get("family") or (model_name.split("-")[0] if "-" in model_name else model_name)

        return CatalogEntry(
            model_id=model_id,
            display_name=raw.get("display_name") or raw.get("name") or raw.get("label") or _build_display_name(model_name, str(routing)),
            provider_family=str(provider),
            routing_family=str(routing),
            family=str(family),
            tier=raw.get("tier") or _infer_tier(model_name),
            capability_class=raw.get("capability_class") or raw.get("capability") or _infer_capability(model_name),
            role_fit=raw.get("role_fit") or _infer_role_fit(model_name),
            supports_primary=raw.get("supports_primary", True),
            supports_fallback=raw.get("supports_fallback", True),
            status=raw.get("status", "active"),
            fallback_candidates=raw.get("fallback_candidates", []),
        )

    return None


async def _fetch_catalog_from_gateway(
    session: "AsyncSession",
    gateway_id: UUID | None = None,
) -> list[CatalogEntry]:
    """Fetch the model catalog from a gateway via models.list RPC.

    Returns an empty list if the gateway is unreachable or the response
    is unparseable. No static fallback.
    """
    from app.models.gateways import Gateway
    from app.services.openclaw.gateway_rpc import OpenClawGatewayError, openclaw_call
    from app.services.openclaw.gateway_resolver import gateway_client_config

    try:
        if gateway_id:
            gateway = await session.get(Gateway, gateway_id)
        else:
            # Use first available gateway
            result = await session.execute(select(Gateway).limit(1))
            gateway = result.scalars().first()

        if not gateway:
            logger.warning("catalog.fetch: no gateway available")
            return []

        config = gateway_client_config(gateway)
        raw_response = await openclaw_call("models.list", config=config)

        # Log the raw response shape on first encounter for debugging
        logger.info(
            "catalog.fetch: models.list response type=%s gateway_id=%s",
            type(raw_response).__name__, gateway.id,
        )
        logger.debug("catalog.fetch: raw response=%r", raw_response)

        # Parse response — handle list of models or dict with models key
        raw_models: list[object] = []
        if isinstance(raw_response, list):
            raw_models = raw_response
        elif isinstance(raw_response, dict):
            raw_models = (
                raw_response.get("models")
                or raw_response.get("list")
                or raw_response.get("data")
                or []
            )
            if not isinstance(raw_models, list):
                raw_models = []

        entries: list[CatalogEntry] = []
        for raw in raw_models:
            entry = _parse_model_entry(raw)
            if entry:
                entries.append(entry)

        logger.info("catalog.fetch: parsed %d models from gateway %s", len(entries), gateway.id)
        return entries

    except (OpenClawGatewayError, TimeoutError) as exc:
        logger.warning("catalog.fetch: gateway RPC failed: %s", exc)
        return []
    except Exception as exc:  # pragma: no cover
        logger.error("catalog.fetch: unexpected error: %s", exc)
        return []


async def get_model_catalog(
    session: "AsyncSession",
    *,
    gateway_id: UUID | None = None,
    role_fit: str | None = None,
    capability_class: str | None = None,
    supports_primary: bool | None = None,
    supports_fallback: bool | None = None,
) -> list[CatalogEntry]:
    """Return filtered model catalog from gateway, with in-memory caching.

    Cache is keyed by gateway_id (or "default") with a 60s TTL.
    Returns empty list if gateway is unreachable.
    """
    cache_key = str(gateway_id) if gateway_id else "default"
    now = _time.monotonic()

    # Check cache
    if cache_key in _catalog_cache:
        cached_entries, cached_at = _catalog_cache[cache_key]
        if now - cached_at < _CATALOG_CACHE_TTL_SECONDS:
            all_entries = cached_entries
        else:
            all_entries = await _fetch_catalog_from_gateway(session, gateway_id)
            # Only cache non-empty results; don't cache gateway failures
            if all_entries:
                _catalog_cache[cache_key] = (all_entries, now)
            else:
                # Serve stale cache on failure rather than empty
                all_entries = cached_entries
    else:
        all_entries = await _fetch_catalog_from_gateway(session, gateway_id)
        if all_entries:
            _catalog_cache[cache_key] = (all_entries, now)

    # Apply filters
    results: list[CatalogEntry] = []
    for entry in all_entries:
        if entry.status != "active":
            continue
        if role_fit and role_fit not in entry.role_fit:
            continue
        if capability_class and entry.capability_class != capability_class:
            continue
        if supports_primary is not None and entry.supports_primary != supports_primary:
            continue
        if supports_fallback is not None and entry.supports_fallback != supports_fallback:
            continue
        results.append(entry)
    return results


async def _get_active_model_ids(session: "AsyncSession", gateway_id: UUID | None = None) -> set[str]:
    """Return the set of active model IDs from the cached gateway catalog."""
    entries = await get_model_catalog(session, gateway_id=gateway_id)
    return {e.model_id for e in entries if e.status == "active"}


async def _is_valid_model_async(session: "AsyncSession", model_id: str, gateway_id: UUID | None = None) -> bool:
    """Check if a model_id is in the active gateway catalog."""
    active = await _get_active_model_ids(session, gateway_id=gateway_id)
    return model_id in active


def _is_valid_model(model_id: str) -> bool:
    """Synchronous validation against the cached catalog.

    Uses the cache directly without a gateway fetch. Returns True if the
    model_id is found in any cached catalog, False otherwise.
    """
    for entries, _ts in _catalog_cache.values():
        for e in entries:
            if e.model_id == model_id and e.status == "active":
                return True
    return False


# ---------------------------------------------------------------------------
# Effective-config assembly helpers
# ---------------------------------------------------------------------------


def _assemble_effective_fallback(
    generated: list[AgentModelFallbackEntry],
    manual: list[AgentModelFallbackEntry],
    override_mode: str,
    effective_primary: str | None,
) -> tuple[list[FallbackEntry], str, str, bool, str | None]:
    """Assemble effective fallback list from generated + manual entries.

    Returns:
        (effective_entries, source_label, status_label, has_effective_fallback,
         no_valid_fallback_reason)
    """

    def _to_read(e: AgentModelFallbackEntry) -> FallbackEntry:
        return FallbackEntry(
            model_id=e.model_id,
            position=e.position,
            trigger_type=e.trigger_type,
            source=e.source,
            enabled=e.enabled,
            constraints=e.constraints,
        )

    gen_entries = [_to_read(e) for e in sorted(generated, key=lambda x: x.position) if e.enabled]
    man_entries = [_to_read(e) for e in sorted(manual, key=lambda x: x.position) if e.enabled]

    if override_mode == "replace":
        raw = man_entries
        source = "manual_only"
    elif override_mode == "append":
        raw = gen_entries + man_entries
        source = "generated_plus_manual" if (gen_entries and man_entries) else (
            "generated_only" if gen_entries else "manual_only"
        )
    else:  # none
        raw = gen_entries
        source = "generated_only"

    # Deduplicate: first occurrence wins. Also remove entries matching effective primary.
    seen: set[str] = set()
    if effective_primary:
        seen.add(effective_primary)
    effective: list[FallbackEntry] = []
    for entry in raw:
        if not _is_valid_model(entry.model_id):
            continue
        if entry.model_id in seen:
            continue
        seen.add(entry.model_id)
        effective.append(entry)

    # Rebuild positions
    for i, e in enumerate(effective):
        e = e.model_copy(update={"position": i})
        effective[i] = e

    has_effective = len(effective) > 0

    # Determine status
    if not has_effective:
        if not raw:
            status = "empty_allowed" if override_mode == "none" else "empty_invalid"
        else:
            status = "empty_invalid"
        reason = "No valid fallback entries remain after validation and deduplication."
    elif override_mode == "none":
        status = "generated_only"
        reason = None
    elif override_mode == "replace":
        status = "manual_only"
        reason = None
    else:
        status = "merged"
        reason = None

    return effective, source, status, has_effective, reason


def _compute_validation(
    profile: AgentModelProfile,
    effective_primary: str | None,
    has_effective_fallback: bool,
    fallback_status: str,
) -> ValidationSection:
    issues: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    # Primary validity
    if profile.primary_selection_mode == "manual" and profile.primary_model_id:
        if not _is_valid_model(profile.primary_model_id):
            issues.append(ValidationIssue(
                code="primary_model_invalid",
                severity="error",
                scope="primary",
                message=(
                    f"Manually selected primary model '{profile.primary_model_id}' "
                    "is not in the active catalog. Please update your selection."
                ),
            ))

    # Recommended model references stale/phantom ID
    if (
        profile.recommended_primary_model_id
        and not _is_valid_model(profile.recommended_primary_model_id)
    ):
        issues.append(ValidationIssue(
            code="recommended_model_invalid",
            severity="error",
            scope="recommendation",
            message=(
                f"Recommended model '{profile.recommended_primary_model_id}' "
                "is not in the active catalog. Regenerate the recommendation."
            ),
        ))

    # No effective primary
    if effective_primary is None:
        issues.append(ValidationIssue(
            code="no_effective_primary",
            severity="error",
            scope="primary",
            message="No effective primary model is available. Assign a model or wait for recommendation.",
        ))

    # No effective fallback
    if not has_effective_fallback and fallback_status == "empty_invalid":
        issues.append(ValidationIssue(
            code="no_effective_fallback",
            severity="error",
            scope="fallback",
            message="No valid fallback remains after validation and deduplication.",
        ))

    # Stale recommendation warning
    if profile.recommendation_status == "stale":
        warnings.append(ValidationIssue(
            code="recommendation_stale",
            severity="warning",
            scope="recommendation",
            message="The model recommendation is stale. Consider regenerating to get an updated suggestion.",
        ))

    # Determine config_status
    if issues:
        config_status = "invalid"
    elif warnings or profile.recommendation_status in ("stale", "error"):
        config_status = "stale" if profile.recommendation_status == "stale" else "degraded"
    elif effective_primary is None:
        config_status = "degraded"
    elif profile.config_status == "pending":
        config_status = "pending"
    else:
        config_status = "valid"

    return ValidationSection(
        config_status=config_status,
        blocking_issues=issues,
        warnings=warnings,
    )


def _resolve_effective_primary(profile: AgentModelProfile) -> str | None:
    if profile.primary_selection_mode == "manual" and profile.primary_model_id:
        if _is_valid_model(profile.primary_model_id):
            return profile.primary_model_id
    # Only use recommendation if it references a valid catalog model
    rec = profile.recommended_primary_model_id
    if rec and _is_valid_model(rec):
        return rec
    return None


def _primary_source(profile: AgentModelProfile, effective: str | None) -> str:
    if profile.primary_selection_mode == "manual" and profile.primary_model_id:
        return "manual"
    if effective == profile.recommended_primary_model_id:
        return "recommended"
    return "none"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AgentModelAssignmentService:
    """Handles reads and writes for per-agent model assignment."""

    def __init__(self, session: "AsyncSession") -> None:
        self._session = session

    async def _exec_scalars(self, stmt: object):
        """Execute a mapped select and return ORM scalar rows."""
        result = await self._session.execute(stmt)  # type: ignore[arg-type]
        return result.scalars()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _get_or_create_profile(self, agent_id: UUID) -> AgentModelProfile:
        """Return the existing profile for an agent or bootstrap a new pending one.

        Raises HTTPException 404 if the agent does not exist (prevents phantom records).
        """
        stmt = select(AgentModelProfile).where(AgentModelProfile.agent_id == agent_id)
        result = await self._exec_scalars(stmt)
        profile = result.one_or_none()
        if profile is None:
            # Verify the agent actually exists before creating a profile
            from fastapi import HTTPException, status as http_status

            agent_check = await self._session.execute(
                select(Agent.id).where(Agent.id == agent_id)
            )
            if agent_check.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail="Agent not found",
                )
            profile = AgentModelProfile(
                agent_id=agent_id,
                primary_selection_mode="auto",
                fallback_override_mode="none",
                recommendation_status="pending",
                config_status="pending",
            )
            self._session.add(profile)
            await self._session.flush()
        return profile

    async def _get_profile(self, agent_id: UUID) -> AgentModelProfile:
        stmt = select(AgentModelProfile).where(AgentModelProfile.agent_id == agent_id)
        result = await self._exec_scalars(stmt)
        profile = result.one_or_none()
        if profile is None:
            raise NoResultFound(f"No model profile for agent {agent_id}")
        return profile

    async def _get_gateway_profile_defaults(
        self, agent_id: UUID
    ) -> GatewayModelProfileDefaults | None:
        """Look up gateway model profile defaults for an agent's gateway.

        Returns None if the agent has no gateway or the gateway has no
        profile defaults configured.
        """
        # Get agent's gateway_id
        agent_stmt = select(Agent.gateway_id).where(Agent.id == agent_id)
        agent_result = await self._session.execute(agent_stmt)
        gateway_id = agent_result.scalar_one_or_none()
        if gateway_id is None:
            return None

        # Get gateway profile defaults
        defaults_stmt = select(GatewayModelProfileDefaults).where(
            GatewayModelProfileDefaults.gateway_id == gateway_id
        )
        defaults_result = await self._session.execute(defaults_stmt)
        return defaults_result.scalars().first()

    async def _get_fallback_entries(
        self, profile_id: UUID
    ) -> tuple[list[AgentModelFallbackEntry], list[AgentModelFallbackEntry]]:
        stmt = select(AgentModelFallbackEntry).where(
            AgentModelFallbackEntry.agent_model_profile_id == profile_id
        )
        result = await self._exec_scalars(stmt)
        all_entries = list(result.all())
        generated = [e for e in all_entries if e.source == "generated"]
        manual = [e for e in all_entries if e.source == "manual"]
        return generated, manual

    def _build_aggregate(
        self,
        profile: AgentModelProfile,
        generated_entries: list[AgentModelFallbackEntry],
        manual_entries: list[AgentModelFallbackEntry],
    ) -> AgentModelAssignmentRead:
        effective_primary = _resolve_effective_primary(profile)

        # Assemble fallback
        (
            effective_fallback,
            fallback_source,
            fallback_status,
            has_effective_fallback,
            no_valid_fallback_reason,
        ) = _assemble_effective_fallback(
            generated_entries,
            manual_entries,
            profile.fallback_override_mode,
            effective_primary,
        )

        # Validation
        validation = _compute_validation(
            profile,
            effective_primary,
            has_effective_fallback,
            fallback_status,
        )

        # Primary section
        primary = PrimarySection(
            manual_model_id=profile.primary_model_id,
            recommended_model_id=profile.recommended_primary_model_id,
            effective_model_id=effective_primary,
            source=_primary_source(profile, effective_primary),
            selection_mode=profile.primary_selection_mode,
            is_valid=not any(
                i.scope == "primary" and i.severity == "error"
                for i in validation.blocking_issues
            ),
            recommendation_changed=False,  # Phase 2: derive from run history
        )

        # Fallback section
        gen_read = [
            FallbackEntry(
                model_id=e.model_id,
                position=e.position,
                trigger_type=e.trigger_type,
                source=e.source,
                enabled=e.enabled,
                constraints=e.constraints,
            )
            for e in sorted(generated_entries, key=lambda x: x.position)
        ]
        man_read = [
            FallbackEntry(
                model_id=e.model_id,
                position=e.position,
                trigger_type=e.trigger_type,
                source=e.source,
                enabled=e.enabled,
                constraints=e.constraints,
            )
            for e in sorted(manual_entries, key=lambda x: x.position)
        ]
        fallback = FallbackSection(
            override_mode=profile.fallback_override_mode,
            generated_entries=gen_read,
            manual_entries=man_read,
            effective_entries=effective_fallback,
            source=fallback_source,
            status=fallback_status,
            has_effective_fallback=has_effective_fallback,
            no_valid_fallback_reason=no_valid_fallback_reason,
        )

        # Recommendation section
        recommendation = RecommendationSection(
            status=profile.recommendation_status,
            generated_at=profile.recommendation_generated_at,
            version=profile.recommendation_version,
            explanation=profile.recommendation_explanation or {},
        )

        return AgentModelAssignmentRead(
            agent_id=profile.agent_id,
            board_id=profile.board_id,
            role_key=profile.role_key,
            primary=primary,
            fallback=fallback,
            recommendation=recommendation,
            validation=validation,
            updated_at=profile.updated_at,
        )

    async def _update_effective_and_validation(self, profile: AgentModelProfile) -> None:
        """Recompute and persist effective_primary_model_id and config_status."""
        generated_entries, manual_entries = await self._get_fallback_entries(profile.id)
        effective_primary = _resolve_effective_primary(profile)
        (_, _, fallback_status, has_effective_fallback, _) = _assemble_effective_fallback(
            generated_entries, manual_entries, profile.fallback_override_mode, effective_primary
        )
        validation = _compute_validation(
            profile, effective_primary, has_effective_fallback, fallback_status
        )
        profile.effective_primary_model_id = effective_primary
        profile.config_status = validation.config_status
        profile.effective_config_updated_at = utcnow()
        profile.updated_at = utcnow()
        self._session.add(profile)

    # -----------------------------------------------------------------------
    # Runtime sync — gateway RPC bridge
    # -----------------------------------------------------------------------

    async def _sync_effective_to_runtime(
        self, agent_id: UUID, effective_model_id: str | None
    ) -> "RuntimeSyncResult | None":
        """Sync effective model to gateway runtime via config.patch RPC.

        Uses the same config.patch mechanism as provisioning heartbeat sync.
        MC DB is the source of truth; this is best-effort.
        """
        from app.schemas.model_controls import RuntimeSyncResult

        if not effective_model_id:
            return RuntimeSyncResult(
                status="skipped",
                error="No effective model to sync",
            )

        # Load the agent to resolve its board and gateway
        agent = await self._session.get(Agent, agent_id)
        if not agent or not agent.board_id:
            return RuntimeSyncResult(
                status="skipped",
                error="Agent has no board; cannot resolve gateway",
            )

        from app.models.boards import Board
        board = await self._session.get(Board, agent.board_id)
        if not board or not board.gateway_id:
            return RuntimeSyncResult(
                status="skipped",
                error="Board has no gateway configured",
            )

        try:
            from app.services.openclaw.gateway_dispatch import GatewayDispatchService
            from app.services.openclaw.gateway_rpc import (
                OpenClawGatewayError,
                openclaw_call,
            )
            from app.services.openclaw.internal.agent_key import agent_key
            from app.services.openclaw.provisioning import (
                _gateway_config_agent_list,
            )

            dispatch = GatewayDispatchService(self._session)
            _gw, config = await dispatch.require_gateway_config_for_board(board)

            # Fetch current agent list from gateway
            base_hash, agent_list, _config_data = await _gateway_config_agent_list(config)

            # Find agent entry and patch model.primary
            agent_dir = agent_key(agent)
            found = False
            for entry in agent_list:
                if entry.get("id") == agent_dir:
                    model = entry.get("model", {})
                    if isinstance(model, str):
                        model = {"primary": model}
                    elif not isinstance(model, dict):
                        model = {}
                    model["primary"] = effective_model_id
                    entry["model"] = model
                    found = True
                    break

            if not found:
                return RuntimeSyncResult(
                    status="skipped",
                    error=f"Agent '{agent_dir}' not found in gateway config agents.list",
                )

            # Send config.patch RPC
            patch = {"agents": {"list": agent_list}}
            params: dict[str, str] = {"raw": json.dumps(patch)}
            if base_hash:
                params["baseHash"] = base_hash
            await openclaw_call("config.patch", params, config=config)

            now = utcnow()
            logger.info(
                "Runtime sync via RPC: agent=%s model=%s",
                agent_dir, effective_model_id,
            )
            return RuntimeSyncResult(
                status="synced",
                synced_at=now,
                next_effective="next_session_start",
            )

        except (OpenClawGatewayError, TimeoutError) as exc:
            logger.warning("Runtime sync RPC failed: %s", exc)
            return RuntimeSyncResult(
                status="failed",
                error=f"Gateway RPC error: {exc}",
            )
        except Exception as exc:  # pragma: no cover — defensive guard
            logger.error("Runtime sync unexpected error: %s", exc)
            return RuntimeSyncResult(
                status="failed",
                error=f"Unexpected error: {exc}",
            )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def get_assignment(self, agent_id: UUID) -> AgentModelAssignmentRead:
        """Return aggregate model assignment for an agent, bootstrapping profile if absent."""
        profile = await self._get_or_create_profile(agent_id)
        await self._session.commit()
        generated_entries, manual_entries = await self._get_fallback_entries(profile.id)
        return self._build_aggregate(profile, generated_entries, manual_entries)

    async def patch_primary(
        self,
        agent_id: UUID,
        payload: PatchPrimaryRequest,
    ) -> AgentModelAssignmentRead:
        """Set or clear manual primary model selection.

        - Does not overwrite recommendation state.
        - Recomputes effective config and validation after mutation.
        """
        profile = await self._get_or_create_profile(agent_id)

        if payload.selection_mode == "manual":
            if not payload.model_id:
                raise ValueError("model_id is required when selection_mode=manual")
            if not await _is_valid_model_async(self._session, payload.model_id):
                raise ValueError(f"Invalid model_id: {payload.model_id}")
            profile.primary_model_id = payload.model_id
            profile.primary_selection_mode = "manual"
        else:  # auto
            profile.primary_model_id = None
            profile.primary_selection_mode = "auto"

        await self._update_effective_and_validation(profile)
        await self._session.commit()

        # Sync effective model to OpenClaw gateway runtime (best-effort)
        sync_result = await self._sync_effective_to_runtime(
            agent_id, profile.effective_primary_model_id
        )

        generated_entries, manual_entries = await self._get_fallback_entries(profile.id)
        result = self._build_aggregate(profile, generated_entries, manual_entries)
        result.runtime_sync = sync_result
        return result

    async def put_fallback_override(
        self,
        agent_id: UUID,
        payload: PutFallbackOverrideRequest,
    ) -> AgentModelAssignmentRead:
        """Full-list replacement for manual fallback entries.

        Replaces all existing manual fallback rows atomically.
        Does not touch generated entries.
        """
        profile = await self._get_or_create_profile(agent_id)

        # Delete existing manual entries
        stmt = select(AgentModelFallbackEntry).where(
            AgentModelFallbackEntry.agent_model_profile_id == profile.id,
            AgentModelFallbackEntry.source == "manual",
        )
        result = await self._exec_scalars(stmt)
        for entry in result.all():
            await self._session.delete(entry)

        # Insert new manual entries
        new_entries: list[AgentModelFallbackEntry] = []
        for item in payload.entries:
            entry = AgentModelFallbackEntry(
                agent_model_profile_id=profile.id,
                source="manual",
                position=item.position,
                model_id=item.model_id,
                trigger_type=item.trigger_type,
                constraints=item.constraints,
                enabled=item.enabled,
            )
            self._session.add(entry)
            new_entries.append(entry)

        # Update override mode
        profile.fallback_override_mode = payload.override_mode
        profile.fallback_override_updated_at = utcnow()

        await self._update_effective_and_validation(profile)
        await self._session.commit()

        # Refresh to pick up persisted manual entries
        await self._session.refresh(profile)
        generated_entries, manual_entries = await self._get_fallback_entries(profile.id)
        return self._build_aggregate(profile, generated_entries, manual_entries)

    async def regenerate_recommendation(
        self,
        agent_id: UUID,
        payload: RegenerateRecommendationRequest,
    ) -> AgentModelAssignmentRead:
        """Recompute recommended primary and generated fallback policy.

        - Does not overwrite valid manual overrides.
        - Updates recommendation_status and generated fallback entries.
        - Appends a recommendation run history record.
        """
        profile = await self._get_or_create_profile(agent_id)

        # --- Role-fit → profile mapping policy ---
        # Maps agent role to preferred gateway profile slot, with fallback chain:
        #   1. Preferred profile slot (coder for coding, budget for automation)
        #   2. General profile slot (baseline)
        #   3. Hardcoded catalog-aware defaults (last resort)
        #
        # Only explicit user-selected values and "default" sentinel are used.
        # No guessing — if a profile slot is unset (null), it is skipped.

        ROLE_TO_PROFILE_SLOT: dict[str, str] = {
            "coding": "coder",
            "automation": "budget",
            # All others (lead, worker, review) map to general
        }
        # Defaults use only models present in gateway config.
        HARDCODED_DEFAULTS: dict[str, str] = {
            "lead": "9router/cc/claude-opus-4-6",
            "coding": "9router/cx/gpt-5.4",
            "worker": "9router/cc/claude-sonnet-4-6",
            "automation": "9router/gh/gpt-5-mini",
            "review": "9router/cc/claude-opus-4-6",
        }
        HARDCODED_FALLBACKS: dict[str, list[str]] = {
            "lead": ["9router/cx/gpt-5.4", "9router/cc/claude-sonnet-4-6"],
            "coding": ["9router/cx/gpt-5.3-codex", "9router/cc/claude-sonnet-4-6"],
            "worker": ["9router/cx/gpt-5.3-codex-spark", "9router/gh/gpt-5-mini"],
            "automation": ["9router/cx/gpt-5.3-codex-spark", "9router/cc/claude-sonnet-4-6"],
            "review": ["9router/cc/claude-sonnet-4-6", "9router/cx/gpt-5.4"],
        }

        role = profile.role_key if profile.role_key in HARDCODED_DEFAULTS else "worker"
        preferred_slot = ROLE_TO_PROFILE_SLOT.get(role, "general")

        # Look up gateway profile defaults for this agent
        gateway_defaults = await self._get_gateway_profile_defaults(agent_id)

        # Resolve recommendation through profile precedence chain
        recommended_primary: str | None = None
        recommendation_source: str = "hardcoded_default"
        explanation_reasons: list[dict] = []

        if gateway_defaults is not None:
            # Try preferred profile slot first
            slot_model_id = getattr(gateway_defaults, f"{preferred_slot}_model_id", None)
            if slot_model_id is not None and slot_model_id != "default":
                if _is_valid_model(slot_model_id):
                    recommended_primary = slot_model_id
                    recommendation_source = f"gateway_profile_{preferred_slot}"
                    explanation_reasons.append({
                        "code": "profile_match",
                        "label": f"Selected from gateway '{preferred_slot}' profile",
                        "weight": 1.0,
                        "profile_slot": preferred_slot,
                        "model_id": slot_model_id,
                    })
            elif slot_model_id == "default":
                # "default" sentinel — use hardcoded default for this role
                recommended_primary = HARDCODED_DEFAULTS[role]
                recommendation_source = f"gateway_profile_{preferred_slot}_default_sentinel"
                explanation_reasons.append({
                    "code": "default_sentinel",
                    "label": f"Gateway '{preferred_slot}' profile set to 'default', using role-based default",
                    "weight": 1.0,
                    "profile_slot": preferred_slot,
                })

            # Fallback to general profile if preferred slot didn't resolve
            if recommended_primary is None and preferred_slot != "general":
                general_model_id = gateway_defaults.general_model_id
                if general_model_id is not None and general_model_id != "default":
                    if _is_valid_model(general_model_id):
                        recommended_primary = general_model_id
                        recommendation_source = "gateway_profile_general_fallback"
                        explanation_reasons.append({
                            "code": "fallback_to_general",
                            "label": f"'{preferred_slot}' profile unset, fell back to 'general' profile",
                            "weight": 0.8,
                            "profile_slot": "general",
                            "model_id": general_model_id,
                        })
                elif general_model_id == "default":
                    recommended_primary = HARDCODED_DEFAULTS[role]
                    recommendation_source = "gateway_profile_general_default_sentinel"
                    explanation_reasons.append({
                        "code": "general_default_sentinel",
                        "label": "General profile set to 'default', using role-based default",
                        "weight": 0.8,
                    })

            # Fallback: general profile for roles that map directly to general
            if recommended_primary is None and preferred_slot == "general":
                general_model_id = gateway_defaults.general_model_id
                if general_model_id is not None and general_model_id != "default":
                    if _is_valid_model(general_model_id):
                        recommended_primary = general_model_id
                        recommendation_source = "gateway_profile_general"
                        explanation_reasons.append({
                            "code": "profile_match",
                            "label": "Selected from gateway 'general' profile",
                            "weight": 1.0,
                            "profile_slot": "general",
                            "model_id": general_model_id,
                        })
                elif general_model_id == "default":
                    recommended_primary = HARDCODED_DEFAULTS[role]
                    recommendation_source = "gateway_profile_general_default_sentinel"
                    explanation_reasons.append({
                        "code": "default_sentinel",
                        "label": "General profile set to 'default', using role-based default",
                        "weight": 1.0,
                    })

        # Last resort: hardcoded catalog-aware defaults
        if recommended_primary is None:
            recommended_primary = HARDCODED_DEFAULTS[role]
            recommendation_source = "hardcoded_default"
            explanation_reasons.append({
                "code": "role_default",
                "label": f"No gateway profile configured, using hardcoded default for role '{role}'",
                "weight": 0.5,
            })

        # Build fallback list from catalog-aware defaults
        # (Future: derive from gateway profiles + catalog fallback_candidates)
        recommended_fallbacks = HARDCODED_FALLBACKS.get(role, HARDCODED_FALLBACKS["worker"])

        now = utcnow()
        version = f"profile-v1/catalog-{now.date()}"

        # Update profile
        profile.recommended_primary_model_id = recommended_primary
        profile.recommendation_status = "fresh"
        profile.recommendation_generated_at = now
        profile.recommendation_version = version
        # Build explanation summary — look up display name from cache
        cat_entry = None
        for _cached_entries, _ts in _catalog_cache.values():
            for _ce in _cached_entries:
                if _ce.model_id == recommended_primary:
                    cat_entry = _ce
                    break
            if cat_entry:
                break
        model_display = cat_entry.display_name if cat_entry else recommended_primary
        summary_parts = [
            f"Recommended '{model_display}' for role '{role}'",
            f"via {recommendation_source.replace('_', ' ')}.",
        ]
        if preferred_slot != "general" and recommendation_source.startswith("gateway_profile_general"):
            summary_parts.append(
                f"'{preferred_slot}' profile was unset, fell back to 'general'."
            )

        profile.recommendation_explanation = {
            "summary": " ".join(summary_parts),
            "reasons": explanation_reasons,
            "tradeoffs": [],
            "inputs": {
                "role_key": role,
                "preferred_profile_slot": preferred_slot,
                "recommendation_source": recommendation_source,
                "reason": payload.reason,
                "gateway_profiles_configured": gateway_defaults is not None,
            },
        }

        # Replace generated fallback entries
        stmt = select(AgentModelFallbackEntry).where(
            AgentModelFallbackEntry.agent_model_profile_id == profile.id,
            AgentModelFallbackEntry.source == "generated",
        )
        result = await self._exec_scalars(stmt)
        for entry in result.all():
            await self._session.delete(entry)
        await self._session.flush()

        for i, model_id in enumerate(recommended_fallbacks):
            entry = AgentModelFallbackEntry(
                agent_model_profile_id=profile.id,
                source="generated",
                position=i,
                model_id=model_id,
                trigger_type="unavailable",
                enabled=True,
                generation_version=version,
            )
            self._session.add(entry)

        # Append history record
        run = AgentModelRecommendationRun(
            agent_id=agent_id,
            board_id=profile.board_id,
            role_key=role,
            catalog_version="seed-v1",
            policy_version="profile-v1",
            status="success",
            recommended_primary_model_id=recommended_primary,
            fallback_plan=[
                {"model_id": m, "position": i} for i, m in enumerate(recommended_fallbacks)
            ],
            explanation=profile.recommendation_explanation,
            signals={"role_key": role, "reason": payload.reason},
            generated_at=now,
        )
        self._session.add(run)

        await self._update_effective_and_validation(profile)
        await self._session.commit()

        # Sync effective model to OpenClaw gateway runtime (best-effort)
        sync_result = await self._sync_effective_to_runtime(
            agent_id, profile.effective_primary_model_id
        )

        generated_entries, manual_entries = await self._get_fallback_entries(profile.id)
        result = self._build_aggregate(profile, generated_entries, manual_entries)
        result.runtime_sync = sync_result
        return result
