# ruff: noqa: INP001
"""Authorization, phantom-record, and enum-validation tests for model controls.

Covers:
  - IDOR: user/agent authorization on model-controls endpoints
  - IDOR: user/agent authorization on gateway-model-profiles endpoints
  - Phantom record prevention: 404 for non-existent agent_id
  - Enum validation: 422 for invalid selection_mode, override_mode, trigger_type
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import ActorContext, require_user_or_agent
from app.api.model_controls import router as model_controls_router
from app.api.gateway_model_profiles import router as gateway_model_profiles_router
from app.db.session import get_session
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.model_controls import AgentModelProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_app(
    session_maker: async_sessionmaker[AsyncSession],
    actor: ActorContext,
) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(model_controls_router)
    api_v1.include_router(gateway_model_profiles_router)
    app.include_router(api_v1)

    async def _override_session():
        async with session_maker() as session:
            yield session

    async def _override_actor():
        return actor

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[require_user_or_agent] = _override_actor
    return app


async def _seed_org_board_agent_gateway(session: AsyncSession) -> dict[str, UUID]:
    """Create a minimal org → gateway → board → agent graph and return their IDs."""
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    agent_id = uuid4()

    org = Organization(id=org_id, name="Test Org")
    session.add(org)

    gw = Gateway(
        id=gateway_id,
        organization_id=org_id,
        name="Test GW",
        url="ws://localhost:9999",
        workspace_root="/tmp/test",
    )
    session.add(gw)

    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="Test Board",
        slug=f"test-board-{board_id.hex[:8]}",
    )
    session.add(board)

    agent = Agent(
        id=agent_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Test Agent",
        status="active",
    )
    session.add(agent)
    await session.commit()

    return {
        "org_id": org_id,
        "gateway_id": gateway_id,
        "board_id": board_id,
        "agent_id": agent_id,
    }


# ---------------------------------------------------------------------------
# Authorization tests — model controls (agent endpoints)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_accessing_own_model_assignment_200() -> None:
    """Agent calling GET on its own model-assignment should succeed."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    # Build actor as the agent itself
    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment")
            assert r.status_code == 200
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_accessing_other_agent_model_assignment_403() -> None:
    """Agent calling GET on a different agent's model-assignment should get 403."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    # Build actor as a DIFFERENT agent
    other_agent = SimpleNamespace(id=uuid4(), board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=other_agent)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment")
            assert r.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_patch_primary_on_other_agent_403() -> None:
    """Agent trying to PATCH primary on a different agent should get 403."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    other_agent = SimpleNamespace(id=uuid4(), board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=other_agent)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.patch(
                f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment/primary",
                json={"selection_mode": "auto"},
            )
            assert r.status_code == 403
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Authorization tests — gateway model profiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_accessing_own_gateway_profiles_200() -> None:
    """Agent calling GET on its own gateway's profiles should succeed."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/gateways/{ids['gateway_id']}/model-profile-defaults")
            assert r.status_code == 200
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_accessing_other_gateway_profiles_403() -> None:
    """Agent calling GET on a different gateway's profiles should get 403."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    # Agent belongs to a different gateway
    other_agent = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=uuid4())
    actor = ActorContext(actor_type="agent", agent=other_agent)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/gateways/{ids['gateway_id']}/model-profile-defaults")
            assert r.status_code == 403
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Phantom record prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_assignment_nonexistent_agent_404() -> None:
    """GET model-assignment for a nonexistent agent_id should return 404."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    fake_agent_id = uuid4()
    # Actor is an agent with matching id so authz passes, but the agent doesn't exist in DB
    agent_obj = SimpleNamespace(id=fake_agent_id, board_id=uuid4(), gateway_id=uuid4())
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/mission-control/agents/{fake_agent_id}/model-assignment")
            assert r.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_primary_nonexistent_agent_404() -> None:
    """PATCH primary for a nonexistent agent_id should return 404."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    fake_agent_id = uuid4()
    agent_obj = SimpleNamespace(id=fake_agent_id, board_id=uuid4(), gateway_id=uuid4())
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.patch(
                f"/api/v1/mission-control/agents/{fake_agent_id}/model-assignment/primary",
                json={"selection_mode": "auto"},
            )
            assert r.status_code == 404
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Gateway not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateway_profiles_nonexistent_gateway_404() -> None:
    """GET model-profile-defaults for a nonexistent gateway should return 404."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    fake_gw_id = uuid4()
    agent_obj = SimpleNamespace(id=uuid4(), board_id=uuid4(), gateway_id=fake_gw_id)
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(f"/api/v1/gateways/{fake_gw_id}/model-profile-defaults")
            assert r.status_code == 404
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_primary_invalid_selection_mode_422() -> None:
    """PATCH primary with invalid selection_mode should return 422."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.patch(
                f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment/primary",
                json={"selection_mode": "invalid_mode"},
            )
            assert r.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_put_fallback_invalid_override_mode_422() -> None:
    """PUT fallback-override with invalid override_mode should return 422."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.put(
                f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment/fallback-override",
                json={"override_mode": "invalid_mode", "entries": []},
            )
            assert r.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_put_fallback_invalid_trigger_type_422() -> None:
    """PUT fallback-override with invalid trigger_type in entries should return 422."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.put(
                f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment/fallback-override",
                json={
                    "override_mode": "replace",
                    "entries": [
                        {
                            "model_id": "9router/cx/gpt-5.4",
                            "position": 0,
                            "trigger_type": "bogus_trigger",
                        }
                    ],
                },
            )
            assert r.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_primary_valid_auto_200() -> None:
    """PATCH primary with valid selection_mode='auto' should succeed."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.patch(
                f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment/primary",
                json={"selection_mode": "auto"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["primary"]["selection_mode"] == "auto"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_put_fallback_valid_none_200() -> None:
    """PUT fallback-override with valid override_mode='none' should succeed."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sm() as session:
        ids = await _seed_org_board_agent_gateway(session)

    agent_obj = SimpleNamespace(id=ids["agent_id"], board_id=ids["board_id"], gateway_id=ids["gateway_id"])
    actor = ActorContext(actor_type="agent", agent=agent_obj)
    app = _build_app(sm, actor)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.put(
                f"/api/v1/mission-control/agents/{ids['agent_id']}/model-assignment/fallback-override",
                json={"override_mode": "none", "entries": []},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["fallback"]["override_mode"] == "none"
    finally:
        await engine.dispose()
