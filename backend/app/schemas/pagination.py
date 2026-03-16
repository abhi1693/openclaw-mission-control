"""Shared pagination response type aliases used by API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from fastapi import Query
from fastapi_pagination.customization import CustomizedPage, UseParamsFields
from fastapi_pagination.limit_offset import LimitOffsetPage

T = TypeVar("T")


# Project-wide default pagination response model.
# - Keep `limit` / `offset` naming (matches existing API conventions).
# - Cap list endpoints to 200 items per request (matches prior route-level constraints).
if TYPE_CHECKING:
    # Type checkers treat this as a normal generic page type.
    DefaultLimitOffsetPage = LimitOffsetPage
else:
    # Runtime uses project-default query param bounds for all list endpoints.
    DefaultLimitOffsetPage = CustomizedPage[
        LimitOffsetPage[T],
        UseParamsFields(
            limit=Query(200, ge=1, le=200),
            offset=Query(0, ge=0),
        ),
    ]
