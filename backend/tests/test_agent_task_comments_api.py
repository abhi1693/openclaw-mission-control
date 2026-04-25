# ruff: noqa: INP001

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi_pagination import add_pagination
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.api.agent import router as agent_router
from app.api.deps import ActorContext, get_board_for_actor_read, get_board_or_404
from app.core.agent_tokens import hash_agent_token
from app.db.session import get_session
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.pagination import DefaultLimitOffsetPage


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _build_test_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(agent_router)
    app.include_router(api_v1)
    add_pagination(app)

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
    app.dependency_overrides[get_board_for_actor_read] = _override_get_board_or_404
    return app


async def _seed_agent_task(
    session: AsyncSession,
    *,
    with_comment: bool = False,
    agent_name: str = "Worker Agent",
    agent_identity_profile: dict[str, Any] | None = None,
) -> tuple[str, Board, Agent, Task]:
    token = "test-agent-token-" + uuid4().hex
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    agent_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="https://gateway.example.local",
            workspace_root="/tmp/workspace",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="Board",
        slug="board",
        comment_signal_filter="off",
    )
    session.add(board)
    agent = Agent(
        id=agent_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name=agent_name,
        status="online",
        openclaw_session_id="agent:worker:session",
        agent_token_hash=hash_agent_token(token),
        identity_profile=agent_identity_profile,
    )
    session.add(agent)
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Live task",
        description="",
        status="in_progress",
        assigned_agent_id=agent_id,
    )
    session.add(task)
    if with_comment:
        session.add(
            ActivityEvent(
                event_type="task.comment",
                message="Existing progress update",
                task_id=task_id,
                board_id=board_id,
                agent_id=agent_id,
            ),
        )
    await session.commit()
    return token, board, agent, task


