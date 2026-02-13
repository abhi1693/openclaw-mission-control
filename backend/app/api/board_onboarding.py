"""Board onboarding endpoints for user/agent collaboration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlmodel import col

from app.api.deps import (
    ActorContext,
    get_board_for_user_read,
    get_board_for_user_write,
    get_board_or_404,
    require_admin_auth,
    require_admin_or_agent,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.board_onboarding import BoardOnboardingSession
from app.schemas.board_onboarding import (
    BoardOnboardingAgentComplete,
    BoardOnboardingAgentUpdate,
    BoardOnboardingAnswer,
    BoardOnboardingConfirm,
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingRead,
    BoardOnboardingStart,
    BoardOnboardingUserProfile,
)
from app.schemas.boards import BoardRead
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_resolver import get_gateway_for_board
from app.services.openclaw.onboarding_service import BoardOnboardingMessagingService
from app.services.openclaw.policies import OpenClawAuthorizationPolicy
from app.services.openclaw.provisioning_db import (
    LeadAgentOptions,
    LeadAgentRequest,
    OpenClawProvisioningService,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext
    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/onboarding", tags=["board-onboarding"])
logger = get_logger(__name__)
BOARD_USER_READ_DEP = Depends(get_board_for_user_read)
BOARD_USER_WRITE_DEP = Depends(get_board_for_user_write)
BOARD_OR_404_DEP = Depends(get_board_or_404)
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_admin_or_agent)
ADMIN_AUTH_DEP = Depends(require_admin_auth)


def _parse_draft_user_profile(
    draft_goal: object,
) -> BoardOnboardingUserProfile | None:
    if not isinstance(draft_goal, dict):
        return None
    raw_profile = draft_goal.get("user_profile")
    if raw_profile is None:
        return None
    try:
        return BoardOnboardingUserProfile.model_validate(raw_profile)
    except ValidationError:
        return None


def _parse_draft_lead_agent(
    draft_goal: object,
) -> BoardOnboardingLeadAgentDraft | None:
    if not isinstance(draft_goal, dict):
        return None
    raw_lead = draft_goal.get("lead_agent")
    if raw_lead is None:
        return None
    try:
        return BoardOnboardingLeadAgentDraft.model_validate(raw_lead)
    except ValidationError:
        return None


def _normalize_autonomy_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    return text.replace("_", "-")


def _is_fully_autonomous_choice(value: object) -> bool:
    token = _normalize_autonomy_token(value)
    if token is None:
        return False
    if token in {"autonomous", "fully-autonomous", "full-autonomy"}:
        return True
    return "autonom" in token and "fully" in token


def _require_approval_for_done_from_draft(draft_goal: object) -> bool:
    """Enable done-approval gate unless onboarding selected fully autonomous mode."""
    if not isinstance(draft_goal, dict):
        return True
    raw_lead = draft_goal.get("lead_agent")
    if not isinstance(raw_lead, dict):
        return True
    if _is_fully_autonomous_choice(raw_lead.get("autonomy_level")):
        return False
    raw_identity_profile = raw_lead.get("identity_profile")
    if isinstance(raw_identity_profile, dict):
        for key in ("autonomy_level", "autonomy", "mode"):
            if _is_fully_autonomous_choice(raw_identity_profile.get(key)):
                return False
    return True


def _apply_user_profile(
    auth: AuthContext,
    profile: BoardOnboardingUserProfile | None,
) -> bool:
    if auth.user is None or profile is None:
        return False

    changed = False
    if profile.preferred_name is not None:
        auth.user.preferred_name = profile.preferred_name
        changed = True
    if profile.pronouns is not None:
        auth.user.pronouns = profile.pronouns
        changed = True
    if profile.timezone is not None:
        auth.user.timezone = profile.timezone
        changed = True
    if profile.notes is not None:
        auth.user.notes = profile.notes
        changed = True
    if profile.context is not None:
        auth.user.context = profile.context
        changed = True
    return changed


def _lead_agent_options(
    lead_agent: BoardOnboardingLeadAgentDraft | None,
) -> LeadAgentOptions:
    if lead_agent is None:
        return LeadAgentOptions(action="provision")

    lead_identity_profile: dict[str, str] = {}
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

    return LeadAgentOptions(
        agent_name=lead_agent.name,
        identity_profile=lead_identity_profile or None,
        action="provision",
    )


@router.get("", response_model=BoardOnboardingRead)
async def get_onboarding(
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingSession:
    """Get the latest onboarding session for a board."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return onboarding


