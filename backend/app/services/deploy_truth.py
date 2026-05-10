"""Phase V §I8 capability-based deploy-truth helpers.

When a task carries ``supports_build_metadata=True``, the reviewer is
claiming the target exposes ``GET /__build`` and that the task's
``packet_commit_sha`` matches what's live. This module:

- fetches the target's ``/__build`` response,
- normalises the payload into ``BuildMetadata``,
- compares the claimed packet SHA with the live SHA under the
  same abbreviated-SHA rules the schema validator enforces.

Degraded-validation (``supports_build_metadata`` is ``False`` or
``None``) is handled at the caller — this module only owns the
capable-target code path.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.logging import get_logger
from app.schemas.tasks import _SHA_HEX_RE

logger = get_logger(__name__)

# Short total timeout + shorter connect — the target may be deployed
# on a flaky environment; the PATCH handler that calls this should not
# block the user for more than a few seconds on the SHA fetch.
_BUILD_ENDPOINT_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_BUILD_ENDPOINT_PATH = "/__build"


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    """Normalised ``/__build`` response.

    All fields optional because targets emit them inconsistently —
    the SHA comparator only requires ``sha``.
    """

    sha: str | None
    built_at: str | None = None
    branch: str | None = None
    target: str | None = None


class DeployTruthFetchError(Exception):
    """Raised when the target's ``/__build`` endpoint is unreachable
    or returns an unparseable response. The caller chooses whether
    this is a hard failure or degrades to operator-visible."""


async def fetch_build_metadata(
    target_url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> BuildMetadata:
    """GET ``{target_url}/__build`` and parse the response.

    ``target_url`` is the ``Task.validation_target`` string; the
    ``/__build`` path is appended even if the target ends with a
    trailing slash.
    """

    normalised = target_url.rstrip("/") + _BUILD_ENDPOINT_PATH
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=_BUILD_ENDPOINT_TIMEOUT,
            headers={"User-Agent": "openclaw-mission-control/1.0"},
        )
    try:
        try:
            resp = await client.get(normalised)
        except httpx.HTTPError as exc:
            raise DeployTruthFetchError(f"unable to reach {normalised}: {exc}") from exc
        if resp.status_code != 200:
            raise DeployTruthFetchError(f"{normalised} returned HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise DeployTruthFetchError(f"{normalised} returned non-JSON body") from exc
        if not isinstance(payload, dict):
            raise DeployTruthFetchError(f"{normalised} returned a non-object body")
        raw_sha = payload.get("sha")
        sha = raw_sha.strip().lower() if isinstance(raw_sha, str) else None
        sha = sha or None
        if sha is not None and not _SHA_HEX_RE.match(sha):
            # Without this check a live ``/__build`` that returns
            # garbage like ``"abcdef1zzz"`` would pass
            # ``live.startswith(packet)`` for packet ``"abcdef1"``, so
            # the comparator would false-pass. Reuse the same
            # 7–40 lowercase-hex validator the packet fields use.
            raise DeployTruthFetchError(f"{normalised} returned a malformed sha: {sha!r}")
        return BuildMetadata(
            sha=sha,
            built_at=_as_str(payload.get("built_at")),
            branch=_as_str(payload.get("branch")),
            target=_as_str(payload.get("target")),
        )
    finally:
        if owns_client:
            await client.aclose()


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def packet_sha_matches_live(*, packet_sha: str, live_sha: str) -> bool:
    """Compare a packet-claimed SHA against the live-fetched SHA.

    The live SHA is the ground truth — the packet is asserting *what
    the reviewer believes is deployed*. A match requires the packet
    to be a prefix of the live SHA (case already normalised by the
    schema validator). Abbreviated packet SHAs (git's default 7-char
    short) therefore match a full 40-char live SHA; a full packet
    against a short live SHA is a capability misconfiguration — the
    live endpoint should always emit at least as much precision as
    the reviewer is claiming.

    Examples:
      packet="abcdef1", live="abcdef1234…"  → match (packet is prefix)
      packet="abcdef1234…", live="abcdef1"  → not match (capability bug)
      packet="abcde01",  live="abcde99…"    → not match (divergence)
    """

    if len(packet_sha) > len(live_sha):
        return False
    return live_sha.startswith(packet_sha)
