"""One-shot backfill — advance review_only tasks stuck in inbox.

Uses the same admin update pipeline as
``scripts/normalize_board_delivery_contract.py`` so it produces the
normal ``task.status_changed`` activity event, runs lead-assignment
normalization, and is naturally idempotent (subsequent runs find 0
rows because the WHERE clause re-evaluates after the advance).

Usage::

    python -m scripts.backfill_review_only_inbox [--board-id UUID] [--dry-run]

The script picks (or creates) a system actor user named
``system-backfill@local``. The admin update pipeline routes that user
through ``_record_task_update_activity``, which records the
``task.status_changed`` event with ``agent_id=None`` (proving the
transition came from a user actor rather than an agent).

Audit caveat: ``_finalize_updated_task`` commits the task row first,
then issues separate commits for the comment + activity rows. A
process kill between those commits leaves the row advanced without
its activity event; a rerun skips it (idempotency by design — no
audit repair). This is fine for a one-shot operator-driven backfill;
do NOT wrap this script in a long-running service.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.api.deps import ActorContext
from app.api.tasks import (
    _TaskUpdateInput,
    _apply_admin_task_rules,
    _finalize_updated_task,
)
from app.db.session import async_session_maker
from app.models.tasks import Task
from app.models.users import User


_SYSTEM_USER_EMAIL = "system-backfill@local"
_SYSTEM_USER_CLERK_ID = "system-backfill"


async def _ensure_system_user(session: AsyncSession) -> User:
    """Create or find the system actor user used to attribute backfill events."""
    user = (
        await session.exec(select(User).where(User.email == _SYSTEM_USER_EMAIL))
    ).first()
    if user is None:
        user = User(
            clerk_user_id=_SYSTEM_USER_CLERK_ID,
            email=_SYSTEM_USER_EMAIL,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def backfill_async(
    session: AsyncSession,
    *,
    actor_user: User,
    dry_run: bool = False,
    board_id: UUID | None = None,
) -> list[UUID]:
    """Advance every ``review_only`` task currently in ``inbox`` to ``review``.

    Returns the list of task IDs reported. Under ``dry_run=True`` the
    list is what WOULD change (nothing committed). Under live mode the
    list is what actually changed.

    Mirrors ``scripts/normalize_board_delivery_contract.py:155-175``: we
    construct a ``_TaskUpdateInput`` and run it through
    ``_apply_admin_task_rules`` + ``_finalize_updated_task``. That
    ensures activity events fire (``task.status_changed``), lead
    assignment normalization runs (``_assign_review_task_to_lead``),
    and downstream review-time gates apply correctly. A naive
    ``task.status = 'review'; commit()`` would skip all of that.
    """
    stmt = select(Task).where(
        Task.review_packet_type == "review_only",
        Task.status == "inbox",
    )
    if board_id is not None:
        stmt = stmt.where(Task.board_id == board_id)
    rows = (await session.exec(stmt)).all()

    advanced: list[UUID] = []
    for task in rows:
        advanced.append(task.id)
        if dry_run:
            continue
        update = _TaskUpdateInput(
            task=task,
            actor=ActorContext(actor_type="user", user=actor_user),
            board_id=task.board_id,
            previous_status=task.status,
            previous_assigned=task.assigned_agent_id,
            previous_in_progress_at=task.in_progress_at,
            previous_review_packet_type=task.review_packet_type,
            status_requested=True,
            updates={"status": "review"},
            comment="Backfill: review_only tasks bypass inbox (2026-05-09)",
            depends_on_task_ids=None,
            tag_ids=None,
            custom_field_values={},
            custom_field_values_set=False,
        )
        await _apply_admin_task_rules(session, update=update)
        await _finalize_updated_task(session, update=update)
    return advanced


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Advance review_only tasks stuck in inbox to review.",
    )
    parser.add_argument("--board-id", type=UUID, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    async with async_session_maker() as session:
        actor = await _ensure_system_user(session)
        advanced = await backfill_async(
            session,
            actor_user=actor,
            dry_run=args.dry_run,
            board_id=args.board_id,
        )
    label = "WOULD ADVANCE" if args.dry_run else "ADVANCED"
    print(f"{label} {len(advanced)} review_only tasks: {advanced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
