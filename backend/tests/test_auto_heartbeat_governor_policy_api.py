# ruff: noqa: INP001

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.boards import router as boards_router
from app.api.deps import get_board_for_user_read, get_board_for_user_write
from app.db.session import get_session
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_test_app(
    session_maker: async_sessionmaker[AsyncSession],
    board_id: UUID,
) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(boards_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    async def _override_board_read(
        board_id: UUID,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        board = await Board.objects.by_id(board_id).first(session)
        assert board is not None
        return board

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_board_for_user_read] = _override_board_read
    app.dependency_overrides[get_board_for_user_write] = _override_board_read
    return app


async def _seed_board(session: AsyncSession) -> Board:
    organization_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()

    session.add(Organization(id=organization_id, name=f"org-{organization_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=organization_id,
            name="gateway",
            url="https://gateway.example.local",
            token="gw-token",
            workspace_root="/tmp",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=organization_id,
        gateway_id=gateway_id,
        name="Board",
        slug="board",
        description="desc",
    )
    session.add(board)
    await session.commit()
    return board


@pytest.mark.asyncio
async def test_get_and_patch_policy_round_trip() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as session:
        board = await _seed_board(session)

    app = _build_test_app(session_maker, board.id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get(f"/api/v1/boards/{board.id}/auto-heartbeat-governor-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["activity_trigger_type"] == "B"
        assert data["lead_cap_every"] == "1h"
        assert data["ladder"] == ["10m", "30m", "1h", "3h", "6h"]

        patch = {
            "enabled": False,
            "activity_trigger_type": "A",
            "ladder": ["15m", "45m"],
            "lead_cap_every": "2h",
        }
        resp = await client.patch(
            f"/api/v1/boards/{board.id}/auto-heartbeat-governor-policy",
            json=patch,
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["enabled"] is False
        assert updated["activity_trigger_type"] == "A"
        assert updated["ladder"] == ["15m", "45m"]
        assert updated["lead_cap_every"] == "2h"

    await engine.dispose()


@pytest.mark.asyncio
async def test_policy_validation_rejects_disabled_duration() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as session:
        board = await _seed_board(session)

    app = _build_test_app(session_maker, board.id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.patch(
            f"/api/v1/boards/{board.id}/auto-heartbeat-governor-policy",
            json={"lead_cap_every": "disabled"},
        )
        assert resp.status_code == 422

    await engine.dispose()


@pytest.mark.asyncio
async def test_policy_validation_rejects_nulls_and_unknown_fields() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as session:
        board = await _seed_board(session)

    app = _build_test_app(session_maker, board.id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        null_resp = await client.patch(
            f"/api/v1/boards/{board.id}/auto-heartbeat-governor-policy",
            json={"lead_cap_every": None},
        )
        assert null_resp.status_code == 422

        extra_resp = await client.patch(
            f"/api/v1/boards/{board.id}/auto-heartbeat-governor-policy",
            json={"run_interval_seconds": 600},
        )
        assert extra_resp.status_code == 422

    await engine.dispose()


@pytest.mark.asyncio
async def test_policy_validation_rejects_empty_ladder() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as session:
        board = await _seed_board(session)

    app = _build_test_app(session_maker, board.id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.patch(
            f"/api/v1/boards/{board.id}/auto-heartbeat-governor-policy",
            json={"ladder": []},
        )
        assert resp.status_code == 422

    await engine.dispose()
