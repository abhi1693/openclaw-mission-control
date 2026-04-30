"""Common reusable schema primitives and simple API response envelopes."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BeforeValidator, StringConstraints
from sqlmodel import SQLModel

# Reusable string type for request payloads where blank/whitespace-only values
# are invalid.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Open-vocabulary reason-code identifier shape: lower-case ASCII, must
# start with a letter, alphanumeric+underscore, max 64 chars. Used for
# the structured ``reason_code`` field on Blocker and OperatorDecision.
# Recognised codes live in ``app/services/blocker_reason_codes.py``;
# unknown codes are accepted by this validator but treated as opaque by
# revalidation logic.
_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def normalize_reason_code(value: object) -> str | None:
    """Strip + lower-case + blank→None + regex-validate a reason_code.

    Raises ``ValueError`` (not ``TypeError``) for non-string inputs so
    Pydantic v2 wraps the failure as a 422 instead of letting it escape
    as a 500.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("reason_code must be a string")
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if not _REASON_CODE_RE.match(cleaned):
        raise ValueError(
            "reason_code must match ^[a-z][a-z0-9_]{0,63}$ (lowercase, "
            "ASCII alphanumeric+underscore, starts with a letter, "
            "max 64 chars)"
        )
    return cleaned


# Annotated type alias — declare ``reason_code: ReasonCode = None`` on a
# schema and Pydantic auto-applies the normalizer without per-schema
# ``@field_validator`` boilerplate. Mirrors the established pattern in
# ``app/schemas/board_webhooks.py``.
ReasonCode = Annotated[str | None, BeforeValidator(normalize_reason_code)]


class OkResponse(SQLModel):
    """Standard success response payload."""

    ok: bool = True
