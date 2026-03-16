"""Common reusable schema primitives and simple API response envelopes."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints
from sqlmodel import SQLModel

# Reusable string type for request payloads where blank/whitespace-only values
# are invalid.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class OkResponse(SQLModel):
    """Standard success response payload."""

    ok: bool = True
