"""Deploy notification endpoint for triggering QA-E2E via internal gateway session messaging."""

from __future__ import annotations

import json
from app.core.logging import get_logger
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.models.boards import Board
from app.models.task_pipeline_events import TaskPipelineEvent
from app.models.tasks import Task
from app.services.activity_log import record_activity
from app.services.openclaw.gateway_dispatch import GatewayDispatchService

logger = get_logger(__name__)
router = APIRouter(tags=["deploy"])

TARGET_QA_AGENT_NAME = "QA-E2E"
DEFAULT_BOARD_NAME = "Dev Squad"

# Statuses where deploy_notify rejects outright (vs records an audit
# and proceeds). cancelled = task removed from scope, kicking off QA
# would be pointless and pollute audit trails. Other non-active
# statuses (inbox, rework) are accepted but audited so operators can
# see if real CI workflows fire on those statuses before tightening.
_DEPLOY_NOTIFY_REJECTED_STATUSES: frozenset[str] = frozenset({"cancelled"})
# Active statuses are the canonical webhook targets — silent fast path,
# no audit needed.
_DEPLOY_NOTIFY_ACTIVE_STATUSES: frozenset[str] = frozenset(
    {"in_progress", "review", "done"},
)


class DeployNotifyPayload(BaseModel):
    """Payload for deploy notification."""

    task_id: UUID = Field(..., description="Real board task ID that triggered the deploy")
    build_hash: str = Field(..., description="Build hash of the deployed artifact")
    deploy_target: str = Field(..., description="Target environment (e.g., staging, prod)")
    commit_sha: str = Field(..., description="Git commit SHA of the deployed code")


class DeployNotifyResponse(BaseModel):
    """Response from deploy notification."""

    ok: bool
    queued: bool
    target_agent: str
    session_key: str
    payload: dict[str, Any]
    dispatch: dict[str, Any]


async def _resolve_target_agent(session) -> tuple[Board, Agent]:
    board = (
        await session.exec(
            select(Board).where(func.lower(Board.name) == DEFAULT_BOARD_NAME.lower())
        )
    ).first()
    if board is None:
        raise HTTPException(status_code=503, detail="Target board not found for QA-E2E dispatch")

    agent = (
        await session.exec(
            select(Agent)
            .where(col(Agent.board_id) == board.id)
            .where(func.lower(Agent.name) == TARGET_QA_AGENT_NAME.lower())
        )
    ).first()
    if agent is None or not agent.openclaw_session_id:
        raise HTTPException(status_code=503, detail="QA-E2E agent session unavailable")
    return board, agent


