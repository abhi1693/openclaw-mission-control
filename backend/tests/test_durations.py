# ruff: noqa: INP001
"""Regression tests for compact duration parsing."""

from app.core.durations import parse_every_to_seconds


def test_parse_every_to_seconds_accepts_minute_schedule() -> None:
    assert parse_every_to_seconds("10m") == 600