@pytest.mark.asyncio
async def test_agent_task_comments_passes_board_actor_and_include_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)
    seen: dict[str, Any] = {}

    async with session_maker() as session:
        token, board, agent, task = await _seed_agent_task(session)

    async def _fake_list_task_comments(
        *,
        task: Task,
        session: AsyncSession,
        board: Board,
        actor: ActorContext,
        include_flagged: bool,
    ) -> Any:
        seen["task_id"] = task.id
        seen["board_filter"] = getattr(board, "comment_signal_filter", None)
        seen["actor_agent_id"] = actor.agent.id if actor.agent else None
        seen["include_flagged"] = include_flagged
        return DefaultLimitOffsetPage[Any].model_validate(
            {"items": [], "total": 0, "limit": 200, "offset": 0},
        )

    monkeypatch.setattr(tasks_api, "list_task_comments", _fake_list_task_comments)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
            )

        assert response.status_code == 200
        assert seen == {
            "task_id": task.id,
            "board_filter": "off",
            "actor_agent_id": agent.id,
            "include_flagged": False,
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_can_fetch_comments_for_live_task() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, _agent, task = await _seed_agent_task(session, with_comment=True)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["message"] == "Existing progress update"
        assert body["items"][0]["task_id"] == str(task.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_task_comments_missing_task_stays_404() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, _agent, _task = await _seed_agent_task(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/agent/boards/{board.id}/tasks/{uuid4()}/comments",
                headers={"X-Agent-Token": token},
            )

        assert response.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_qa_validation_comment_must_start_with_verdict() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, _agent, task = await _seed_agent_task(
            session,
            agent_name="QA-E2E",
            agent_identity_profile={"validation_flow": "qa_validation"},
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
                json={"message": "QA-E2E validation\n\nFAIL - missing switcher"},
            )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "qa_verdict_prefix_required"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_qa_validation_comment_accepts_verdict_first() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, _agent, task = await _seed_agent_task(
            session,
            agent_name="QA-E2E",
            agent_identity_profile={"validation_flow": "qa_validation"},
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
                json={
                    "message": (
                        "VERDICT: FAIL\n"
                        "Blocking ACs: org switcher\n"
                        "Suggested routing: lead move to rework for PF/org switcher"
                    ),
                },
            )

        assert response.status_code == 200
        assert response.json()["message"].startswith("VERDICT: FAIL")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_qa_validation_pass_rejects_bundle_grep_as_rendered_evidence() -> None:
    agent = Agent(name="QA-E2E", identity_profile={"validation_flow": "qa_validation"})

    with pytest.raises(HTTPException) as exc:
        tasks_api._require_rendered_live_pass_has_browser_evidence(
            "VERDICT: PASS\nLive evidence: feTurbulence found in deployed bundle.",
            ActorContext(actor_type="agent", agent=agent),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "rendered_live_evidence_required"


@pytest.mark.asyncio
async def test_qa_validation_pass_accepts_browser_rendered_evidence() -> None:
    agent = Agent(name="QA-E2E", identity_profile={"validation_flow": "qa_validation"})

    tasks_api._require_rendered_live_pass_has_browser_evidence(
        (
            "VERDICT: PASS\n"
            "Browser snapshot: hero overlay div present on the live target.\n"
            "getComputedStyle(backgroundImage) contains encoded SVG marker; screenshot captured."
        ),
        ActorContext(actor_type="agent", agent=agent),
    )


@pytest.mark.asyncio
async def test_review_only_pass_rejects_bundle_grep_as_rendered_evidence() -> None:
    agent = Agent(name="Architect", identity_profile={"dev_acp_flow": "review_only"})

    with pytest.raises(HTTPException) as exc:
        tasks_api._require_rendered_live_pass_has_browser_evidence(
            "VERDICT: PASS\nRendered/live evidence: grep found feTurbulence in deployed bundle.",
            ActorContext(actor_type="agent", agent=agent),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "rendered_live_evidence_required"


@pytest.mark.asyncio
async def test_review_only_fail_allows_bundle_grep_diagnostic() -> None:
    agent = Agent(name="Architect", identity_profile={"dev_acp_flow": "review_only"})

    tasks_api._require_rendered_live_pass_has_browser_evidence(
        "VERDICT: FAIL\nDiagnostic: bundle contains GeometricPattern but browser snapshot shows no pattern wrapper.",
        ActorContext(actor_type="agent", agent=agent),
    )


@pytest.mark.parametrize(
    "message",
    [
        "Architect FAIL accepted. Routing to PF for rework. @Programmer-Frontend",
        "Architect FAIL accepted. return to PF rework",
        "Review failed; move back to rework.",
    ],
)
@pytest.mark.asyncio
async def test_lead_rework_routing_comment_requires_status_transition(message: str) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, agent, task = await _seed_agent_task(
            session,
            agent_name="Supervisor",
        )
        agent.is_board_lead = True
        task.status = "review"
        task.assigned_agent_id = agent.id
        await session.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
                json={"message": message},
            )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "rework_routing_comment_requires_status_transition"
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "message",
    [
        "Do not move to rework; Architect is still reviewing.",
        "I reviewed the rework plan; move the button left.",
    ],
)
@pytest.mark.asyncio
async def test_lead_non_routing_rework_comment_is_allowed(message: str) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, agent, task = await _seed_agent_task(
            session,
            agent_name="Supervisor",
        )
        agent.is_board_lead = True
        task.status = "review"
        task.assigned_agent_id = agent.id
        await session.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
                json={"message": message},
            )

        assert response.status_code == 200
        assert response.json()["message"] == message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_comment_guard_allows_rework_routing_comment_after_status_is_rework() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _token, _board, agent, task = await _seed_agent_task(
                session,
                agent_name="Supervisor",
            )
            agent.is_board_lead = True
            task.status = "rework"
            task.assigned_agent_id = agent.id
            session.add(
                ActivityEvent(
                    event_type="task.comment",
                    message="@Supervisor please route this rework.",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=None,
                )
            )
            await session.commit()

            event = await tasks_api.create_task_comment(
                payload=tasks_api.TaskCommentCreate(
                    message="Routed to PF for rework. @Programmer-Frontend",
                ),
                task=task,
                session=session,
                actor=ActorContext(actor_type="agent", agent=agent),
            )

            assert event.message == "Routed to PF for rework. @Programmer-Frontend"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_qa_comment_does_not_require_verdict_prefix() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, _agent, task = await _seed_agent_task(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
                headers={"X-Agent-Token": token},
                json={"message": "Worker update\n\nEvidence: tests passed"},
            )

        assert response.status_code == 200
        assert response.json()["message"].startswith("Worker update")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_qa_validation_patch_comment_must_start_with_verdict() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(session_maker)

    async with session_maker() as session:
        token, board, _agent, task = await _seed_agent_task(
            session,
            agent_name="QA-E2E",
            agent_identity_profile={"validation_flow": "qa_validation"},
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/agent/boards/{board.id}/tasks/{task.id}",
                headers={"X-Agent-Token": token},
                json={"comment": "QA-E2E validation\n\nFAIL - missing switcher"},
            )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "qa_verdict_prefix_required"
    finally:
        await engine.dispose()
