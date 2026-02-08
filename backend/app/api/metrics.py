from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import DateTime, case, cast, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_org_member
from app.core.time import utcnow
from app.db.session import get_session
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.tasks import Task
from app.schemas.metrics import (
    DashboardKpis,
    DashboardMetrics,
    DashboardRangeSeries,
    DashboardSeriesPoint,
    DashboardSeriesSet,
    DashboardWipPoint,
    DashboardWipRangeSeries,
    DashboardWipSeriesSet,
)
from app.services.organizations import OrganizationContext, list_accessible_board_ids

router = APIRouter(prefix="/metrics", tags=["metrics"])

OFFLINE_AFTER = timedelta(minutes=10)
ERROR_EVENT_PATTERN = "%failed"


@dataclass(frozen=True)
class RangeSpec:
    key: Literal["24h", "7d"]
    start: datetime
    end: datetime
    bucket: Literal["hour", "day"]


def _resolve_range(range_key: Literal["24h", "7d"]) -> RangeSpec:
    now = utcnow()
    if range_key == "7d":
        return RangeSpec(
            key="7d",
            start=now - timedelta(days=7),
            end=now,
            bucket="day",
        )
    return RangeSpec(
        key="24h",
        start=now - timedelta(hours=24),
        end=now,
        bucket="hour",
    )


def _comparison_range(range_key: Literal["24h", "7d"]) -> RangeSpec:
    return _resolve_range("7d" if range_key == "24h" else "24h")


def _bucket_start(value: datetime, bucket: Literal["hour", "day"]) -> datetime:
    if bucket == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


def _build_buckets(range_spec: RangeSpec) -> list[datetime]:
    cursor = _bucket_start(range_spec.start, range_spec.bucket)
    step = timedelta(days=1) if range_spec.bucket == "day" else timedelta(hours=1)
    buckets: list[datetime] = []
    while cursor <= range_spec.end:
        buckets.append(cursor)
        cursor += step
    return buckets


def _series_from_mapping(
    range_spec: RangeSpec, mapping: dict[datetime, float]
) -> DashboardRangeSeries:
    points = [
        DashboardSeriesPoint(period=bucket, value=float(mapping.get(bucket, 0)))
        for bucket in _build_buckets(range_spec)
    ]
    return DashboardRangeSeries(
        range=range_spec.key,
        bucket=range_spec.bucket,
        points=points,
    )


def _wip_series_from_mapping(
    range_spec: RangeSpec, mapping: dict[datetime, dict[str, int]]
) -> DashboardWipRangeSeries:
    points: list[DashboardWipPoint] = []
    for bucket in _build_buckets(range_spec):
        values = mapping.get(bucket, {})
        points.append(
            DashboardWipPoint(
                period=bucket,
                inbox=values.get("inbox", 0),
                in_progress=values.get("in_progress", 0),
                review=values.get("review", 0),
            )
        )
    return DashboardWipRangeSeries(
        range=range_spec.key,
        bucket=range_spec.bucket,
        points=points,
    )


async def _query_throughput(
    session: AsyncSession, range_spec: RangeSpec, board_ids: list[UUID]
) -> DashboardRangeSeries:
    bucket_col = func.date_trunc(range_spec.bucket, Task.updated_at).label("bucket")
    statement = (
        select(bucket_col, func.count())
        .where(col(Task.status) == "review")
        .where(col(Task.updated_at) >= range_spec.start)
        .where(col(Task.updated_at) <= range_spec.end)
    )
    if not board_ids:
        return _series_from_mapping(range_spec, {})
    statement = (
        statement.where(col(Task.board_id).in_(board_ids)).group_by(bucket_col).order_by(bucket_col)
    )
    results = (await session.exec(statement)).all()
    mapping = {row[0]: float(row[1]) for row in results}
    return _series_from_mapping(range_spec, mapping)


