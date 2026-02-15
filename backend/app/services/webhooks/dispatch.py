"""Webhook dispatch worker routines."""

from __future__ import annotations

import asyncio
import time

from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.board_webhook_payloads import BoardWebhookPayload
from app.models.board_webhooks import BoardWebhook
from app.models.boards import Board
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.webhooks.queue import (
    QueuedInboundDelivery,
    dequeue_webhook_delivery,
    requeue_if_failed,
)

logger = get_logger(__name__)


def _build_payload_preview(payload_value: object) -> str:
    if isinstance(payload_value, str):
        return payload_value
    try:
        import json

        return json.dumps(payload_value, indent=2, ensure_ascii=True)
    except TypeError:
        return str(payload_value)


def _payload_preview(payload_value: object) -> str:
    preview = _build_payload_preview(payload_value)
    if len(preview) <= 1600:
        return preview
    return f"{preview[:1597]}..."


def _webhook_message(
    *,
    board: Board,
    webhook: BoardWebhook,
    payload: BoardWebhookPayload,
) -> str:
    preview = _payload_preview(payload.payload)
    return (
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
        f"{preview}\n\n"
        "To inspect board memory entries:\n"
        f"GET /api/v1/agent/boards/{board.id}/memory?is_chat=false"
    )


async def _notify_lead(
    *,
    session: AsyncSession,
    board: Board,
    webhook: BoardWebhook,
    payload: BoardWebhookPayload,
) -> None:
    lead = await Agent.objects.filter_by(board_id=board.id, is_board_lead=True).first(session)
    if lead is None or not lead.openclaw_session_id:
        return

    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return

    message = _webhook_message(board=board, webhook=webhook, payload=payload)
    await dispatch.try_send_agent_message(
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=message,
        deliver=False,
    )


async def _load_webhook_payload(
    *,
    session: AsyncSession,
    payload_id: UUID,
    webhook_id: UUID,
    board_id: UUID,
) -> tuple[Board, BoardWebhook, BoardWebhookPayload] | None:
    payload = await session.get(BoardWebhookPayload, payload_id)
    if payload is None:
        logger.warning(
            "webhook.queue.payload_missing",
            extra={
                "payload_id": str(payload_id),
                "webhook_id": str(webhook_id),
                "board_id": str(board_id),
            },
        )
        return None

    if payload.board_id != board_id or payload.webhook_id != webhook_id:
        logger.warning(
            "webhook.queue.payload_mismatch",
            extra={
                "payload_id": str(payload_id),
                "payload_webhook_id": str(payload.webhook_id),
                "payload_board_id": str(payload.board_id),
            },
        )
        return None

    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        logger.warning(
            "webhook.queue.board_missing",
            extra={"board_id": str(board_id), "payload_id": str(payload_id)},
        )
        return None

    webhook = await session.get(BoardWebhook, webhook_id)
    if webhook is None:
        logger.warning(
            "webhook.queue.webhook_missing",
            extra={"webhook_id": str(webhook_id), "board_id": str(board_id)},
        )
        return None

    if webhook.board_id != board_id:
        logger.warning(
            "webhook.queue.webhook_board_mismatch",
            extra={
                "webhook_id": str(webhook_id),
                "payload_board_id": str(payload.board_id),
                "expected_board_id": str(board_id),
            },
        )
        return None

    return board, webhook, payload


async def _process_single_item(item: QueuedInboundDelivery) -> None:
    async with async_session_maker() as session:
        loaded = await _load_webhook_payload(
            session=session,
            payload_id=item.payload_id,
            webhook_id=item.webhook_id,
            board_id=item.board_id,
        )
        if loaded is None:
            return

        board, webhook, payload = loaded
        await _notify_lead(session=session, board=board, webhook=webhook, payload=payload)
        await session.commit()


async def flush_webhook_delivery_queue() -> None:
    """Consume queued webhook events and notify board leads in a throttled batch."""
    processed = 0
    while True:
        try:
            item = dequeue_webhook_delivery()
        except Exception:
            logger.exception("webhook.dispatch.dequeue_failed")
            continue

        if item is None:
            break

        try:
            await _process_single_item(item)
            processed += 1
            logger.info(
                "webhook.dispatch.success",
                extra={
                    "payload_id": str(item.payload_id),
                    "webhook_id": str(item.webhook_id),
                    "board_id": str(item.board_id),
                    "attempt": item.attempts,
                },
            )
        except Exception as exc:
            logger.exception(
                "webhook.dispatch.failed",
                extra={
                    "payload_id": str(item.payload_id),
                    "webhook_id": str(item.webhook_id),
                    "board_id": str(item.board_id),
                    "attempt": item.attempts,
                    "error": str(exc),
                },
            )
            requeue_if_failed(item)
        time.sleep(settings.rq_dispatch_throttle_seconds)
    logger.info("webhook.dispatch.batch_complete", extra={"count": processed})


def run_flush_webhook_delivery_queue() -> None:
    """RQ entrypoint for running the async queue flush from worker jobs."""
    logger.info(
        "webhook.dispatch.batch_started",
        extra={"throttle_seconds": settings.rq_dispatch_throttle_seconds},
    )
    start = time.time()
    asyncio.run(flush_webhook_delivery_queue())
    elapsed_ms = int((time.time() - start) * 1000)
    logger.info("webhook.dispatch.batch_finished", extra={"duration_ms": elapsed_ms})
