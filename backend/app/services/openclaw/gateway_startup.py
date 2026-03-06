"""Startup-time gateway configuration overrides."""

from __future__ import annotations

import logging
from uuid import UUID

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.gateways import Gateway

logger = logging.getLogger(__name__)


async def apply_gateway_startup_overrides(session: AsyncSession) -> None:
    """Apply env-var-driven gateway field overrides on startup.

    Idempotent: only writes rows that need changing.
    """
    raw: str = settings.gateway_disable_device_pairing_ids.strip()
    if not raw:
        return

    ids: list[UUID] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            ids.append(UUID(value))
        except ValueError:
            logger.warning("gateway_startup.invalid_uuid value=%s", value)

    if not ids:
        return

    result = await session.exec(
        sa.select(Gateway.id)
        .where(Gateway.id.in_(ids))
        .where(Gateway.disable_device_pairing.is_(False)),
    )
    gateway_ids_to_update: list[UUID] = [gateway_id for (gateway_id,) in result.all()]
    if not gateway_ids_to_update:
        logger.debug("gateway_startup.disable_device_pairing.no_changes_needed")
        return

    await session.exec(
        sa.update(Gateway)
        .where(Gateway.id.in_(gateway_ids_to_update))
        .values(disable_device_pairing=True),
    )
    await session.commit()
    logger.info(
        "gateway_startup.disable_device_pairing.applied count=%d ids=%s",
        len(gateway_ids_to_update),
        [str(gateway_id) for gateway_id in gateway_ids_to_update],
    )
