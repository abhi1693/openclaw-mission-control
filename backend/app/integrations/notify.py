from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from sqlmodel import Session, select

from app.integrations.openclaw import OpenClawClient
from app.models.org import Employee
from app.models.projects import ProjectMember
from app.models.work import Task, TaskComment

logger = logging.getLogger("app.notify")


@dataclass(frozen=True)
class NotifyContext:
    event: str  # task.created | task.updated | task.assigned | comment.created | status.changed
    actor_employee_id: int
    task: Task
    comment: TaskComment | None = None
    changed_fields: dict | None = None


def _employees_with_session_keys(session: Session, employee_ids: Iterable[int]) -> list[Employee]:
    ids = sorted({i for i in employee_ids if i is not None})
    if not ids:
        return []

    emps = session.exec(select(Employee).where(Employee.id.in_(ids))).all()
    out: list[Employee] = []
    for e in emps:
        if not getattr(e, "notify_enabled", True):
            continue
        if getattr(e, "openclaw_session_key", None):
            out.append(e)
    return out


def _project_pm_employee_ids(session: Session, project_id: int) -> set[int]:
    # Generic, data-driven: PMs are determined by project_members.role.
    pms = session.exec(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
    pm_ids: set[int] = set()
    for m in pms:
        role = (m.role or "").lower()
        if role in {"pm", "product", "product_manager", "manager"}:
            pm_ids.add(m.employee_id)
    return pm_ids


def resolve_recipients(session: Session, ctx: NotifyContext) -> set[int]:
    t = ctx.task
    recipients: set[int] = set()

    if ctx.event == "task.created":
        # notify assignee + PMs
        if t.assignee_employee_id:
            recipients.add(t.assignee_employee_id)
        recipients |= _project_pm_employee_ids(session, t.project_id)

    elif ctx.event == "task.assigned":
        if t.assignee_employee_id:
            recipients.add(t.assignee_employee_id)
        recipients |= _project_pm_employee_ids(session, t.project_id)

    elif ctx.event == "comment.created":
        # notify assignee + reviewer + PMs, excluding author
        if t.assignee_employee_id:
            recipients.add(t.assignee_employee_id)
        if t.reviewer_employee_id:
            recipients.add(t.reviewer_employee_id)
        recipients |= _project_pm_employee_ids(session, t.project_id)
        if ctx.comment and ctx.comment.author_employee_id:
            recipients.discard(ctx.comment.author_employee_id)

    elif ctx.event == "status.changed":
        new_status = (getattr(t, "status", None) or "").lower()
        if new_status in {"review", "ready_for_review"} and t.reviewer_employee_id:
            recipients.add(t.reviewer_employee_id)
        recipients |= _project_pm_employee_ids(session, t.project_id)

    elif ctx.event == "task.updated":
        # conservative: PMs only
        recipients |= _project_pm_employee_ids(session, t.project_id)

    recipients.discard(ctx.actor_employee_id)
    return recipients


def build_message(ctx: NotifyContext, recipient: Employee) -> str:
    t = ctx.task
    base = f"Task #{t.id}: {t.title}" if t.id is not None else f"Task: {t.title}"

    # Agent-specific dispatch instructions. These notifications should result in the agent
    # taking concrete actions in Mission Control, not just acknowledging.
    if ctx.event in {"task.created", "task.assigned"} and recipient.employee_type == "agent":
        desc = (t.description or "").strip()
        if len(desc) > 500:
            desc = desc[:497] + "..."
        desc_block = f"\n\nDescription:\n{desc}" if desc else ""

        # Keep this deterministic: agents already have base URL + header guidance in their prompt.
        base_url = __import__(
            "app.core.urls", fromlist=["public_api_base_url"]
        ).public_api_base_url()

        return (
            f"{base}\n\n"
            f"Set BASE={base_url}\n\n"
            "You are the assignee. Start NOW (use the exec tool to run these curl commands):\n"
            f"1) curl -sS -X PATCH $BASE/tasks/{t.id} -H 'X-Actor-Employee-Id: {recipient.id}' "
            "-H 'Content-Type: application/json' -d '{\"status\":\"in_progress\"}'\n"
            f"2) curl -sS -X POST $BASE/task-comments -H 'X-Actor-Employee-Id: {recipient.id}' "
            f'-H \'Content-Type: application/json\' -d \'{{"task_id":{t.id},"body":"Plan: ... Next: ..."}}\'\n'
            "3) Do the work\n"
            f"4) Post progress updates via POST $BASE/task-comments (same headers)\n"
            f"5) When complete: curl -sS -X PATCH $BASE/tasks/{t.id} -H 'X-Actor-Employee-Id: {recipient.id}' "
            "-H 'Content-Type: application/json' -d '{\"status\":\"done\"}' and post a final summary comment"
            f"-H 'X-Actor-Employee-Id: {recipient.id}' "
            "-H 'Content-Type: application/json' "
            '-d \'{"status":"done"}\' and post a final summary comment'
            f"{desc_block}"
        )

    if ctx.event == "task.assigned":
        return (
            f"Assigned: {base}.\n"
            "Work ONE task only; update Mission Control with a comment when you make progress."
        )

    if ctx.event == "comment.created":
        snippet = ""
        if ctx.comment and ctx.comment.body:
            snippet = ctx.comment.body.strip().replace("\n", " ")
            if len(snippet) > 180:
                snippet = snippet[:177] + "..."
            snippet = f"\nComment: {snippet}"
        return (
            f"New comment on {base}.{snippet}\nWork ONE task only; reply/update in Mission Control."
        )

    if ctx.event == "status.changed":
        return (
            f"Status changed on {base} → {t.status}.\n"
            "Work ONE task only; update Mission Control with next step."
        )

    if ctx.event == "task.created":
        return (
            f"New task created: {base}.\n"
            "Work ONE task only; add acceptance criteria / next step in Mission Control."
        )

    return f"Update on {base}.\nWork ONE task only; update Mission Control."


def notify_openclaw(session: Session, ctx: NotifyContext) -> None:
    client = OpenClawClient.from_env()
    logger.info(
        "notify_openclaw: start",
        extra={
            "event": ctx.event,
            "task_id": getattr(ctx.task, "id", None),
            "actor": ctx.actor_employee_id,
        },
    )
    if client is None:
        logger.warning("notify_openclaw: skipped (missing OpenClaw env)")
        return

    recipient_ids = resolve_recipients(session, ctx)
    logger.info(
        "notify_openclaw: recipients resolved", extra={"recipient_ids": sorted(recipient_ids)}
    )
    recipients = _employees_with_session_keys(session, recipient_ids)
    if not recipients:
        logger.info("notify_openclaw: no recipients with session keys")
        return

    for e in recipients:
        logger.info(
            "notify_openclaw: sending",
            extra={
                "to_employee_id": getattr(e, "id", None),
                "session_key": getattr(e, "openclaw_session_key", None),
                "event": ctx.event,
            },
        )
        sk = getattr(e, "openclaw_session_key", None)
        if not sk:
            continue

        message = build_message(ctx, recipient=e)
        try:
            client.tools_invoke(
                "sessions_send",
                {"sessionKey": sk, "message": message},
                timeout_s=15.0,
            )
        except Exception:
            logger.exception("notify_openclaw: sessions_send failed")
            # best-effort; never break Mission Control writes
            continue