async def _query_cycle_time(
    session: AsyncSession, range_spec: RangeSpec, board_ids: list[UUID]
) -> DashboardRangeSeries:
    bucket_col = func.date_trunc(range_spec.bucket, Task.updated_at).label("bucket")
    in_progress = cast(Task.in_progress_at, DateTime)
    duration_hours = func.extract("epoch", Task.updated_at - in_progress) / 3600.0
    statement = (
        select(bucket_col, func.avg(duration_hours))
        .where(col(Task.status) == "review")
        .where(col(Task.in_progress_at).is_not(None))
        .where(col(Task.updated_at) >= range_spec.start)
        .where(col(Task.updated_at) <= range_spec.end)
    )
    if not board_ids:
        return _series_from_mapping(range_spec, {})
    statement = (
        statement.where(col(Task.board_id).in_(board_ids)).group_by(bucket_col).order_by(bucket_col)
    )
    results = (await session.exec(statement)).all()
    mapping = {row[0]: float(row[1] or 0) for row in results}
    return _series_from_mapping(range_spec, mapping)


async def _query_error_rate(
    session: AsyncSession, range_spec: RangeSpec, board_ids: list[UUID]
) -> DashboardRangeSeries:
    bucket_col = func.date_trunc(range_spec.bucket, ActivityEvent.created_at).label("bucket")
    error_case = case(
        (
            col(ActivityEvent.event_type).like(ERROR_EVENT_PATTERN),
            1,
        ),
        else_=0,
    )
    statement = (
        select(bucket_col, func.sum(error_case), func.count())
        .join(Task, col(ActivityEvent.task_id) == col(Task.id))
        .where(col(ActivityEvent.created_at) >= range_spec.start)
        .where(col(ActivityEvent.created_at) <= range_spec.end)
    )
    if not board_ids:
        return _series_from_mapping(range_spec, {})
    statement = (
        statement.where(col(Task.board_id).in_(board_ids)).group_by(bucket_col).order_by(bucket_col)
    )
    results = (await session.exec(statement)).all()
    mapping: dict[datetime, float] = {}
    for bucket, errors, total in results:
        total_count = float(total or 0)
        error_count = float(errors or 0)
        rate = (error_count / total_count) * 100 if total_count > 0 else 0.0
        mapping[bucket] = rate
    return _series_from_mapping(range_spec, mapping)


async def _query_wip(
    session: AsyncSession, range_spec: RangeSpec, board_ids: list[UUID]
) -> DashboardWipRangeSeries:
    bucket_col = func.date_trunc(range_spec.bucket, Task.updated_at).label("bucket")
    inbox_case = case((col(Task.status) == "inbox", 1), else_=0)
    progress_case = case((col(Task.status) == "in_progress", 1), else_=0)
    review_case = case((col(Task.status) == "review", 1), else_=0)
    statement = (
        select(
            bucket_col,
            func.sum(inbox_case),
            func.sum(progress_case),
            func.sum(review_case),
        )
        .where(col(Task.updated_at) >= range_spec.start)
        .where(col(Task.updated_at) <= range_spec.end)
    )
    if not board_ids:
        return _wip_series_from_mapping(range_spec, {})
    statement = (
        statement.where(col(Task.board_id).in_(board_ids)).group_by(bucket_col).order_by(bucket_col)
    )
    results = (await session.exec(statement)).all()
    mapping: dict[datetime, dict[str, int]] = {}
    for bucket, inbox, in_progress, review in results:
        mapping[bucket] = {
            "inbox": int(inbox or 0),
            "in_progress": int(in_progress or 0),
            "review": int(review or 0),
        }
    return _wip_series_from_mapping(range_spec, mapping)


async def _median_cycle_time_7d(session: AsyncSession, board_ids: list[UUID]) -> float | None:
    now = utcnow()
    start = now - timedelta(days=7)
    in_progress = cast(Task.in_progress_at, DateTime)
    duration_hours = func.extract("epoch", Task.updated_at - in_progress) / 3600.0
    statement = (
        select(func.percentile_cont(0.5).within_group(duration_hours))
        .where(col(Task.status) == "review")
        .where(col(Task.in_progress_at).is_not(None))
        .where(col(Task.updated_at) >= start)
        .where(col(Task.updated_at) <= now)
    )
    if not board_ids:
        return None
    statement = statement.where(col(Task.board_id).in_(board_ids))
    value = (await session.exec(statement)).one_or_none()
    if value is None:
        return None
    if isinstance(value, tuple):
        value = value[0]
    if value is None:
        return None
    return float(value)


