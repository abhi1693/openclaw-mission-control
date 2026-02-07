from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ActorContext, require_admin_or_agent
from app.schemas.souls_directory import (
    SoulsDirectoryMarkdownResponse,
    SoulsDirectorySearchResponse,
    SoulsDirectorySoulRef,
)
from app.services import souls_directory

router = APIRouter(prefix="/souls-directory", tags=["souls-directory"])

_SAFE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_SAFE_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_segment(value: str, *, field: str) -> str:
    cleaned = value.strip().strip("/")
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} is required",
        )
    if field == "handle":
        ok = bool(_SAFE_SEGMENT_RE.match(cleaned))
    else:
        ok = bool(_SAFE_SLUG_RE.match(cleaned))
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} contains unsupported characters",
        )
    return cleaned


@router.get("/search", response_model=SoulsDirectorySearchResponse)
async def search(
    q: str = Query(default="", min_length=0),
    limit: int = Query(default=20, ge=1, le=100),
    _actor: ActorContext = Depends(require_admin_or_agent),
) -> SoulsDirectorySearchResponse:
    refs = await souls_directory.list_souls_directory_refs()
    matches = souls_directory.search_souls(refs, query=q, limit=limit)
    items = [
        SoulsDirectorySoulRef(
            handle=ref.handle,
            slug=ref.slug,
            page_url=ref.page_url,
            raw_md_url=ref.raw_md_url,
        )
        for ref in matches
    ]
    return SoulsDirectorySearchResponse(items=items)


@router.get("/{handle}/{slug}.md", response_model=SoulsDirectoryMarkdownResponse)
@router.get("/{handle}/{slug}", response_model=SoulsDirectoryMarkdownResponse)
async def get_markdown(
    handle: str,
    slug: str,
    _actor: ActorContext = Depends(require_admin_or_agent),
) -> SoulsDirectoryMarkdownResponse:
    safe_handle = _validate_segment(handle, field="handle")
    safe_slug = _validate_segment(slug.removesuffix(".md"), field="slug")
    try:
        content = await souls_directory.fetch_soul_markdown(handle=safe_handle, slug=safe_slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SoulsDirectoryMarkdownResponse(handle=safe_handle, slug=safe_slug, content=content)
