from __future__ import annotations

import logging
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import ActorContext, get_board_or_404, require_admin_auth, require_admin_or_agent
from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.core.auth import AuthContext
from app.core.config import settings
from app.core.time import utcnow
from app.db.session import get_session
from app.integrations.openclaw_gateway import GatewayConfig as GatewayClientConfig
from app.integrations.openclaw_gateway import OpenClawGatewayError, ensure_session, send_message
from app.models.agents import Agent
from app.models.board_onboarding import BoardOnboardingSession
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.board_onboarding import (
    BoardOnboardingAnswer,
    BoardOnboardingAgentComplete,
    BoardOnboardingAgentUpdate,
    BoardOnboardingConfirm,
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingRead,
    BoardOnboardingStart,
    BoardOnboardingUserProfile,
)
from app.schemas.boards import BoardRead
from app.services.agent_provisioning import DEFAULT_HEARTBEAT_CONFIG, provision_agent

router = APIRouter(prefix="/boards/{board_id}/onboarding", tags=["board-onboarding"])
logger = logging.getLogger(__name__)


async def _gateway_config(
    session: AsyncSession, board: Board
) -> tuple[Gateway, GatewayClientConfig]:
    if not board.gateway_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    gateway = await session.get(Gateway, board.gateway_id)
    if gateway is None or not gateway.url or not gateway.main_session_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return gateway, GatewayClientConfig(url=gateway.url, token=gateway.token)


