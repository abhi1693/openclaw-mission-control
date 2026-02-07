from __future__ import annotations

from app.services.souls_directory import SoulRef, _parse_sitemap_soul_refs, search_souls


def test_parse_sitemap_extracts_soul_refs() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://souls.directory</loc></url>
  <url><loc>https://souls.directory/souls/thedaviddias/code-reviewer</loc></url>
  <url><loc>https://souls.directory/souls/someone/technical-writer</loc></url>
</urlset>
"""
    refs = _parse_sitemap_soul_refs(xml)
    assert refs == [
        SoulRef(handle="thedaviddias", slug="code-reviewer"),
        SoulRef(handle="someone", slug="technical-writer"),
    ]


def test_search_souls_matches_handle_or_slug() -> None:
    refs = [
        SoulRef(handle="thedaviddias", slug="code-reviewer"),
        SoulRef(handle="thedaviddias", slug="technical-writer"),
        SoulRef(handle="someone", slug="pirate-captain"),
    ]
    assert search_souls(refs, query="writer", limit=20) == [refs[1]]
    assert search_souls(refs, query="thedaviddias", limit=20) == [refs[0], refs[1]]
