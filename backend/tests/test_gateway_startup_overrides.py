from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.services.openclaw.gateway_startup import apply_gateway_startup_overrides


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def _seed_gateway(
    session: AsyncSession,
    *,
    gateway_id: UUID | None = None,
    disable_device_pairing: bool,
) -> Gateway:
    organization_id = uuid4()
    gateway = Gateway(
        id=gateway_id or uuid4(),
        organization_id=organization_id,
        name=f"gateway-{organization_id}",
        url="https://gateway.local",
        disable_device_pairing=disable_device_pairing,
        workspace_root="/tmp/workspace",
    )
    session.add(Organization(id=organization_id, name=f"org-{organization_id}"))
    session.add(gateway)
    await session.commit()
    return gateway


@pytest.mark.asyncio
async def test_sets_disable_device_pairing_for_listed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            gateway = await _seed_gateway(session, disable_device_pairing=False)
            monkeypatch.setattr(
                settings,
                "gateway_disable_device_pairing_ids",
                str(gateway.id),
            )

            await apply_gateway_startup_overrides(session)
            await session.refresh(gateway)

            assert gateway.disable_device_pairing is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_skips_already_disabled_gateways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            gateway = await _seed_gateway(session, disable_device_pairing=True)
            original_updated_at: datetime = gateway.updated_at
            monkeypatch.setattr(
                settings,
                "gateway_disable_device_pairing_ids",
                str(gateway.id),
            )

            await apply_gateway_startup_overrides(session)
            await session.refresh(gateway)

            assert gateway.disable_device_pairing is True
            assert gateway.updated_at == original_updated_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ignores_unlisted_gateways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            listed_gateway = await _seed_gateway(session, disable_device_pairing=False)
            unlisted_gateway = await _seed_gateway(session, disable_device_pairing=False)
            monkeypatch.setattr(
                settings,
                "gateway_disable_device_pairing_ids",
                str(listed_gateway.id),
            )

            await apply_gateway_startup_overrides(session)
            await session.refresh(listed_gateway)
            await session.refresh(unlisted_gateway)

            assert listed_gateway.disable_device_pairing is True
            assert unlisted_gateway.disable_device_pairing is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_env_var_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            gateway = await _seed_gateway(session, disable_device_pairing=False)
            monkeypatch.setattr(settings, "gateway_disable_device_pairing_ids", "")

            await apply_gateway_startup_overrides(session)
            await session.refresh(gateway)

            assert gateway.disable_device_pairing is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_uuid_is_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            gateway = await _seed_gateway(session, disable_device_pairing=False)
            monkeypatch.setattr(
                settings,
                "gateway_disable_device_pairing_ids",
                f"not-a-uuid,{gateway.id}",
            )
            caplog.set_level("WARNING")

            await apply_gateway_startup_overrides(session)
            await session.refresh(gateway)

            assert gateway.disable_device_pairing is True
            assert "gateway_startup.invalid_uuid value=not-a-uuid" in caplog.text
    finally:
        await engine.dispose()