def _build_session_key(agent_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", agent_name.lower()).strip("-")
    return f"agent:{slug or uuid4().hex}:main"


def _lead_agent_name(board: Board) -> str:
    return "Lead Agent"


def _lead_session_key(board: Board) -> str:
    return f"agent:lead-{board.id}:main"


async def _ensure_lead_agent(
    session: AsyncSession,
    board: Board,
    gateway: Gateway,
    config: GatewayClientConfig,
    auth: AuthContext,
    *,
    agent_name: str | None = None,
    identity_profile: dict[str, str] | None = None,
) -> Agent:
    existing = (
        await session.exec(
            select(Agent)
            .where(Agent.board_id == board.id)
            .where(col(Agent.is_board_lead).is_(True))
        )
    ).first()
    if existing:
        desired_name = agent_name or _lead_agent_name(board)
        if existing.name != desired_name:
            existing.name = desired_name
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
        return existing

    merged_identity_profile = {
        "role": "Board Lead",
        "communication_style": "direct, concise, practical",
        "emoji": ":gear:",
    }
    if identity_profile:
        merged_identity_profile.update(
            {key: value.strip() for key, value in identity_profile.items() if value.strip()}
        )

    agent = Agent(
        name=agent_name or _lead_agent_name(board),
        status="provisioning",
        board_id=board.id,
        is_board_lead=True,
        heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
        identity_profile=merged_identity_profile,
    )
    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    agent.provision_requested_at = utcnow()
    agent.provision_action = "provision"
    agent.openclaw_session_id = _lead_session_key(board)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    try:
        await provision_agent(agent, board, gateway, raw_token, auth.user, action="provision")
        await ensure_session(agent.openclaw_session_id, config=config, label=agent.name)
        await send_message(
            (
                f"Hello {agent.name}. Your workspace has been provisioned.\n\n"
                "Start the agent, run BOOT.md, and if BOOTSTRAP.md exists run it once "
                "then delete it. Begin heartbeats after startup."
            ),
            session_key=agent.openclaw_session_id,
            config=config,
            deliver=True,
        )
    except OpenClawGatewayError:
        # Best-effort provisioning. Board confirmation should still succeed.
        pass
    return agent


@router.get("", response_model=BoardOnboardingRead)
async def get_onboarding(
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> BoardOnboardingSession:
    onboarding = (
        await session.exec(
            select(BoardOnboardingSession)
            .where(BoardOnboardingSession.board_id == board.id)
            .order_by(col(BoardOnboardingSession.created_at).desc())
        )
    ).first()
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return onboarding


@router.post("/start", response_model=BoardOnboardingRead)
async def start_onboarding(
    payload: BoardOnboardingStart,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> BoardOnboardingSession:
    onboarding = (
        await session.exec(
            select(BoardOnboardingSession)
            .where(BoardOnboardingSession.board_id == board.id)
            .where(BoardOnboardingSession.status == "active")
        )
    ).first()
    if onboarding:
        return onboarding

    gateway, config = await _gateway_config(session, board)
    session_key = gateway.main_session_key
    base_url = settings.base_url or "http://localhost:8000"
    prompt = (
        "BOARD ONBOARDING REQUEST\n\n"
        f"Board Name: {board.name}\n"
        "You are the main agent. Ask the user 6-10 focused questions total:\n"
        "- 3-6 questions to clarify the board goal.\n"
        "- 1 question to choose a unique name for the board lead agent (first-name style).\n"
        "- 2-4 questions to capture the user's preferences for how the board lead should work\n"
        "  (communication style, autonomy, update cadence, and output formatting).\n"
        "Do NOT respond in OpenClaw chat.\n"
        "All onboarding responses MUST be sent to Mission Control via API.\n"
        f"Mission Control base URL: {base_url}\n"
        "Use the AUTH_TOKEN from USER.md or TOOLS.md and pass it as X-Agent-Token.\n"
        "Onboarding response endpoint:\n"
        f"POST {base_url}/api/v1/agent/boards/{board.id}/onboarding\n"
        "QUESTION example (send JSON body exactly as shown):\n"
        f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding" '
        '-H "X-Agent-Token: $AUTH_TOKEN" '
        '-H "Content-Type: application/json" '
        '-d \'{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}]}\'\n'
        "COMPLETION example (send JSON body exactly as shown):\n"
        f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding" '
        '-H "X-Agent-Token: $AUTH_TOKEN" '
        '-H "Content-Type: application/json" '
        '-d \'{"status":"complete","board_type":"goal","objective":"...","success_metrics":{"metric":"...","target":"..."},"target_date":"YYYY-MM-DD","user_profile":{"preferred_name":"...","pronouns":"...","timezone":"...","notes":"...","context":"..."},"lead_agent":{"name":"Ava","identity_profile":{"role":"Board Lead","communication_style":"direct, concise, practical","emoji":":gear:"},"autonomy_level":"balanced","verbosity":"concise","output_format":"bullets","update_cadence":"daily","custom_instructions":"..."}}\'\n'
        "ENUMS:\n"
        "- board_type: goal | general\n"
        "- lead_agent.autonomy_level: ask_first | balanced | autonomous\n"
        "- lead_agent.verbosity: concise | balanced | detailed\n"
        "- lead_agent.output_format: bullets | mixed | narrative\n"
        "- lead_agent.update_cadence: asap | hourly | daily | weekly\n"
        "QUESTION FORMAT (one question per response, no arrays, no markdown, no extra text):\n"
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}]}\n'
        "Do NOT wrap questions in a list. Do NOT add commentary.\n"
        "When you have enough info, send one final response with status=complete.\n"
        "The completion payload must include board_type. If board_type=goal, include objective + success_metrics.\n"
        "Also include user_profile + lead_agent to configure the board lead's working style.\n"
    )

    try:
        await ensure_session(session_key, config=config, label="Main Agent")
        await send_message(prompt, session_key=session_key, config=config, deliver=False)
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    onboarding = BoardOnboardingSession(
        board_id=board.id,
        session_key=session_key,
        status="active",
        messages=[{"role": "user", "content": prompt, "timestamp": utcnow().isoformat()}],
    )
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/answer", response_model=BoardOnboardingRead)
async def answer_onboarding(
    payload: BoardOnboardingAnswer,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> BoardOnboardingSession:
    onboarding = (
        await session.exec(
            select(BoardOnboardingSession)
            .where(BoardOnboardingSession.board_id == board.id)
            .order_by(col(BoardOnboardingSession.created_at).desc())
        )
    ).first()
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    _, config = await _gateway_config(session, board)
    answer_text = payload.answer
    if payload.other_text:
        answer_text = f"{payload.answer}: {payload.other_text}"

    messages = list(onboarding.messages or [])
    messages.append(
        {"role": "user", "content": answer_text, "timestamp": utcnow().isoformat()}
    )

    try:
        await ensure_session(onboarding.session_key, config=config, label="Main Agent")
        await send_message(
            answer_text, session_key=onboarding.session_key, config=config, deliver=False
        )
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/agent", response_model=BoardOnboardingRead)
async def agent_onboarding_update(
    payload: BoardOnboardingAgentUpdate,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    actor: ActorContext = Depends(require_admin_or_agent),
) -> BoardOnboardingSession:
    if actor.actor_type != "agent" or actor.agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    agent = actor.agent
    if agent.board_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if board.gateway_id:
        gateway = await session.get(Gateway, board.gateway_id)
        if gateway and gateway.main_session_key and agent.openclaw_session_id:
            if agent.openclaw_session_id != gateway.main_session_key:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    onboarding = (
        await session.exec(
            select(BoardOnboardingSession)
            .where(BoardOnboardingSession.board_id == board.id)
            .order_by(col(BoardOnboardingSession.created_at).desc())
        )
    ).first()
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if onboarding.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    messages = list(onboarding.messages or [])
    now = utcnow().isoformat()
    payload_text = payload.model_dump_json(exclude_none=True)
    payload_data = payload.model_dump(mode="json", exclude_none=True)
    logger.info(
        "onboarding.agent.update board_id=%s agent_id=%s payload=%s",
        board.id,
        agent.id,
        payload_text,
    )
    if isinstance(payload, BoardOnboardingAgentComplete):
        onboarding.draft_goal = payload_data
        onboarding.status = "completed"
        messages.append({"role": "assistant", "content": payload_text, "timestamp": now})
    else:
        messages.append({"role": "assistant", "content": payload_text, "timestamp": now})

    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    logger.info(
        "onboarding.agent.update stored board_id=%s messages_count=%s status=%s",
        board.id,
        len(onboarding.messages or []),
        onboarding.status,
    )
    return onboarding


@router.post("/confirm", response_model=BoardRead)
async def confirm_onboarding(
    payload: BoardOnboardingConfirm,
    board: Board = Depends(get_board_or_404),
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_admin_auth),
) -> Board:
    onboarding = (
        await session.exec(
            select(BoardOnboardingSession)
            .where(BoardOnboardingSession.board_id == board.id)
            .order_by(col(BoardOnboardingSession.created_at).desc())
        )
    ).first()
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    board.board_type = payload.board_type
    board.objective = payload.objective
    board.success_metrics = payload.success_metrics
    board.target_date = payload.target_date
    board.goal_confirmed = True
    board.goal_source = "lead_agent_onboarding"

    onboarding.status = "confirmed"
    onboarding.updated_at = utcnow()

    user_profile: BoardOnboardingUserProfile | None = None
    lead_agent: BoardOnboardingLeadAgentDraft | None = None
    if isinstance(onboarding.draft_goal, dict):
        raw_profile = onboarding.draft_goal.get("user_profile")
        if raw_profile is not None:
            try:
                user_profile = BoardOnboardingUserProfile.model_validate(raw_profile)
            except ValidationError:
                user_profile = None
        raw_lead = onboarding.draft_goal.get("lead_agent")
        if raw_lead is not None:
            try:
                lead_agent = BoardOnboardingLeadAgentDraft.model_validate(raw_lead)
            except ValidationError:
                lead_agent = None

    if auth.user and user_profile:
        changed = False
        if user_profile.preferred_name is not None:
            auth.user.preferred_name = user_profile.preferred_name
            changed = True
        if user_profile.pronouns is not None:
            auth.user.pronouns = user_profile.pronouns
            changed = True
        if user_profile.timezone is not None:
            auth.user.timezone = user_profile.timezone
            changed = True
        if user_profile.notes is not None:
            auth.user.notes = user_profile.notes
            changed = True
        if user_profile.context is not None:
            auth.user.context = user_profile.context
            changed = True
        if changed:
            session.add(auth.user)

    lead_identity_profile: dict[str, str] = {}
    lead_name: str | None = None
    if lead_agent:
        lead_name = lead_agent.name
        if lead_agent.identity_profile:
            lead_identity_profile.update(lead_agent.identity_profile)
        if lead_agent.autonomy_level:
            lead_identity_profile["autonomy_level"] = lead_agent.autonomy_level
        if lead_agent.verbosity:
            lead_identity_profile["verbosity"] = lead_agent.verbosity
        if lead_agent.output_format:
            lead_identity_profile["output_format"] = lead_agent.output_format
        if lead_agent.update_cadence:
            lead_identity_profile["update_cadence"] = lead_agent.update_cadence
        if lead_agent.custom_instructions:
            lead_identity_profile["custom_instructions"] = lead_agent.custom_instructions

    gateway, config = await _gateway_config(session, board)
    session.add(board)
    session.add(onboarding)
    await session.commit()
    await session.refresh(board)
    await _ensure_lead_agent(
        session,
        board,
        gateway,
        config,
        auth,
        agent_name=lead_name,
        identity_profile=lead_identity_profile or None,
    )
    return board
