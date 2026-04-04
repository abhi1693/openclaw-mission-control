"""Service for gateway-level model profile defaults (General/Coder/Budget)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import select

from app.core.time import utcnow
from app.models.gateway_model_profiles import GatewayModelProfileDefaults
from app.schemas.gateway_model_profiles import (
    GatewayModelProfileDefaultsRead,
    PatchGatewayModelProfileDefaultsRequest,
    ProfileSlotRead,
)
from app.services.model_controls import _catalog_cache, _is_valid_model

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

# Sentinel value for "use runtime default"
DEFAULT_SENTINEL = "default"


def _validate_model_id(model_id: str | None, field_name: str) -> None:
    """Validate a model_id value.

    Accepts:
    - None (clear/unset)
    - "default" sentinel
    - A valid catalog model_id
    """
    if model_id is None:
        return
    if model_id == DEFAULT_SENTINEL:
        return
    if not _is_valid_model(model_id):
        raise ValueError(
            f"Invalid {field_name}: '{model_id}' is not a valid catalog model "
            f"or the 'default' sentinel."
        )


def _resolve_slot(
    model_id: str | None,
    general_model_id: str | None,
    is_general: bool = False,
) -> ProfileSlotRead:
    """Resolve a profile slot to its read shape with fallback logic."""
    if model_id is None:
        if is_general:
            return ProfileSlotRead(
                model_id=None,
                source="unset",
                display_name=None,
                effective_model_id=None,
            )
        # Coder/budget fall back to general when unset
        if general_model_id is not None and general_model_id != DEFAULT_SENTINEL:
            return ProfileSlotRead(
                model_id=None,
                source="fallback_to_general",
                display_name=None,
                effective_model_id=general_model_id,
            )
        return ProfileSlotRead(
            model_id=None,
            source="fallback_to_general",
            display_name=None,
            effective_model_id=general_model_id,  # may be "default" or None
        )

    if model_id == DEFAULT_SENTINEL:
        return ProfileSlotRead(
            model_id=DEFAULT_SENTINEL,
            source="default_sentinel",
            display_name=None,
            effective_model_id=DEFAULT_SENTINEL,
        )

    # Concrete catalog model_id — look up display name from cache
    display_name = model_id
    for _entries, _ts in _catalog_cache.values():
        for _ce in _entries:
            if _ce.model_id == model_id:
                display_name = _ce.display_name
                break
    return ProfileSlotRead(
        model_id=model_id,
        source="explicit",
        display_name=display_name,
        effective_model_id=model_id,
    )


def _build_read(
    gateway_id: UUID,
    record: GatewayModelProfileDefaults | None,
) -> GatewayModelProfileDefaultsRead:
    """Build the aggregate read shape from a DB record (or empty defaults)."""
    if record is None:
        return GatewayModelProfileDefaultsRead(
            gateway_id=gateway_id,
            general=ProfileSlotRead(source="unset"),
            coder=ProfileSlotRead(source="unset"),
            budget=ProfileSlotRead(source="unset"),
        )

    general = _resolve_slot(record.general_model_id, record.general_model_id, is_general=True)
    coder = _resolve_slot(record.coder_model_id, record.general_model_id)
    budget = _resolve_slot(record.budget_model_id, record.general_model_id)

    return GatewayModelProfileDefaultsRead(
        gateway_id=gateway_id,
        general=general,
        coder=coder,
        budget=budget,
        updated_at=record.updated_at,
        created_at=record.created_at,
    )


class GatewayModelProfileService:
    """Service for reading/writing gateway model profile defaults."""

    def __init__(self, session: "AsyncSession") -> None:
        self._session = session

    async def _get_record(
        self, gateway_id: UUID
    ) -> GatewayModelProfileDefaults | None:
        stmt = select(GatewayModelProfileDefaults).where(
            GatewayModelProfileDefaults.gateway_id == gateway_id
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_defaults(
        self, gateway_id: UUID
    ) -> GatewayModelProfileDefaultsRead:
        """Get current profile defaults for a gateway.

        Returns empty/unset defaults if no record exists yet (no bootstrap).
        """
        record = await self._get_record(gateway_id)
        return _build_read(gateway_id, record)

    async def patch_defaults(
        self,
        gateway_id: UUID,
        payload: PatchGatewayModelProfileDefaultsRequest,
    ) -> GatewayModelProfileDefaultsRead:
        """Update profile defaults for a gateway.

        Creates the record if it doesn't exist. Validates model IDs
        against the active catalog.

        Only fields that are actually provided in the payload are updated.
        Explicit nulls will clear fields; omitted fields are left unchanged.
        """
        # Determine which fields were actually provided in the request.
        # __pydantic_fields_set__ is available in both Pydantic v1 and v2.
        fields_set = getattr(payload, "__pydantic_fields_set__", set())

        record = await self._get_record(gateway_id)

        # If no fields were provided and no record exists yet, there's nothing to do.
        if not fields_set and record is None:
            return _build_read(gateway_id, record)

        # Create a new record if needed and at least one field is being set.
        if record is None:
            record = GatewayModelProfileDefaults(gateway_id=gateway_id)
            self._session.add(record)

        updated = False

        # Validate and apply only the fields that were explicitly provided.
        if "general_model_id" in fields_set:
            _validate_model_id(payload.general_model_id, "general_model_id")
            record.general_model_id = payload.general_model_id
            updated = True

        if "coder_model_id" in fields_set:
            _validate_model_id(payload.coder_model_id, "coder_model_id")
            record.coder_model_id = payload.coder_model_id
            updated = True

        if "budget_model_id" in fields_set:
            _validate_model_id(payload.budget_model_id, "budget_model_id")
            record.budget_model_id = payload.budget_model_id
            updated = True

        # If nothing was actually updated (e.g. empty payload), return current state.
        if not updated:
            return _build_read(gateway_id, record)

        record.updated_at = utcnow()
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)

        return _build_read(gateway_id, record)
