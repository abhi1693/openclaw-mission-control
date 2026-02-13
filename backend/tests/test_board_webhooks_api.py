# ruff: noqa: INP001
"""Integration tests for board webhook ingestion behavior."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import board_webhooks
from app.api.board_webhooks import router as board_webhooks_router
from app.api.deps import get_board_or_404
from app.db.session import get_session
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
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


def _build_test_app(
    session_maker: async_sessionmaker[AsyncSession],
) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(board_webhooks_router)
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


async def _seed_webhook(
    session: AsyncSession,
    *,
    enabled: bool,
) -> tuple[Board, BoardWebhook]:
    organization_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    webhook_id = uuid4()

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
        name="Launch board",
        slug="launch-board",
        description="Board for launch automation.",
    )
    session.add(board)
    session.add(
        Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=gateway_id,
            name="Lead Agent",
            status="online",
            openclaw_session_id="lead:session:key",
            is_board_lead=True,
        ),
    )
    webhook = BoardWebhook(
        id=webhook_id,
        board_id=board_id,
        description="Triage payload and create tasks for impacted services.",
        enabled=enabled,
    )
    session.add(webhook)
    await session.commit()
    return board, webhook


@pytest.mark.asyncio
async def test_ingest_board_webhook_stores_payload_and_notifies_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    app = _build_test_app(session_maker)
    sent_messages: list[dict[str, str]] = []

    async with session_maker() as session:
        board, webhook = await _seed_webhook(session, enabled=True)

    async def _fake_optional_gateway_config_for_board(
        self: board_webhooks.GatewayDispatchService,
        _board: Board,
    ) -> object:
        return object()

    async def _fake_try_send_agent_message(
        self: board_webhooks.GatewayDispatchService,
        *,
        session_key: str,
        config: object,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> None:
        del self, config, deliver
        sent_messages.append(
            {
                "session_key": session_key,
                "agent_name": agent_name,
                "message": message,
            },
        )
        return None

    monkeypatch.setattr(
        board_webhooks.GatewayDispatchService,
        "optional_gateway_config_for_board",
        _fake_optional_gateway_config_for_board,
    )
    monkeypatch.setattr(
        board_webhooks.GatewayDispatchService,
        "try_send_agent_message",
        _fake_try_send_agent_message,
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/boards/{board.id}/webhooks/{webhook.id}",
                json={"event": "deploy", "service": "api"},
                headers={"X-Signature": "sha256=abc123"},
            )

        assert response.status_code == 202
        body = response.json()
        payload_id = UUID(body["payload_id"])
        assert body["board_id"] == str(board.id)
        assert body["webhook_id"] == str(webhook.id)

        async with session_maker() as session:
            payloads = (
                await session.exec(
                    select(BoardWebhookPayload).where(col(BoardWebhookPayload.id) == payload_id),
                )
            ).all()
            assert len(payloads) == 1
            assert payloads[0].payload == {"event": "deploy", "service": "api"}
            assert payloads[0].headers is not None
            assert payloads[0].headers.get("x-signature") == "sha256=abc123"
            assert payloads[0].headers.get("content-type") == "application/json"

            memory_items = (
                await session.exec(
                    select(BoardMemory).where(col(BoardMemory.board_id) == board.id),
                )
            ).all()
            assert len(memory_items) == 1
            assert memory_items[0].source == "webhook"
            assert memory_items[0].tags is not None
            assert f"webhook:{webhook.id}" in memory_items[0].tags
            assert f"payload:{payload_id}" in memory_items[0].tags
            assert f"Payload ID: {payload_id}" in memory_items[0].content

        assert len(sent_messages) == 1
        assert sent_messages[0]["session_key"] == "lead:session:key"
        assert "WEBHOOK EVENT RECEIVED" in sent_messages[0]["message"]
        assert str(payload_id) in sent_messages[0]["message"]
        assert webhook.description in sent_messages[0]["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_board_webhook_rejects_disabled_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    app = _build_test_app(session_maker)
    sent_messages: list[str] = []

    async with session_maker() as session:
        board, webhook = await _seed_webhook(session, enabled=False)

    async def _fake_try_send_agent_message(
        self: board_webhooks.GatewayDispatchService,
        *,
        session_key: str,
        config: object,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> None:
        del self, session_key, config, agent_name, deliver
        sent_messages.append(message)
        return None

    monkeypatch.setattr(
        board_webhooks.GatewayDispatchService,
        "try_send_agent_message",
        _fake_try_send_agent_message,
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/boards/{board.id}/webhooks/{webhook.id}",
                json={"event": "deploy"},
            )

        assert response.status_code == 410
        assert response.json() == {"detail": "Webhook is disabled."}

        async with session_maker() as session:
            stored_payloads = (
                await session.exec(
                    select(BoardWebhookPayload).where(
                        col(BoardWebhookPayload.board_id) == board.id
                    ),
                )
            ).all()
            assert stored_payloads == []
            stored_memory = (
                await session.exec(
                    select(BoardMemory).where(col(BoardMemory.board_id) == board.id),
                )
            ).all()
            assert stored_memory == []

        assert sent_messages == []
    finally:
        await engine.dispose()
