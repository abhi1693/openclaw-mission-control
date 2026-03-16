"""Schemas for souls-directory search and markdown fetch responses."""

from __future__ import annotations

from pydantic import BaseModel


class SoulsDirectorySoulRef(BaseModel):
    """Reference metadata for a soul entry in the directory index."""

    handle: str
    slug: str
    page_url: str
    raw_md_url: str


class SoulsDirectorySearchResponse(BaseModel):
    """Response wrapper for directory search results."""

    items: list[SoulsDirectorySoulRef]


class SoulsDirectoryMarkdownResponse(BaseModel):
    """Response payload containing rendered markdown for a soul."""

    handle: str
    slug: str
    content: str