async def _error_rate_kpi(
    session: AsyncSession, range_spec: RangeSpec, board_ids: list[UUID]
) -> float:
    error_case = case(
        (
            col(ActivityEvent.event_type).like(ERROR_EVENT_PATTERN),
            1,
        ),
        else_=0,
    )
    statement = (
        select(func.sum(error_case), func.count())
        .join(Task, col(ActivityEvent.task_id) == col(Task.id))
        .where(col(ActivityEvent.created_at) >= range_spec.start)
        .where(col(ActivityEvent.created_at) <= range_spec.end)
    )
    if not board_ids:
        return 0.0
    statement = statement.where(col(Task.board_id).in_(board_ids))
    result = (await session.exec(statement)).one_or_none()
    if result is None:
        return 0.0
    errors, total = result
    total_count = float(total or 0)
    error_count = float(errors or 0)
    return (error_count / total_count) * 100 if total_count > 0 else 0.0


async def _active_agents(session: AsyncSession, board_ids: list[UUID]) -> int:
    threshold = utcnow() - OFFLINE_AFTER
    statement = select(func.count()).where(
        col(Agent.last_seen_at).is_not(None),
        col(Agent.last_seen_at) >= threshold,
    )
    if not board_ids:
        return 0
    statement = statement.where(col(Agent.board_id).in_(board_ids))
    result = (await session.exec(statement)).one()
    return int(result)


async def _tasks_in_progress(session: AsyncSession, board_ids: list[UUID]) -> int:
    if not board_ids:
        return 0
    statement = (
        select(func.count())
        .where(col(Task.status) == "in_progress")
        .where(col(Task.board_id).in_(board_ids))
    )
    result = (await session.exec(statement)).one()
    return int(result)


@router.get("/dashboard", response_model=DashboardMetrics)
async def dashboard_metrics(
    range: Literal["24h", "7d"] = Query(default="24h"),
    session: AsyncSession = Depends(get_session),
    ctx: OrganizationContext = Depends(require_org_member),
) -> DashboardMetrics:
    primary = _resolve_range(range)
    comparison = _comparison_range(range)
    board_ids = await list_accessible_board_ids(session, member=ctx.member, write=False)

    throughput_primary = await _query_throughput(session, primary, board_ids)
    throughput_comparison = await _query_throughput(session, comparison, board_ids)
    throughput = DashboardSeriesSet(
        primary=throughput_primary,
        comparison=throughput_comparison,
    )
    cycle_time_primary = await _query_cycle_time(session, primary, board_ids)
    cycle_time_comparison = await _query_cycle_time(session, comparison, board_ids)
    cycle_time = DashboardSeriesSet(
        primary=cycle_time_primary,
        comparison=cycle_time_comparison,
    )
    error_rate_primary = await _query_error_rate(session, primary, board_ids)
    error_rate_comparison = await _query_error_rate(session, comparison, board_ids)
    error_rate = DashboardSeriesSet(
        primary=error_rate_primary,
        comparison=error_rate_comparison,
    )
    wip_primary = await _query_wip(session, primary, board_ids)
    wip_comparison = await _query_wip(session, comparison, board_ids)
    wip = DashboardWipSeriesSet(
        primary=wip_primary,
        comparison=wip_comparison,
    )

    kpis = DashboardKpis(
        active_agents=await _active_agents(session, board_ids),
        tasks_in_progress=await _tasks_in_progress(session, board_ids),
        error_rate_pct=await _error_rate_kpi(session, primary, board_ids),
        median_cycle_time_hours_7d=await _median_cycle_time_7d(session, board_ids),
    )

    return DashboardMetrics(
        range=primary.key,
        generated_at=utcnow(),
        kpis=kpis,
        throughput=throughput,
        cycle_time=cycle_time,
        error_rate=error_rate,
        wip=wip,
    )
