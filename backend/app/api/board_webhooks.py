"""Board webhook configuration and inbound payload ingestion endpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import col, select

from app.api.deps import get_board_for_user_read, get_board_for_user_write, get_board_or_404
from app.core.config import settings
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.models.board_webhook_payloads import BoardWebhookPayload
from app.models.board_webhooks import BoardWebhook
from app.schemas.board_webhooks import (
    BoardWebhookCreate,
    BoardWebhookIngestResponse,
    BoardWebhookPayloadRead,
    BoardWebhookRead,
    BoardWebhookUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.openclaw.gateway_dispatch import GatewayDispatchService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/webhooks", tags=["board-webhooks"])
SESSION_DEP = Depends(get_session)
BOARD_USER_READ_DEP = Depends(get_board_for_user_read)
BOARD_USER_WRITE_DEP = Depends(get_board_for_user_write)
BOARD_OR_404_DEP = Depends(get_board_or_404)
PAYLOAD_PREVIEW_MAX_CHARS = 1600


def _webhook_endpoint_path(board_id: UUID, webhook_id: UUID) -> str:
    return f"/api/v1/boards/{board_id}/webhooks/{webhook_id}"


def _webhook_endpoint_url(endpoint_path: str) -> str | None:
    base_url = settings.base_url.rstrip("/")
    if not base_url:
        return None
    return f"{base_url}{endpoint_path}"


def _to_webhook_read(webhook: BoardWebhook) -> BoardWebhookRead:
    endpoint_path = _webhook_endpoint_path(webhook.board_id, webhook.id)
    return BoardWebhookRead(
        id=webhook.id,
        board_id=webhook.board_id,
        description=webhook.description,
        enabled=webhook.enabled,
        endpoint_path=endpoint_path,
        endpoint_url=_webhook_endpoint_url(endpoint_path),
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
    )


def _to_payload_read(payload: BoardWebhookPayload) -> BoardWebhookPayloadRead:
    return BoardWebhookPayloadRead.model_validate(payload, from_attributes=True)


def _coerce_webhook_items(items: Sequence[object]) -> list[BoardWebhook]:
    values: list[BoardWebhook] = []
    for item in items:
        if not isinstance(item, BoardWebhook):
            msg = "Expected BoardWebhook items from paginated query"
            raise TypeError(msg)
        values.append(item)
    return values


def _coerce_payload_items(items: Sequence[object]) -> list[BoardWebhookPayload]:
    values: list[BoardWebhookPayload] = []
    for item in items:
        if not isinstance(item, BoardWebhookPayload):
            msg = "Expected BoardWebhookPayload items from paginated query"
            raise TypeError(msg)
        values.append(item)
    return values


async def _require_board_webhook(
    session: AsyncSession,
    *,
    board_id: UUID,
    webhook_id: UUID,
) -> BoardWebhook:
    webhook = (
        await session.exec(
            select(BoardWebhook)
            .where(col(BoardWebhook.id) == webhook_id)
            .where(col(BoardWebhook.board_id) == board_id),
        )
    ).first()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return webhook


async def _require_board_webhook_payload(
    session: AsyncSession,
    *,
    board_id: UUID,
    webhook_id: UUID,
    payload_id: UUID,
) -> BoardWebhookPayload:
    payload = (
        await session.exec(
            select(BoardWebhookPayload)
            .where(col(BoardWebhookPayload.id) == payload_id)
            .where(col(BoardWebhookPayload.board_id) == board_id)
            .where(col(BoardWebhookPayload.webhook_id) == webhook_id),
        )
    ).first()
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return payload


def _decode_payload(
    raw_body: bytes,
    *,
    content_type: str | None,
) -> dict[str, object] | list[object] | str | int | float | bool | None:
    if not raw_body:
        return {}

    body_text = raw_body.decode("utf-8", errors="replace")
    normalized_content_type = (content_type or "").lower()
    should_parse_json = "application/json" in normalized_content_type
    if not should_parse_json:
        should_parse_json = body_text.startswith(("{", "[", '"')) or body_text in {"true", "false"}

    if should_parse_json:
        try:
            parsed = json.loads(body_text)
        except json.JSONDecodeError:
            return body_text
        if isinstance(parsed, (dict, list, str, int, float, bool)) or parsed is None:
            return parsed
    return body_text


def _captured_headers(request: Request) -> dict[str, str] | None:
    captured: dict[str, str] = {}
    for header, value in request.headers.items():
        normalized = header.lower()
        if normalized in {"content-type", "user-agent"} or normalized.startswith("x-"):
            captured[normalized] = value
    return captured or None


def _payload_preview(
    value: dict[str, object] | list[object] | str | int | float | bool | None,
) -> str:
    if isinstance(value, str):
        preview = value
    else:
        try:
            preview = json.dumps(value, indent=2, ensure_ascii=True)
        except TypeError:
            preview = str(value)
    if len(preview) <= PAYLOAD_PREVIEW_MAX_CHARS:
        return preview
    return f"{preview[: PAYLOAD_PREVIEW_MAX_CHARS - 3]}..."


def _webhook_memory_content(
    *,
    webhook: BoardWebhook,
    payload: BoardWebhookPayload,
) -> str:
    preview = _payload_preview(payload.payload)
    inspect_path = f"/api/v1/boards/{webhook.board_id}/webhooks/{webhook.id}/payloads/{payload.id}"
    return (
        "WEBHOOK PAYLOAD RECEIVED\n"
        f"Webhook ID: {webhook.id}\n"
        f"Payload ID: {payload.id}\n"
        f"Instruction: {webhook.description}\n"
        f"Inspect (admin API): {inspect_path}\n\n"
        "Payload preview:\n"
        f"{preview}"
    )


async def _notify_lead_on_webhook_payload(
    *,
    session: AsyncSession,
    board: Board,
    webhook: BoardWebhook,
    payload: BoardWebhookPayload,
) -> None:
    lead = (
        await Agent.objects.filter_by(board_id=board.id)
        .filter(col(Agent.is_board_lead).is_(True))
        .first(session)
    )
    if lead is None or not lead.openclaw_session_id:
        return

    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return

    payload_preview = _payload_preview(payload.payload)
    message = (
        "WEBHOOK EVENT RECEIVED\n"
        f"Board: {board.name}\n"
        f"Webhook ID: {webhook.id}\n"
        f"Payload ID: {payload.id}\n"
        f"Instruction: {webhook.description}\n\n"
        "Take action:\n"
        "1) Triage this payload against the webhook instruction.\n"
        "2) Create/update tasks as needed.\n"
        f"3) Reference payload ID {payload.id} in task descriptions.\n\n"
        "Payload preview:\n"
        f"{payload_preview}\n\n"
        "To inspect board memory entries:\n"
        f"GET /api/v1/agent/boards/{board.id}/memory?is_chat=false"
    )
    await dispatch.try_send_agent_message(
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=message,
        deliver=False,
    )


@router.get("", response_model=DefaultLimitOffsetPage[BoardWebhookRead])
async def list_board_webhooks(
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[BoardWebhookRead]:
    """List configured webhooks for a board."""
    statement = (
        select(BoardWebhook)
        .where(col(BoardWebhook.board_id) == board.id)
        .order_by(col(BoardWebhook.created_at).desc())
    )

    def _transform(items: Sequence[object]) -> Sequence[object]:
        webhooks = _coerce_webhook_items(items)
        return [_to_webhook_read(value) for value in webhooks]

    return await paginate(session, statement, transformer=_transform)


@router.post("", response_model=BoardWebhookRead)
async def create_board_webhook(
    payload: BoardWebhookCreate,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardWebhookRead:
    """Create a new board webhook with a generated UUID endpoint."""
    webhook = BoardWebhook(
        board_id=board.id,
        description=payload.description,
        enabled=payload.enabled,
    )
    await crud.save(session, webhook)
    return _to_webhook_read(webhook)


@router.get("/{webhook_id}", response_model=BoardWebhookRead)
async def get_board_webhook(
    webhook_id: UUID,
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardWebhookRead:
    """Get one board webhook configuration."""
    webhook = await _require_board_webhook(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
    )
    return _to_webhook_read(webhook)


@router.patch("/{webhook_id}", response_model=BoardWebhookRead)
async def update_board_webhook(
    webhook_id: UUID,
    payload: BoardWebhookUpdate,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardWebhookRead:
    """Update board webhook description or enabled state."""
    webhook = await _require_board_webhook(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
    )
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        crud.apply_updates(webhook, updates)
        webhook.updated_at = utcnow()
        await crud.save(session, webhook)
    return _to_webhook_read(webhook)


@router.delete("/{webhook_id}", response_model=OkResponse)
async def delete_board_webhook(
    webhook_id: UUID,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OkResponse:
    """Delete a webhook and its stored payload rows."""
    webhook = await _require_board_webhook(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
    )
    await crud.delete_where(
        session,
        BoardWebhookPayload,
        col(BoardWebhookPayload.webhook_id) == webhook.id,
        commit=False,
    )
    await session.delete(webhook)
    await session.commit()
    return OkResponse()


@router.get(
    "/{webhook_id}/payloads", response_model=DefaultLimitOffsetPage[BoardWebhookPayloadRead]
)
async def list_board_webhook_payloads(
    webhook_id: UUID,
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[BoardWebhookPayloadRead]:
    """List stored payloads for one board webhook."""
    await _require_board_webhook(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
    )
    statement = (
        select(BoardWebhookPayload)
        .where(col(BoardWebhookPayload.board_id) == board.id)
        .where(col(BoardWebhookPayload.webhook_id) == webhook_id)
        .order_by(col(BoardWebhookPayload.received_at).desc())
    )

    def _transform(items: Sequence[object]) -> Sequence[object]:
        payloads = _coerce_payload_items(items)
        return [_to_payload_read(value) for value in payloads]

    return await paginate(session, statement, transformer=_transform)


@router.get("/{webhook_id}/payloads/{payload_id}", response_model=BoardWebhookPayloadRead)
async def get_board_webhook_payload(
    webhook_id: UUID,
    payload_id: UUID,
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardWebhookPayloadRead:
    """Get a single stored payload for one board webhook."""
    await _require_board_webhook(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
    )
    payload = await _require_board_webhook_payload(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
        payload_id=payload_id,
    )
    return _to_payload_read(payload)


@router.post(
    "/{webhook_id}",
    response_model=BoardWebhookIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_board_webhook(
    request: Request,
    webhook_id: UUID,
    board: Board = BOARD_OR_404_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardWebhookIngestResponse:
    """Open inbound webhook endpoint that stores payloads and nudges the board lead."""
    webhook = await _require_board_webhook(
        session,
        board_id=board.id,
        webhook_id=webhook_id,
    )
    if not webhook.enabled:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Webhook is disabled.",
        )

    content_type = request.headers.get("content-type")
    payload_value = _decode_payload(
        await request.body(),
        content_type=content_type,
    )
    payload = BoardWebhookPayload(
        board_id=board.id,
        webhook_id=webhook.id,
        payload=payload_value,
        headers=_captured_headers(request),
        source_ip=request.client.host if request.client else None,
        content_type=content_type,
    )
    session.add(payload)
    memory = BoardMemory(
        board_id=board.id,
        content=_webhook_memory_content(webhook=webhook, payload=payload),
        tags=[
            "webhook",
            f"webhook:{webhook.id}",
            f"payload:{payload.id}",
        ],
        source="webhook",
        is_chat=False,
    )
    session.add(memory)
    await session.commit()
    await _notify_lead_on_webhook_payload(
        session=session,
        board=board,
        webhook=webhook,
        payload=payload,
    )
    return BoardWebhookIngestResponse(
        board_id=board.id,
        webhook_id=webhook.id,
        payload_id=payload.id,
    )
