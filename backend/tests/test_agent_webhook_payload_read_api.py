# ruff: noqa: INP001

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.agent import router as agent_router
from app.api.deps import get_board_or_404
from app.core.agent_tokens import hash_agent_token
from app.db.session import get_session
from app.models.agents import Agent
from app.models.board_webhook_payloads import BoardWebhookPayload
from app.models.board_webhooks import BoardWebhook
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_test_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(agent_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    async def _override_get_board_or_404(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        board = await Board.objects.by_id(UUID(board_id)).first(session)
        if board is None:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return board

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_board_or_404] = _override_get_board_or_404
    return app


async def _seed_payload(session: AsyncSession) -> tuple[str, Board, BoardWebhook, BoardWebhookPayload]:
    token = "test-agent-token-" + uuid4().hex
    token_hash = hash_agent_token(token)

    organization_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    webhook_id = uuid4()
    agent_id = uuid4()
    payload_id = uuid4()

    session.add(Organization(id=organization_id, name=f"org-{organization_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=organization_id,
            name="gateway",
            url="https://gateway.example.local",
            workspace_root="/tmp/workspace",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=organization_id,
        gateway_id=gateway_id,
        name="Board",
        slug="board",
    )
    session.add(board)
    session.add(
        Agent(
            id=agent_id,
            board_id=board_id,
            gateway_id=gateway_id,
            name="Lead Agent",
            status="online",
            is_board_lead=True,
            openclaw_session_id="agent:lead:session",
            agent_token_hash=token_hash,
        ),
    )
    webhook = BoardWebhook(
        id=webhook_id,
        board_id=board_id,
        description="Triage payload",
        enabled=True,
    )
    session.add(webhook)
    payload = BoardWebhookPayload(
        id=payload_id,
        board_id=board_id,
        webhook_id=webhook_id,
        payload={"event": "push", "ref": "refs/heads/master"},
        headers={"x-github-event": "push"},
        content_type="application/json",
        source_ip="127.0.0.1",
    )
    session.add(payload)
    await session.commit()
    return token, board, webhook, payload


@pytest.mark.asyncio
async def test_agent_can_fetch_webhook_payload() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, webhook, payload = await _seed_payload(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/agent/boards/{board.id}/webhooks/{webhook.id}/payloads/{payload.id}",
                headers={"X-Agent-Token": token},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(payload.id)
        assert body["board_id"] == str(board.id)
        assert body["webhook_id"] == str(webhook.id)
        assert body["payload"] == {"event": "push", "ref": "refs/heads/master"}
        assert body["headers"]["x-github-event"] == "push"

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_payload_read_rejects_invalid_token() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        _token, board, webhook, payload = await _seed_payload(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/agent/boards/{board.id}/webhooks/{webhook.id}/payloads/{payload.id}",
                headers={"X-Agent-Token": "invalid"},
            )

        assert response.status_code == 401

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_payload_read_rejects_cross_board_access() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, webhook, payload = await _seed_payload(session)

        # Second board + payload that should be inaccessible to the first board agent.
        organization_id = uuid4()
        gateway_id = uuid4()
        other_board = Board(
            id=uuid4(),
            organization_id=organization_id,
            gateway_id=gateway_id,
            name="Other",
            slug="other",
        )
        session.add(Organization(id=organization_id, name=f"org-{organization_id}"))
        session.add(
            Gateway(
                id=gateway_id,
                organization_id=organization_id,
                name="gateway",
                url="https://gateway.example.local",
                workspace_root="/tmp/workspace",
            ),
        )
        session.add(other_board)
        other_webhook = BoardWebhook(
            id=uuid4(),
            board_id=other_board.id,
            description="Other webhook",
            enabled=True,
        )
        session.add(other_webhook)
        other_payload = BoardWebhookPayload(
            id=uuid4(),
            board_id=other_board.id,
            webhook_id=other_webhook.id,
            payload={"event": "push"},
        )
        session.add(other_payload)
        await session.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/agent/boards/{other_board.id}/webhooks/{other_webhook.id}/payloads/{other_payload.id}",
                headers={"X-Agent-Token": token},
            )

        assert response.status_code == 403

    finally:
        await engine.dispose()