async def _require_board_task(session, *, board_id: UUID, task_id: UUID) -> Task:
    task = (
        await session.exec(
            select(Task)
            .where(col(Task.id) == task_id)
            .where(col(Task.board_id) == board_id)
        )
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found on target board")
    return task


def _dispatch_message(payload: dict[str, Any]) -> str:
    lines = [
        "DEPLOY NOTIFY",
        "Source: mission-control.deploy_notify",
        f"task_id: {payload['task_id']}",
        f"board_id: {payload['board_id']}",
        f"board_name: {payload['board_name']}",
        f"task_title: {payload['task_title']}",
        f"task_status: {payload['task_status']}",
        f"build_hash: {payload['build_hash']}",
        f"deploy_target: {payload['deploy_target']}",
        f"commit_sha: {payload['commit_sha']}",
        f"triggered_at: {payload['triggered_at']}",
        "",
        "QA contract:",
        "- task_id is a real Dev Squad board task UUID",
        "- board_name and board_id are included for authoritative lookup",
        "- task_title and task_status are included for QA queue context",
        "",
        "Treat this as an internal QA-E2E trigger and begin validation on your next heartbeat.",
    ]
    return "\n".join(lines)


@router.post("/deploy/notify", status_code=202, response_model=DeployNotifyResponse)
async def api_deploy_notify(payload: DeployNotifyPayload = Body(...)) -> DeployNotifyResponse:
    """Receive deploy notification and trigger QA-E2E via gateway session message."""
    for field_name, value in payload.model_dump().items():
        if value is None or not str(value).strip():
            raise HTTPException(status_code=422, detail=f"{field_name} is required")

    async with async_session_maker() as session:
        board, agent = await _resolve_target_agent(session)
        task = await _require_board_task(session, board_id=board.id, task_id=payload.task_id)

        if task.status in _DEPLOY_NOTIFY_REJECTED_STATUSES:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"Task is `{task.status}` — operator/lead has removed "
                        f"it from scope. Deploy notification will not be "
                        f"recorded; ask operator to reactivate the task before "
                        f"firing the webhook."
                    ),
                    "code": "deploy_notify_task_cancelled",
                    "current_status": task.status,
                },
            )
        if task.status not in _DEPLOY_NOTIFY_ACTIVE_STATUSES:
            # Audit only — accept the deploy_notify but record so
            # operators can see if real CI workflows are firing on
            # non-active statuses (e.g. inbox/rework). If observed
            # traffic shows none of these are legitimate, the gate
            # can be tightened in a follow-up.
            record_activity(
                session,
                event_type="task.deploy_notify_on_non_active_status",
                task_id=task.id,
                board_id=board.id,
                message=(
                    f"deploy_notify fired while task.status={task.status}. "
                    f"build_hash={payload.build_hash} commit={payload.commit_sha}. "
                    f"Active webhook targets are in_progress/review/done."
                ),
            )

        dispatch_payload = {
            "task_id": str(payload.task_id),
            "board_id": str(board.id),
            "board_name": board.name,
            "task_title": task.title,
            "task_status": task.status,
            "build_hash": payload.build_hash,
            "deploy_target": payload.deploy_target,
            "commit_sha": payload.commit_sha,
            "trigger_source": "mission-control.deploy_notify",
            "triggered_at": utcnow().isoformat(),
        }
        for state in ("built", "deployed"):
            session.add(
                TaskPipelineEvent(
                    board_id=board.id,
                    task_id=task.id,
                    agent_id=None,
                    state=state,
                    source="deploy_notify",
                    commit_sha=payload.commit_sha,
                    artifact_hash=payload.build_hash,
                    deploy_target=payload.deploy_target,
                    evidence={
                        "trigger_source": "mission-control.deploy_notify",
                        "build_hash": payload.build_hash,
                    },
                ),
            )

        dispatch = GatewayDispatchService(session)
        config = await dispatch.optional_gateway_config_for_board(board)
        if config is None:
            raise HTTPException(status_code=503, detail="Gateway config unavailable for QA-E2E dispatch")

        error = await dispatch.try_send_agent_message(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=_dispatch_message(dispatch_payload),
            deliver=False,
        )

        dispatch_result = {
            "ok": error is None,
            "via": "gateway_session_message",
            "target_agent": agent.name,
            "session_key": agent.openclaw_session_id,
        }
        if error is not None:
            logger.warning(
                "deploy_notify gateway dispatch failed for %s: %s",
                agent.openclaw_session_id,
                error,
            )
            dispatch_result["error"] = str(error)

        try:
            memory = BoardMemory(
                board_id=board.id,
                content=json.dumps(
                    {
                        "event_type": "deploy_notify_sent",
                        "source": "pf-deploy",
                        "payload": dispatch_payload,
                        "dispatch": dispatch_result,
                    }
                ),
                tags=["deploy", "gateway-session", "qa-e2e"],
            )
            session.add(memory)
            await session.commit()
        except Exception as exc:
            logger.warning("Failed to store deploy_notify event in board memory: %s", exc)

    return DeployNotifyResponse(
        ok=True,
        queued=True,
        target_agent=TARGET_QA_AGENT_NAME,
        session_key=dispatch_result["session_key"],
        payload=dispatch_payload,
        dispatch=dispatch_result,
    )
