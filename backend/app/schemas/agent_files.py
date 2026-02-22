"""Pydantic schemas for agent file operations."""

from __future__ import annotations

from pydantic import Field
from sqlmodel import SQLModel
from sqlmodel._compat import SQLModelConfig


class AgentFileRead(SQLModel):
    """Response model for reading an agent file."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_file_content",
            "x-when-to-use": [
                "Retrieve content of an agent markdown file",
                "Read IDENTITY.md, SOUL.md, BOOTSTRAP.md, or other agent files",
            ],
        },
    )

    name: str = Field(
        description="File name (e.g., IDENTITY.md, SOUL.md, BOOTSTRAP.md)",
        examples=["IDENTITY.md", "SOUL.md"],
    )
    content: str = Field(
        description="File content",
        examples=["# IDENTITY.md\n\n## Core\n- Name: Agent Name"],
    )


class AgentFileUpdate(SQLModel):
    """Request model for updating an agent file."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_file_update",
            "x-when-to-use": [
                "Update an agent markdown file",
                "Modify IDENTITY.md or other editable agent files",
            ],
        },
    )

    content: str = Field(
        description="New file content",
        examples=["# IDENTITY.md\n\n## Core\n- Name: Updated Agent Name"],
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for the update",
        examples=["Updated agent role and communication style"],
    )


class AgentFileListItem(SQLModel):
    """Agent file list item."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_file_list_item",
        },
    )

    name: str = Field(
        description="File name",
        examples=["IDENTITY.md", "SOUL.md", "BOOTSTRAP.md"],
    )
    editable: bool = Field(
        description="Whether the file can be edited via the API",
        examples=[True, False],
    )
