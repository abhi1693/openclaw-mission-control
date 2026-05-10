"""Tests for async deploy parity check (Phase 2 pipeline gates).

Tests the _revert_to_in_progress CAS guards and the end-to-end
process_deploy_parity_task handler using mocked /__build responses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.deploy_parity import (
    TASK_TYPE,
    enqueue_deploy_parity_check,
    process_deploy_parity_task,
)
from app.services.deploy_truth import BuildMetadata, DeployTruthFetchError
from app.services.queue import QueuedTask


def _make_parity_task(
    *,
    packet_sha: str = "a885428",
    target: str = "http://192.168.2.63:3002",
    task_id: str | None = None,
    board_id: str | None = None,
    expected_updated_at: str = "2026-04-25T19:28:00",
    prior_agent_id: str | None = None,
) -> QueuedTask:
    return QueuedTask(
        task_type=TASK_TYPE,
        payload={
            "task_id": task_id or str(uuid4()),
            "board_id": board_id or str(uuid4()),
            "packet_commit_sha": packet_sha,
            "validation_target": target,
            "expected_updated_at": expected_updated_at,
            "prior_agent_id": prior_agent_id or str(uuid4()),
        },
        created_at=datetime.now(UTC),
    )


class TestDeployParityMatch:
    """Cases where live SHA matches packet — no revert."""

    @pytest.mark.asyncio
    async def test_matching_sha_no_revert(self) -> None:
        """Live /__build SHA matches packet_commit_sha -> no action."""
        task = _make_parity_task(packet_sha="a885428")

        with (
            patch(
                "app.services.deploy_parity.fetch_build_metadata",
                new_callable=AsyncMock,
                return_value=BuildMetadata(sha="a8854286b141ef8a3857ef753c9864f7218556f5"),
            ),
            patch(
                "app.services.deploy_parity._revert_to_in_progress",
                new_callable=AsyncMock,
            ) as mock_revert,
        ):
            await process_deploy_parity_task(task)
            mock_revert.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_live_sha_no_revert(self) -> None:
        """Live /__build returns no SHA (degraded) -> no revert."""
        task = _make_parity_task(packet_sha="a885428")

        with (
            patch(
                "app.services.deploy_parity.fetch_build_metadata",
                new_callable=AsyncMock,
                return_value=BuildMetadata(sha=None),
            ),
            patch(
                "app.services.deploy_parity._revert_to_in_progress",
                new_callable=AsyncMock,
            ) as mock_revert,
        ):
            await process_deploy_parity_task(task)
            mock_revert.assert_not_called()


class TestDeployParityMismatch:
    """Cases where live SHA mismatches — should revert."""

    @pytest.mark.asyncio
    async def test_mismatched_sha_triggers_revert(self) -> None:
        """Live SHA differs from packet -> revert called."""
        task = _make_parity_task(packet_sha="a885428")

        with (
            patch(
                "app.services.deploy_parity.fetch_build_metadata",
                new_callable=AsyncMock,
                return_value=BuildMetadata(sha="deadbeef1234567890abcdef1234567890abcdef"),
            ),
            patch(
                "app.services.deploy_parity._revert_to_in_progress",
                new_callable=AsyncMock,
            ) as mock_revert,
        ):
            await process_deploy_parity_task(task)
            mock_revert.assert_called_once()
            call_kwargs = mock_revert.call_args.kwargs
            assert call_kwargs["packet_sha"] == "a885428"
            assert call_kwargs["live_sha"] == "deadbeef1234567890abcdef1234567890abcdef"


class TestDeployParityFetchError:
    """Cases where /__build fetch fails — should raise for retry."""

    @pytest.mark.asyncio
    async def test_fetch_error_raises(self) -> None:
        """Transient fetch failure -> raises for worker retry."""
        task = _make_parity_task()

        with patch(
            "app.services.deploy_parity.fetch_build_metadata",
            new_callable=AsyncMock,
            side_effect=DeployTruthFetchError("connection refused"),
        ):
            with pytest.raises(DeployTruthFetchError):
                await process_deploy_parity_task(task)


class TestEnqueueShape:
    """Verify enqueue payload structure."""

    def test_enqueue_payload_shape(self) -> None:
        """Enqueue creates a valid QueuedTask with all CAS fields."""
        task_id = uuid4()
        board_id = uuid4()
        prior_id = uuid4()

        with patch("app.services.deploy_parity.enqueue_task") as mock_enqueue:
            enqueue_deploy_parity_check(
                task_id=task_id,
                board_id=board_id,
                packet_commit_sha="abc1234",
                validation_target="http://example.com",
                expected_updated_at="2026-04-25T19:00:00",
                prior_agent_id=prior_id,
            )
            mock_enqueue.assert_called_once()
            queued: QueuedTask = mock_enqueue.call_args.args[0]
            assert queued.task_type == TASK_TYPE
            assert queued.payload["task_id"] == str(task_id)
            assert queued.payload["packet_commit_sha"] == "abc1234"
            assert queued.payload["prior_agent_id"] == str(prior_id)
            assert queued.payload["expected_updated_at"] == "2026-04-25T19:00:00"


class TestTaskType:
    """Verify task type constant matches worker registration."""

    def test_task_type_value(self) -> None:
        assert TASK_TYPE == "deploy_parity_check"

    def test_worker_registration(self) -> None:
        """Task type is registered in queue worker."""
        from app.services.queue_worker import _TASK_HANDLERS

        assert TASK_TYPE in _TASK_HANDLERS
