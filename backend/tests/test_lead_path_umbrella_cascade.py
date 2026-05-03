# ruff: noqa: INP001
"""Lead-path PATCH must trigger umbrella cascade.

Codex 2026-05-03 review caught: ``update_task`` returns directly from
``_apply_lead_task_update`` for board leads (``tasks.py:3382-3383``),
bypassing ``_finalize_updated_task`` where the umbrella-cascade hook
lives. So when Supervisor (board lead) closes the last child of a
retired umbrella, the parent stays in inbox forever — the exact bug
the cascade was supposed to fix.

Both the agent path (in ``_finalize_updated_task``) AND the lead path
(in ``_apply_lead_task_update``) must run the cascade hook for it to
actually catch all terminal transitions.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import tasks as tasks_api
from app.api.deps import ActorContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.tasks import TaskUpdate


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_lead_path_patch_to_done_triggers_umbrella_cascade() -> None:
    """Lead PATCHing the last child of a retired umbrella to ``done``
    must auto-cancel the parent."""
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            gateway_id = uuid4()
            lead_id = uuid4()
            parent_id = uuid4()
            child_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                    # Disable approval gate so lead PATCH review→done doesn't
                    # 409 on missing approval row; we're testing cascade, not
                    # the approval-gate path.
                    require_approval_for_done=False,
                ),
            )
            session.add(
                Agent(
                    id=lead_id,
                    name="Supervisor",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    is_board_lead=True,
                ),
            )
            # Parent: never executed coordination umbrella in inbox.
            session.add(
                Task(
                    id=parent_id,
                    board_id=board_id,
                    title="umbrella parent",
                    description="",
                    status="inbox",
                    review_packet_type="review_only",
                ),
            )
            # Child: in review (lead can transition review → done per
            # _lead_apply_status), assigned to the lead so the lead-path
            # rules accept the PATCH.
            session.add(
                Task(
                    id=child_id,
                    board_id=board_id,
                    title="last child",
                    description="",
                    status="review",
                    review_packet_type="review_only",
                    parent_task_id=parent_id,
                    assigned_agent_id=lead_id,
                ),
            )
            await session.commit()

            child = (await session.exec(select(Task).where(col(Task.id) == child_id))).first()
            assert child is not None
            lead = (await session.exec(select(Agent).where(col(Agent.id) == lead_id))).first()
            assert lead is not None

            updated = await tasks_api.update_task(
                payload=TaskUpdate(status="done"),
                task=child,
                session=session,
                actor=ActorContext(actor_type="agent", agent=lead),
            )
            assert updated.status == "done"

            # The cascade should have flipped the parent to cancelled.
            session.expire_all()
            parent = (
                await session.exec(select(Task).where(col(Task.id) == parent_id))
            ).first()
            assert parent is not None
            assert parent.status == "cancelled", (
                f"lead-path PATCH must cascade through to retired umbrella; "
                f"parent.status={parent.status}"
            )
            assert parent.cancelled_at is not None
    finally:
        await engine.dispose()
