"""Organization-level task custom field definition management."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import require_org_admin, require_org_member
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.task_custom_fields import (
    BoardTaskCustomField,
    TaskCustomFieldDefinition,
    TaskCustomFieldValue,
)
from app.schemas.common import OkResponse
from app.schemas.task_custom_fields import (
    TaskCustomFieldDefinitionCreate,
    TaskCustomFieldDefinitionRead,
    TaskCustomFieldDefinitionUpdate,
    validate_custom_field_definition,
)
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


router = APIRouter(prefix="/organizations/me/custom-fields", tags=["org-custom-fields"])
SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
ORG_ADMIN_DEP = Depends(require_org_admin)


def _to_definition_read_payload(
    *,
    definition: TaskCustomFieldDefinition,
    board_ids: list[UUID],
) -> TaskCustomFieldDefinitionRead:
    payload = TaskCustomFieldDefinitionRead.model_validate(definition, from_attributes=True)
    payload.board_ids = board_ids
    return payload


async def _board_ids_by_definition_id(
    *,
    session: AsyncSession,
    definition_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    if not definition_ids:
        return {}
    rows = (
        await session.exec(
            select(
                col(BoardTaskCustomField.task_custom_field_definition_id),
                col(BoardTaskCustomField.board_id),
            ).where(
                col(BoardTaskCustomField.task_custom_field_definition_id).in_(definition_ids),
            ),
        )
    ).all()
    board_ids_by_definition_id: dict[UUID, list[UUID]] = {
        definition_id: [] for definition_id in definition_ids
    }
    for definition_id, board_id in rows:
        board_ids_by_definition_id.setdefault(definition_id, []).append(board_id)
    for definition_id in board_ids_by_definition_id:
        board_ids_by_definition_id[definition_id].sort(key=str)
    return board_ids_by_definition_id


async def _validated_board_ids_for_org(
    *,
    session: AsyncSession,
    ctx: OrganizationContext,
    board_ids: list[UUID],
) -> list[UUID]:
    normalized_board_ids = list(dict.fromkeys(board_ids))
    if not normalized_board_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one board must be selected.",
        )
    valid_board_ids = set(
        (
            await session.exec(
                select(col(Board.id)).where(
                    col(Board.organization_id) == ctx.organization.id,
                    col(Board.id).in_(normalized_board_ids),
                ),
            )
        ).all(),
    )
    missing_board_ids = sorted(
        {board_id for board_id in normalized_board_ids if board_id not in valid_board_ids},
        key=str,
    )
    if missing_board_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Some selected boards are invalid for this organization.",
                "invalid_board_ids": [str(value) for value in missing_board_ids],
            },
        )
    return normalized_board_ids


async def _get_org_definition(
    *,
    session: AsyncSession,
    ctx: OrganizationContext,
    definition_id: UUID,
) -> TaskCustomFieldDefinition:
    definition = (
        await session.exec(
            select(TaskCustomFieldDefinition).where(
                col(TaskCustomFieldDefinition.id) == definition_id,
                col(TaskCustomFieldDefinition.organization_id) == ctx.organization.id,
            ),
        )
    ).first()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return definition


@router.get("", response_model=list[TaskCustomFieldDefinitionRead])
async def list_org_custom_fields(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[TaskCustomFieldDefinitionRead]:
    """List task custom field definitions for the authenticated organization."""
    definitions = list(
        await session.exec(
            select(TaskCustomFieldDefinition)
            .where(col(TaskCustomFieldDefinition.organization_id) == ctx.organization.id)
            .order_by(func.lower(col(TaskCustomFieldDefinition.label)).asc()),
        ),
    )
    board_ids_by_definition_id = await _board_ids_by_definition_id(
        session=session,
        definition_ids=[definition.id for definition in definitions],
    )
    return [
        _to_definition_read_payload(
            definition=definition,
            board_ids=board_ids_by_definition_id.get(definition.id, []),
        )
        for definition in definitions
    ]


@router.post("", response_model=TaskCustomFieldDefinitionRead)
async def create_org_custom_field(
    payload: TaskCustomFieldDefinitionCreate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TaskCustomFieldDefinitionRead:
    """Create an organization-level task custom field definition."""
    board_ids = await _validated_board_ids_for_org(
        session=session,
        ctx=ctx,
        board_ids=payload.board_ids,
    )
    try:
        validate_custom_field_definition(
            field_type=payload.field_type,
            validation_regex=payload.validation_regex,
            default_value=payload.default_value,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err
    definition = TaskCustomFieldDefinition(
        organization_id=ctx.organization.id,
        field_key=payload.field_key,
        label=payload.label or payload.field_key,
        field_type=payload.field_type,
        ui_visibility=payload.ui_visibility,
        validation_regex=payload.validation_regex,
        description=payload.description,
        required=payload.required,
        default_value=payload.default_value,
    )
    session.add(definition)
    await session.flush()
    for board_id in board_ids:
        session.add(
            BoardTaskCustomField(
                board_id=board_id,
                task_custom_field_definition_id=definition.id,
            ),
        )
    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Field key already exists in this organization.",
        ) from err

    await session.refresh(definition)
    return _to_definition_read_payload(definition=definition, board_ids=board_ids)


@router.patch("/{task_custom_field_definition_id}", response_model=TaskCustomFieldDefinitionRead)
async def update_org_custom_field(
    task_custom_field_definition_id: UUID,
    payload: TaskCustomFieldDefinitionUpdate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TaskCustomFieldDefinitionRead:
    """Update an organization-level task custom field definition."""
    definition = await _get_org_definition(
        session=session,
        ctx=ctx,
        definition_id=task_custom_field_definition_id,
    )
    updates = payload.model_dump(exclude_unset=True)
    board_ids = updates.pop("board_ids", None)
    validated_board_ids: list[UUID] | None = None
    if board_ids is not None:
        validated_board_ids = await _validated_board_ids_for_org(
            session=session,
            ctx=ctx,
            board_ids=board_ids,
        )
    next_field_type = updates.get("field_type", definition.field_type)
    next_validation_regex = (
        updates["validation_regex"]
        if "validation_regex" in updates
        else definition.validation_regex
    )
    next_default_value = (
        updates["default_value"] if "default_value" in updates else definition.default_value
    )
    try:
        validate_custom_field_definition(
            field_type=next_field_type,
            validation_regex=next_validation_regex,
            default_value=next_default_value,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err
    for key, value in updates.items():
        setattr(definition, key, value)
    if validated_board_ids is not None:
        bindings = list(
            await session.exec(
                select(BoardTaskCustomField).where(
                    col(BoardTaskCustomField.task_custom_field_definition_id) == definition.id,
                ),
            ),
        )
        current_board_ids = {binding.board_id for binding in bindings}
        target_board_ids = set(validated_board_ids)
        for binding in bindings:
            if binding.board_id not in target_board_ids:
                await session.delete(binding)
        for board_id in validated_board_ids:
            if board_id in current_board_ids:
                continue
            session.add(
                BoardTaskCustomField(
                    board_id=board_id,
                    task_custom_field_definition_id=definition.id,
                ),
            )
    definition.updated_at = utcnow()
    session.add(definition)

    try:
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Field key already exists in this organization.",
        ) from err

    await session.refresh(definition)
    if validated_board_ids is None:
        board_ids = (
            await _board_ids_by_definition_id(
                session=session,
                definition_ids=[definition.id],
            )
        ).get(definition.id, [])
    else:
        board_ids = validated_board_ids
    return _to_definition_read_payload(definition=definition, board_ids=board_ids)


@router.delete("/{task_custom_field_definition_id}", response_model=OkResponse)
async def delete_org_custom_field(
    task_custom_field_definition_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OkResponse:
    """Delete an org-level definition when it has no persisted task values."""
    definition = await _get_org_definition(
        session=session,
        ctx=ctx,
        definition_id=task_custom_field_definition_id,
    )
    value_ids = (
        await session.exec(
            select(col(TaskCustomFieldValue.id)).where(
                col(TaskCustomFieldValue.task_custom_field_definition_id) == definition.id,
            ),
        )
    ).all()
    if value_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a custom field definition while task values exist.",
        )

    bindings = list(
        await session.exec(
            select(BoardTaskCustomField).where(
                col(BoardTaskCustomField.task_custom_field_definition_id) == definition.id,
            ),
        ),
    )
    for binding in bindings:
        await session.delete(binding)
    await session.delete(definition)
    await session.commit()
    return OkResponse()
