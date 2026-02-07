from __future__ import annotations

from pydantic import BaseModel


class SoulsDirectorySoulRef(BaseModel):
    handle: str
    slug: str
    page_url: str
    raw_md_url: str


class SoulsDirectorySearchResponse(BaseModel):
    items: list[SoulsDirectorySoulRef]


class SoulsDirectoryMarkdownResponse(BaseModel):
    handle: str
    slug: str
    content: str