@router.post("/start", response_model=BoardOnboardingRead)
async def start_onboarding(
    _payload: BoardOnboardingStart,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingSession:
    """Start onboarding and send instructions to the gateway agent."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .filter(col(BoardOnboardingSession.status) == "active")
        .first(session)
    )
    if onboarding:
        last_user_content: str | None = None
        messages = onboarding.messages or []
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, dict):
                last_role = last_message.get("role")
                content = last_message.get("content")
                if last_role == "user" and isinstance(content, str) and content:
                    last_user_content = content

        if last_user_content:
            # Retrigger the agent when the session is waiting on a response.
            dispatcher = BoardOnboardingMessagingService(session)
            await dispatcher.dispatch_answer(
                board=board,
                onboarding=onboarding,
                answer_text=last_user_content,
                correlation_id=f"onboarding.resume:{board.id}:{onboarding.id}",
            )
            onboarding.updated_at = utcnow()
            session.add(onboarding)
            await session.commit()
            await session.refresh(onboarding)
        return onboarding

    dispatcher = BoardOnboardingMessagingService(session)
    base_url = settings.base_url or "http://localhost:8000"
    prompt = (
        "BOARD ONBOARDING REQUEST\n\n"
        f"Board Name: {board.name}\n"
        f"Board Description: {board.description or '(not provided)'}\n"
        "You are the gateway agent. Ask the user 6-10 focused questions total:\n"
        "- 3-6 questions to clarify the board goal.\n"
        "- 1 question to choose a unique name for the board lead agent "
        "(first-name style).\n"
        "- 2-4 questions to capture the user's preferences for how the board "
        "lead should work\n"
        "  (communication style, autonomy, update cadence, and output formatting).\n"
        '- Always include a final question (and only once): "Anything else we '
        'should know?"\n'
        "  (constraints, context, preferences). This MUST be the last question.\n"
        '  Provide an option like "Yes (I\'ll type it)" so they can enter free-text.\n'
        "  Do NOT ask for additional context on earlier questions.\n"
        "  Only include a free-text option on earlier questions if a typed "
        "answer is necessary;\n"
        '  when you do, make the option label include "I\'ll type it" '
        '(e.g., "Other (I\'ll type it)").\n'
        '- If the user sends an "Additional context" message later, incorporate '
        "it and resend status=complete\n"
        "  to update the draft (until the user confirms).\n"
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
        '-d \'{"question":"...","options":[{"id":"1","label":"..."},'
        '{"id":"2","label":"..."}]}\'\n'
        "COMPLETION example (send JSON body exactly as shown):\n"
        f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding" '
        '-H "X-Agent-Token: $AUTH_TOKEN" '
        '-H "Content-Type: application/json" '
        '-d \'{"status":"complete","board_type":"goal","objective":"...",'
        '"success_metrics":{"metric":"...","target":"..."},'
        '"target_date":"YYYY-MM-DD",'
        '"user_profile":{"preferred_name":"...","pronouns":"...",'
        '"timezone":"...","notes":"...","context":"..."},'
        '"lead_agent":{"name":"Ava","identity_profile":{"role":"Board Lead",'
        '"communication_style":"direct, concise, practical","emoji":":gear:"},'
        '"autonomy_level":"balanced","verbosity":"concise",'
        '"output_format":"bullets","update_cadence":"daily",'
        '"custom_instructions":"..."}}\'\n'
        "ENUMS:\n"
        "- board_type: goal | general\n"
        "- lead_agent.autonomy_level: ask_first | balanced | autonomous\n"
        "- lead_agent.verbosity: concise | balanced | detailed\n"
        "- lead_agent.output_format: bullets | mixed | narrative\n"
        "- lead_agent.update_cadence: asap | hourly | daily | weekly\n"
        "QUESTION FORMAT (one question per response, no arrays, no markdown, "
        "no extra text):\n"
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}]}\n'
        "Do NOT wrap questions in a list. Do NOT add commentary.\n"
        "When you have enough info, send one final response with status=complete.\n"
        "The completion payload must include board_type. If board_type=goal, "
        "include objective + success_metrics.\n"
        "Also include user_profile + lead_agent to configure the board lead's "
        "working style.\n"
    )

    session_key = await dispatcher.dispatch_start_prompt(
        board=board,
        prompt=prompt,
        correlation_id=f"onboarding.start:{board.id}",
    )

    onboarding = BoardOnboardingSession(
        board_id=board.id,
        session_key=session_key,
        status="active",
        messages=[
            {"role": "user", "content": prompt, "timestamp": utcnow().isoformat()},
        ],
    )
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/answer", response_model=BoardOnboardingRead)
async def answer_onboarding(
    payload: BoardOnboardingAnswer,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingSession:
    """Send a user onboarding answer to the gateway agent."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    dispatcher = BoardOnboardingMessagingService(session)
    answer_text = payload.answer
    if payload.other_text:
        answer_text = f"{payload.answer}: {payload.other_text}"

    messages = list(onboarding.messages or [])
    messages.append(
        {"role": "user", "content": answer_text, "timestamp": utcnow().isoformat()},
    )

    await dispatcher.dispatch_answer(
        board=board,
        onboarding=onboarding,
        answer_text=answer_text,
        correlation_id=f"onboarding.answer:{board.id}:{onboarding.id}",
    )

    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/agent", response_model=BoardOnboardingRead)
async def agent_onboarding_update(
    payload: BoardOnboardingAgentUpdate,
    board: Board = BOARD_OR_404_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BoardOnboardingSession:
    """Store onboarding updates submitted by the gateway agent."""
    if actor.actor_type != "agent" or actor.agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    agent = actor.agent
    OpenClawAuthorizationPolicy.require_gateway_scoped_actor(actor_agent=agent)

    gateway = await get_gateway_for_board(session, board)
    if gateway is not None:
        OpenClawAuthorizationPolicy.require_gateway_main_actor_binding(
            actor_agent=agent,
            gateway=gateway,
        )

    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
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
        messages.append(
            {"role": "assistant", "content": payload_text, "timestamp": now},
        )
    else:
        messages.append(
            {"role": "assistant", "content": payload_text, "timestamp": now},
        )

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
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = ADMIN_AUTH_DEP,
) -> Board:
    """Confirm onboarding results and provision the board lead agent."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    board.board_type = payload.board_type
    board.objective = payload.objective
    board.success_metrics = payload.success_metrics
    board.target_date = payload.target_date
    board.goal_confirmed = True
    board.goal_source = "lead_agent_onboarding"
    board.require_approval_for_done = _require_approval_for_done_from_draft(
        onboarding.draft_goal,
    )

    onboarding.status = "confirmed"
    onboarding.updated_at = utcnow()

    user_profile = _parse_draft_user_profile(onboarding.draft_goal)
    if _apply_user_profile(auth, user_profile) and auth.user is not None:
        session.add(auth.user)

    lead_agent = _parse_draft_lead_agent(onboarding.draft_goal)
    lead_options = _lead_agent_options(lead_agent)

    gateway, config = await GatewayDispatchService(session).require_gateway_config_for_board(board)
    session.add(board)
    session.add(onboarding)
    await session.commit()
    await session.refresh(board)
    await OpenClawProvisioningService(session).ensure_board_lead_agent(
        request=LeadAgentRequest(
            board=board,
            gateway=gateway,
            config=config,
            user=auth.user,
            options=lead_options,
        ),
    )
    return board
