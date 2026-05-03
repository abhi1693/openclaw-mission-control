"""Handler-level integration test for slice-5 gateway-session wiring.

The selector contract (``select_lead_next_action`` accepting
``gateway_session_by_agent_id``) and the persistence contract
(``SessionStateRepo``) are unit-tested in isolation. The glue lives in
``app/api/agent.py:get_lead_next_action`` — load Agent rows for in-progress
task assignees, derive lookup ids via ``projection_lookup_id``, query the
projection, populate the selector kwarg. This file exercises that glue
end-to-end against sqlite so a regression in the wiring (e.g. wrong
prefix, missing JOIN, or skipped repo call) shows up as a red test, not
as silent absence of ``gateway_session`` from production responses.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.agent import get_lead_next_action
from app.core.agent_auth import AgentAuthContext
from app.core.time import utcnow
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.lead_next_action import IN_PROGRESS_PIPELINE_NUDGE_GRACE
from app.services.mc_gateway_subscriber.session_state_projector import SessionState
from app.services.mc_gateway_subscriber.session_state_repo import SessionStateRepo


def _stale_in_progress_at():
    return utcnow() - IN_PROGRESS_PIPELINE_NUDGE_GRACE - timedelta(minutes=5)


@pytest.mark.asyncio
async def test_get_lead_next_action_populates_gateway_session_from_repo(
    sqlite_session: AsyncSession,
) -> None:
    """End-to-end wiring: an in-progress task whose assignee has a
    gateway_session_state row → the response's
    ``details.gateway_session`` carries the projected fields. Pins the
    UUID → openclaw_session_id → projection_lookup_id → repo lookup
    chain so a regression in any link surfaces immediately."""
    org = Organization(name="org")
    sqlite_session.add(org)
    await sqlite_session.flush()
    gateway = Gateway(
        organization_id=org.id,
        name="gw",
        url="ws://x",
        workspace_root="/tmp",
    )
    sqlite_session.add(gateway)
    await sqlite_session.flush()
    board = Board(organization_id=org.id, name="board", slug="board")
    sqlite_session.add(board)
    await sqlite_session.flush()

    # Lead agent — must have is_board_lead=True so _require_board_lead
    # succeeds. The lead itself isn't an in_progress assignee.
    lead = Agent(
        gateway_id=gateway.id,
        board_id=board.id,
        name="Lead",
        openclaw_session_id=f"agent:lead-{board.id}:main",
        is_board_lead=True,
    )
    sqlite_session.add(lead)

    # Worker agent — assigned to a stale in-progress task. The handler
    # must derive its gateway lookup id from openclaw_session_id, not
    # from a hardcoded mc-<uuid> string.
    worker_uuid = uuid4()
    worker = Agent(
        id=worker_uuid,
        gateway_id=gateway.id,
        board_id=board.id,
        name="Worker",
        openclaw_session_id=f"agent:mc-{worker_uuid}:main",
    )
    sqlite_session.add(worker)
    await sqlite_session.flush()

    task = Task(
        board_id=board.id,
        title="Stale work",
        status="in_progress",
        assigned_agent_id=worker.id,
        in_progress_at=_stale_in_progress_at(),
    )
    sqlite_session.add(task)

    await SessionStateRepo.upsert(
        sqlite_session,
        SessionState(
            agent_id=f"mc-{worker_uuid}",
            session_label="main",
            session_id="sess-abc",
            last_phase="tool",
            last_message_seq=42,
            last_changed_at_ms=1_777_900_000_000,
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            channel="webchat",
            aborted_last_run=False,
        ),
    )
    await sqlite_session.commit()

    response = await get_lead_next_action(
        board=board,
        session=sqlite_session,
        agent_ctx=AgentAuthContext(actor_type="agent", agent=lead),
    )

    assert response.action == "inspect_stale_in_progress"
    assert response.reason_code == "in_progress_work_needs_health_check"
    assert response.task_id == task.id
    gateway_session = response.details["gateway_session"]
    assert gateway_session is not None
    assert gateway_session["session_id"] == "sess-abc"
    assert gateway_session["last_phase"] == "tool"
    assert gateway_session["last_changed_at_ms"] == 1_777_900_000_000
    assert gateway_session["aborted_last_run"] is False


@pytest.mark.asyncio
async def test_get_lead_next_action_marks_gateway_session_null_for_unprovisioned_assignee(
    sqlite_session: AsyncSession,
) -> None:
    """If the assigned worker has no ``openclaw_session_id`` (newly
    provisioned, never bootstrapped on the gateway), the handler must
    skip them in the lookup and the selector returns
    ``gateway_session: None`` — explicit no-signal marker, not a
    silently-omitted key. Lead playbook depends on this distinction."""
    org = Organization(name="org")
    sqlite_session.add(org)
    await sqlite_session.flush()
    gateway = Gateway(
        organization_id=org.id, name="gw", url="ws://x", workspace_root="/tmp"
    )
    sqlite_session.add(gateway)
    await sqlite_session.flush()
    board = Board(organization_id=org.id, name="b", slug="b")
    sqlite_session.add(board)
    await sqlite_session.flush()

    lead = Agent(
        gateway_id=gateway.id,
        board_id=board.id,
        name="Lead",
        openclaw_session_id=f"agent:lead-{board.id}:main",
        is_board_lead=True,
    )
    sqlite_session.add(lead)
    worker = Agent(
        gateway_id=gateway.id,
        board_id=board.id,
        name="Worker-Unprovisioned",
        openclaw_session_id=None,  # KEY: not yet bootstrapped on gateway
    )
    sqlite_session.add(worker)
    await sqlite_session.flush()

    task = Task(
        board_id=board.id,
        title="Stale",
        status="in_progress",
        assigned_agent_id=worker.id,
        in_progress_at=_stale_in_progress_at(),
    )
    sqlite_session.add(task)
    await sqlite_session.commit()

    response = await get_lead_next_action(
        board=board,
        session=sqlite_session,
        agent_ctx=AgentAuthContext(actor_type="agent", agent=lead),
    )

    assert response.action == "inspect_stale_in_progress"
    assert response.details["gateway_session"] is None, (
        "unprovisioned assignee must produce explicit None, not a missing key "
        "(lead playbook branches on this)"
    )
