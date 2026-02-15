"""Minimal GitHub REST client used for merge-policy enforcement.

This module is intentionally small and purpose-built for:
- PR metadata lookup (head SHA)
- Check Runs upsert (create or update by name)

It uses a repo-scoped token (PAT or GitHub App token) provided via settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_ERROR_DETAIL_MAX_CHARS = 500


def _safe_error_detail(resp: httpx.Response) -> str:
    """Return a safe, truncated error detail string for exceptions/logs."""
    try:
        text = (resp.text or "").strip()
    except Exception:
        return ""
    if not text:
        return ""
    if len(text) <= _ERROR_DETAIL_MAX_CHARS:
        return text
    return f"{text[: _ERROR_DETAIL_MAX_CHARS - 3]}..."


GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


@dataclass(frozen=True)
class ParsedPullRequest:
    owner: str
    repo: str
    number: int
    url: str


def parse_pull_request_url(url: str) -> ParsedPullRequest | None:
    """Parse a GitHub PR URL: https://github.com/<owner>/<repo>/pull/<number>."""
    raw = (url or "").strip()
    if not raw:
        return None
    if raw.startswith("http://"):
        # normalize; we only accept github.com URLs
        raw = "https://" + raw.removeprefix("http://")
    if not raw.startswith("https://github.com/"):
        return None
    path = raw.removeprefix("https://github.com/")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4:
        return None
    owner, repo, kind, num = parts[0], parts[1], parts[2], parts[3]
    if kind != "pull":
        return None
    try:
        number = int(num)
    except ValueError:
        return None
    if number <= 0:
        return None
    canonical_url = f"https://github.com/{owner}/{repo}/pull/{number}"
    return ParsedPullRequest(owner=owner, repo=repo, number=number, url=canonical_url)


class GitHubClientError(RuntimeError):
    pass


def _auth_headers() -> dict[str, str]:
    token = (settings.github_token or "").strip()
    if not token:
        raise GitHubClientError("GitHub token is not configured (GH_TOKEN/GITHUB_TOKEN).")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


async def get_pull_request_head_sha(pr: ParsedPullRequest) -> str:
    """Return head SHA for a PR."""
    url = f"{GITHUB_API_BASE_URL}/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_auth_headers())
    if resp.status_code >= 400:
        detail = _safe_error_detail(resp)
        suffix = f" {detail}" if detail else ""
        raise GitHubClientError(f"GitHub PR lookup failed: {resp.status_code}{suffix}")
    data = resp.json()
    head = data.get("head")
    if not isinstance(head, dict) or not isinstance(head.get("sha"), str):
        raise GitHubClientError("GitHub PR response missing head.sha")
    # mypy: dict indexing returns Any; we've validated it's a str above.
    return str(head["sha"])


async def _find_check_run_id(*, owner: str, repo: str, ref: str, check_name: str) -> int | None:
    # Docs: GET /repos/{owner}/{repo}/commits/{ref}/check-runs
    url = f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/commits/{ref}/check-runs"
    params: dict[str, str | int] = {"check_name": check_name, "per_page": 100}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_auth_headers(), params=params)
    if resp.status_code >= 400:
        detail = _safe_error_detail(resp)
        suffix = f" {detail}" if detail else ""
        raise GitHubClientError(
            f"GitHub check-runs lookup failed: {resp.status_code}{suffix}",
        )
    payload = resp.json()
    runs = payload.get("check_runs")
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("name") != check_name:
            continue
        run_id = run.get("id")
        if isinstance(run_id, int):
            return run_id
    return None


CheckStatus = Literal["queued", "in_progress", "completed"]
CheckConclusion = Literal[
    "success",
    "failure",
    "neutral",
    "cancelled",
    "skipped",
    "timed_out",
    "action_required",
]


async def upsert_check_run(
    *,
    owner: str,
    repo: str,
    head_sha: str,
    check_name: str,
    status: CheckStatus,
    conclusion: CheckConclusion | None,
    title: str,
    summary: str,
    details_url: str | None = None,
) -> None:
    """Create or update a check run on a commit SHA.

    If a check run with the same name exists on the ref, we patch it.
    Otherwise, we create a new one.
    """

    payload: dict[str, Any] = {
        "name": check_name,
        "head_sha": head_sha,
        "status": status,
        "output": {
            "title": title,
            "summary": summary,
        },
    }
    if details_url:
        payload["details_url"] = details_url
    if status == "completed":
        if conclusion is None:
            raise ValueError("conclusion is required when status=completed")
        payload["conclusion"] = conclusion

    run_id = await _find_check_run_id(owner=owner, repo=repo, ref=head_sha, check_name=check_name)
    if run_id is None:
        url = f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/check-runs"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers={**_auth_headers(), "Accept": "application/vnd.github+json"}, json=payload)
        if resp.status_code >= 400:
            detail = _safe_error_detail(resp)
            suffix = f" {detail}" if detail else ""
            raise GitHubClientError(
                f"GitHub check-run create failed: {resp.status_code}{suffix}",
            )
        logger.info(
            "github.check_run.created",
            extra={"owner": owner, "repo": repo, "sha": head_sha, "check": check_name},
        )
        return

    url = f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/check-runs/{run_id}"
    # PATCH payload should not include head_sha/name for updates? Safe to include minimal fields.
    patch_payload = {
        "status": status,
        "output": payload["output"],
    }
    if details_url:
        patch_payload["details_url"] = details_url
    if status == "completed":
        patch_payload["conclusion"] = conclusion

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(url, headers=_auth_headers(), json=patch_payload)
    if resp.status_code >= 400:
        detail = _safe_error_detail(resp)
        suffix = f" {detail}" if detail else ""
        raise GitHubClientError(
            f"GitHub check-run update failed: {resp.status_code}{suffix}",
        )
    logger.info(
        "github.check_run.updated",
        extra={"owner": owner, "repo": repo, "sha": head_sha, "check": check_name, "id": run_id},
    )
