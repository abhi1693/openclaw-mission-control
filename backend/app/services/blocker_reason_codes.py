"""Canonical reason-code registry for blockers and operator decisions.

The DB column is open-vocabulary (no CHECK constraint, no Pydantic Literal)
so new codes can be added without a schema migration. This module is the
runtime source of truth for which codes the platform RECOGNISES — used by:

- the `lead-health-scan` skill's revalidation dispatch
- (planned, Phase IV-A) `strict` enforcement that 422s agent-filed
  blockers carrying unknown codes for runtime/deploy categories

Operators can post any string they want; the DB accepts it. Agents
filing programmatic blockers should restrict themselves to the
recognised set so revalidation logic has something to act on.

When adding a new code:

1. Add it here with a classification.
2. Add a probe rule to `lead-health-scan` SKILL.md if it's auto-revalidatable.
3. Add a test in `tests/test_blocker_reason_codes.py`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Final, Literal, get_args
from uuid import UUID

ReasonCodeClass = Literal[
    "infra_self_resolvable",  # gateway / runtime issues that may have recovered
    "deploy_drift",  # source vs. live target divergence; recheck mechanically
    "external_dependency",  # waiting on a vendor/3rd-party signal
    "operator_durable",  # human policy/judgment; never auto-revalidates
]

# Static union of recognised codes. Adding a new code requires editing
# this Literal AND the ``_CODE_CLASS`` mapping below — keeping both
# in sync gives static type checkers a chance to catch typos in
# downstream call sites that reference the registry by string literal.
KnownReasonCode = Literal[
    "credential_required",
    "deploy_drift",
    "external_dependency",
    "gateway_ws_timeout",
    "infra_other",
    "operator_policy",
    "requirements_clarification",
    "review_anti_loop",
]

# Canonical map: reason_code -> classification.
# Keep sorted alphabetically for diff stability.
_CODE_CLASS: Final[dict[KnownReasonCode, ReasonCodeClass]] = {
    "credential_required": "operator_durable",
    "deploy_drift": "deploy_drift",
    "external_dependency": "external_dependency",
    "gateway_ws_timeout": "infra_self_resolvable",
    "infra_other": "operator_durable",
    "operator_policy": "operator_durable",
    "requirements_clarification": "operator_durable",
    "review_anti_loop": "operator_durable",
}

RECOGNISED_CODES: Final[frozenset[str]] = frozenset(_CODE_CLASS)

# Import-time guard: the static ``KnownReasonCode`` union and the runtime
# ``_CODE_CLASS`` keys must stay in lockstep. A contributor adding to one
# but not the other would otherwise get silent drift — this assertion
# fires at module import so the regression surfaces in CI/startup.
assert set(get_args(KnownReasonCode)) == set(_CODE_CLASS), (
    "KnownReasonCode Literal members and _CODE_CLASS keys are out of sync. "
    "Update both when adding or removing a recognised reason code."
)

# Codes that the revalidation skill may auto-probe. Excludes
# operator_durable codes — those represent human decisions we don't
# auto-clear on infra recovery.
AUTO_REVALIDATABLE_CODES: Final[frozenset[str]] = frozenset(
    code for code, cls in _CODE_CLASS.items() if cls in {"infra_self_resolvable", "deploy_drift"}
)


def is_recognised(code: str | None) -> bool:
    """True iff the code is in the canonical registry."""
    return code is not None and code in _CODE_CLASS


def classify(code: str | None) -> ReasonCodeClass | None:
    """Return the classification for a recognised code, or None."""
    if code is None or code not in _CODE_CLASS:
        return None
    return _CODE_CLASS[code]


def is_auto_revalidatable(code: str | None) -> bool:
    """True iff the revalidation skill should run a probe for this code.

    Operator-durable codes (e.g. policy, credentials, requirements
    clarification) explicitly never auto-revalidate even if the skill
    sees them stale — those are human decisions, not infra.
    """
    return code is not None and code in AUTO_REVALIDATABLE_CODES


def group_codes_by_task(
    rows: Iterable[tuple[UUID | None, str | None]],
) -> dict[UUID, list[str]]:
    """Group ``(task_id, reason_code)`` rows by task id, deduplicated.

    Both NULL ``task_id`` and NULL ``code`` rows are dropped before any
    bucket is created — preserves the contract documented on the two
    batch-helper callers ("tasks whose only ... codes are NULL are
    absent from the result map"). All values in the returned map are
    non-empty.
    """
    grouped: defaultdict[UUID, list[str]] = defaultdict(list)
    for task_id, code in rows:
        if task_id is None or code is None:
            continue
        bucket = grouped[task_id]
        if code not in bucket:
            bucket.append(code)
    return dict(grouped)
