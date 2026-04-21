# ruff: noqa: INP001
"""Unit tests for the Phase III OperatorDecision model (plan §I3).

Scope: the column contract + constraint guards. Compatibility bridge
(is_blocked derivation ORing in open decisions) + endpoints land in
follow-up commits.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from app.models.operator_decisions import (
    OperatorDecision,
    OperatorDecisionTaskLink,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


def _decision(**overrides: object) -> OperatorDecision:
    defaults: dict[str, object] = {
        "board_id": uuid4(),
        "question": "Should the rollout continue?",
    }
    defaults.update(overrides)
    return OperatorDecision(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_canonical_statuses_round_trip(db_session: AsyncSession) -> None:
    for status in ("pending", "resolved", "cancelled"):
        db_session.add(_decision(status=status))
    await db_session.commit()


@pytest.mark.asyncio
async def test_unknown_status_rejected(db_session: AsyncSession) -> None:
    db_session.add(_decision(status="approved"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_default_status_is_pending(db_session: AsyncSession) -> None:
    decision = _decision()
    db_session.add(decision)
    await db_session.commit()
    assert decision.status == "pending"


@pytest.mark.asyncio
async def test_task_link_unique_per_decision_task_pair(
    db_session: AsyncSession,
) -> None:
    """A decision cannot link the same task twice — duplicates would
    inflate the bridge's 'does any decision block this task?' count."""

    decision = _decision()
    db_session.add(decision)
    await db_session.commit()
    task_id = uuid4()
    db_session.add(
        OperatorDecisionTaskLink(decision_id=decision.id, task_id=task_id),
    )
    await db_session.commit()
    db_session.add(
        OperatorDecisionTaskLink(decision_id=decision.id, task_id=task_id),
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
