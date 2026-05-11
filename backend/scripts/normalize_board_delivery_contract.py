"""Apply delivery-contract normalization patches to board tasks from a manifest."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


from app.api.deps import ActorContext  # noqa: E402
from app.api.tasks import (  # noqa: E402
    _apply_admin_task_rules,
    _finalize_updated_task,
    _TaskUpdateInput,
)
from app.db.session import async_session_maker  # noqa: E402
from app.models.tasks import Task  # noqa: E402
from app.models.users import User  # noqa: E402
from app.schemas.tasks import TaskUpdate  # noqa: E402


class NormalizationTaskPatch(BaseModel):
    task_id: UUID
    title: str | None = None
    update: TaskUpdate

    @model_validator(mode="after")
    def validate_update_fields(self) -> "NormalizationTaskPatch":
        field_names = set(self.update.model_fields_set)
        if field_names and field_names.issubset({"comment"}):
            raise ValueError("normalization patch must include at least one non-comment task field")
        if not field_names:
            raise ValueError("normalization patch must include at least one non-comment task field")
        return self


class BoardDeliveryContractManifest(BaseModel):
    board_id: UUID
    actor_user_id: UUID | None = None
    tasks: list[NormalizationTaskPatch] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tasks(self) -> "BoardDeliveryContractManifest":
        if not self.tasks:
            raise ValueError("manifest must include at least one task patch")
        return self


def _update_field_names(update: TaskUpdate) -> list[str]:
    return sorted(field for field in update.model_fields_set if field != "comment")


def summarize_patch(patch: NormalizationTaskPatch) -> str:
    label = patch.title or str(patch.task_id)
    fields = ", ".join(_update_field_names(patch.update))
    return f"{label}: {fields}"


def render_dry_run_lines(manifest: BoardDeliveryContractManifest) -> list[str]:
    return [f"DRY RUN {summarize_patch(patch)}" for patch in manifest.tasks]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize task delivery-contract metadata from a manifest.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to a JSON manifest describing task normalization patches.",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="Optional admin user UUID to attribute updates to. Required unless --dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned task patches without writing changes.",
    )
    return parser.parse_args()


def _load_manifest(path: Path) -> BoardDeliveryContractManifest:
    return BoardDeliveryContractManifest.model_validate(json.loads(path.read_text()))


async def _resolve_actor_user(
    *,
    user_id: UUID | None,
) -> User:
    if user_id is None:
        raise SystemExit(
            "--user-id (or manifest actor_user_id) is required unless --dry-run is used"
        )
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise SystemExit(f"User not found: {user_id}")
        return user


async def _apply_manifest(
    manifest: BoardDeliveryContractManifest,
    *,
    dry_run: bool,
    actor_user_id: UUID | None,
) -> int:
    if dry_run:
        for line in render_dry_run_lines(manifest):
            print(line)
        return 0

    actor_user: User | None = None
    actor_user = await _resolve_actor_user(user_id=actor_user_id or manifest.actor_user_id)
    async with async_session_maker() as session:
        for patch in manifest.tasks:
            task = await session.get(Task, patch.task_id)
            if task is None:
                raise SystemExit(f"Task not found: {patch.task_id}")
            if task.board_id != manifest.board_id:
                raise SystemExit(
                    f"Task {patch.task_id} belongs to board {task.board_id}, expected {manifest.board_id}"
                )
            if patch.title is not None and task.title != patch.title:
                raise SystemExit(
                    f"Task {patch.task_id} title mismatch: expected {patch.title!r}, found {task.title!r}"
                )
            update_model = patch.update
            updates = update_model.model_dump(exclude_unset=True)
            comment = update_model.comment if "comment" in update_model.model_fields_set else None
            depends_on_task_ids = (
                update_model.depends_on_task_ids
                if "depends_on_task_ids" in update_model.model_fields_set
                else None
            )
            tag_ids = update_model.tag_ids if "tag_ids" in update_model.model_fields_set else None
            custom_field_values = (
                update_model.custom_field_values
                if "custom_field_values" in update_model.model_fields_set
                else None
            )
            custom_field_values_set = "custom_field_values" in update_model.model_fields_set
            updates.pop("comment", None)
            updates.pop("depends_on_task_ids", None)
            updates.pop("tag_ids", None)
            updates.pop("custom_field_values", None)
            requested_status = (
                update_model.status if "status" in update_model.model_fields_set else None
            )

            update = _TaskUpdateInput(
                task=task,
                actor=ActorContext(actor_type="user", user=actor_user),
                board_id=manifest.board_id,
                previous_status=task.status,
                previous_assigned=task.assigned_agent_id,
                previous_in_progress_at=task.in_progress_at,
                previous_review_packet_type=task.review_packet_type,
                status_requested=(requested_status is not None and requested_status != task.status),
                updates=updates,
                comment=comment,
                depends_on_task_ids=depends_on_task_ids,
                tag_ids=tag_ids,
                custom_field_values=custom_field_values or {},
                custom_field_values_set=custom_field_values_set,
            )
            await _apply_admin_task_rules(session, update=update)
            result = await _finalize_updated_task(session, update=update)
            print(f"UPDATED {result.id} {result.title}")

    return 0


async def _run() -> int:
    args = _parse_args()
    manifest = _load_manifest(args.manifest)
    actor_user_id = UUID(args.user_id) if args.user_id else None
    return await _apply_manifest(
        manifest,
        dry_run=bool(args.dry_run),
        actor_user_id=actor_user_id,
    )


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
