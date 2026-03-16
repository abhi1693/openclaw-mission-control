from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.api import metrics as metrics_api
from app.schemas.metrics import DashboardRangeKey


@pytest.mark.parametrize(
    ("range_key", "expected_bucket", "expected_duration"),
    [
        ("24h", "hour", timedelta(hours=24)),
        ("3d", "day", timedelta(days=3)),
        ("7d", "day", timedelta(days=7)),
        ("14d", "day", timedelta(days=14)),
        ("1m", "day", timedelta(days=30)),
        ("3m", "week", timedelta(days=90)),
        ("6m", "week", timedelta(days=180)),
        ("1y", "month", timedelta(days=365)),
    ],
)
def test_resolve_range_maps_expected_window(
    monkeypatch: pytest.MonkeyPatch,
    range_key: DashboardRangeKey,
    expected_bucket: str,
    expected_duration: timedelta,
) -> None:
    fixed_now = datetime(2026, 2, 12, 15, 30, 0)
    monkeypatch.setattr(metrics_api, "utcnow", lambda: fixed_now)

    spec = metrics_api._resolve_range(range_key)

    assert spec.key == range_key
    assert spec.bucket == expected_bucket
    assert spec.duration == expected_duration
    assert spec.start == fixed_now - expected_duration
    assert spec.end == fixed_now


def test_comparison_range_is_previous_window(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 2, 12, 15, 30, 0)
    monkeypatch.setattr(metrics_api, "utcnow", lambda: fixed_now)
    primary = metrics_api._resolve_range("14d")

    comparison = metrics_api._comparison_range(primary)

    assert comparison.key == primary.key
    assert comparison.bucket == primary.bucket
    assert comparison.duration == primary.duration
    assert comparison.start == primary.start - primary.duration
    assert comparison.end == primary.end - primary.duration


def test_week_buckets_align_to_monday(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 2, 12, 15, 30, 0)
    monkeypatch.setattr(metrics_api, "utcnow", lambda: fixed_now)
    spec = metrics_api._resolve_range("3m")

    buckets = metrics_api._build_buckets(spec)

    assert buckets
    assert all(bucket.weekday() == 0 for bucket in buckets)
    assert all(
        buckets[index + 1] - buckets[index] == timedelta(days=7)
        for index in range(len(buckets) - 1)
    )


def test_month_buckets_align_to_first_of_month(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 2, 12, 15, 30, 0)
    monkeypatch.setattr(metrics_api, "utcnow", lambda: fixed_now)
    spec = metrics_api._resolve_range("1y")

    buckets = metrics_api._build_buckets(spec)

    assert buckets
    assert all(
        bucket.day == 1
        and bucket.hour == 0
        and bucket.minute == 0
        and bucket.second == 0
        and bucket.microsecond == 0
        for bucket in buckets
    )
    assert len(buckets) >= 12
