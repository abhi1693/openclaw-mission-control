"""Service helpers for querying and caching souls.directory content."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Final

import httpx

SOULS_DIRECTORY_BASE_URL: Final[str] = "https://souls.directory"
SOULS_DIRECTORY_SITEMAP_URL: Final[str] = f"{SOULS_DIRECTORY_BASE_URL}/sitemap.xml"

_SITEMAP_TTL_SECONDS: Final[int] = 60 * 60
_SOUL_URL_MIN_PARTS: Final[int] = 6
_LOC_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?loc>(.*?)</(?:[A-Za-z0-9_]+:)?loc>",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class SoulRef:
    """Handle/slug reference pair for a soul entry."""

    handle: str
    slug: str

    @property
    def page_url(self) -> str:
        """Return the canonical page URL for this soul."""
        return f"{SOULS_DIRECTORY_BASE_URL}/souls/{self.handle}/{self.slug}"

    @property
    def raw_md_url(self) -> str:
        """Return the raw markdown URL for this soul."""
        return f"{SOULS_DIRECTORY_BASE_URL}/api/souls/{self.handle}/{self.slug}.md"


def _parse_sitemap_soul_refs(sitemap_xml: str) -> list[SoulRef]:
    """Parse sitemap XML and extract valid souls.directory handle/slug refs."""
    # Extract <loc> values without XML entity expansion.
    urls = [unescape(match.group(1)).strip() for match in _LOC_PATTERN.finditer(sitemap_xml)]

    refs: list[SoulRef] = []
    for url in urls:
        if not url.startswith(f"{SOULS_DIRECTORY_BASE_URL}/souls/"):
            continue
        # Expected: https://souls.directory/souls/{handle}/{slug}
        parts = url.split("/")
        if len(parts) < _SOUL_URL_MIN_PARTS:
            continue
        handle = parts[4].strip()
        slug = parts[5].strip()
        if not handle or not slug:
            continue
        refs.append(SoulRef(handle=handle, slug=slug))
    return refs


_sitemap_cache: dict[str, object] = {
    "loaded_at": 0.0,
    "refs": [],
}


async def list_souls_directory_refs(
    *,
    client: httpx.AsyncClient | None = None,
) -> list[SoulRef]:
    """Return cached sitemap-derived soul refs, refreshing when TTL expires."""
    now = time.time()
    loaded_raw = _sitemap_cache.get("loaded_at")
    loaded_at = loaded_raw if isinstance(loaded_raw, (int, float)) else 0.0
    cached = _sitemap_cache.get("refs")
    if cached and isinstance(cached, list) and now - loaded_at < _SITEMAP_TTL_SECONDS:
        return cached

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"User-Agent": "openclaw-mission-control/1.0"},
        )
    try:
        resp = await client.get(SOULS_DIRECTORY_SITEMAP_URL)
        resp.raise_for_status()
        refs = _parse_sitemap_soul_refs(resp.text)
        _sitemap_cache["loaded_at"] = now
        _sitemap_cache["refs"] = refs
        return refs
    finally:
        if owns_client:
            await client.aclose()


async def fetch_soul_markdown(
    *,
    handle: str,
    slug: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Fetch raw markdown content for a specific handle/slug pair."""
    normalized_handle = handle.strip().strip("/")
    normalized_slug = slug.strip().strip("/")
    if normalized_slug.endswith(".md"):
        normalized_slug = normalized_slug[: -len(".md")]
    url = f"{SOULS_DIRECTORY_BASE_URL}/api/souls/" f"{normalized_handle}/{normalized_slug}.md"

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": "openclaw-mission-control/1.0"},
        )
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    finally:
        if owns_client:
            await client.aclose()


def search_souls(refs: list[SoulRef], *, query: str, limit: int = 20) -> list[SoulRef]:
    """Search refs by case-insensitive handle/slug substring with a hard limit."""
    q = query.strip().lower()
    if not q:
        return refs[: max(0, min(limit, len(refs)))]

    matches: list[SoulRef] = []
    for ref in refs:
        hay = f"{ref.handle}/{ref.slug}".lower()
        if q in hay:
            matches.append(ref)
        if len(matches) >= limit:
            break
    return matches
