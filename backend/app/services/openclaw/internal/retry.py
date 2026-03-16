"""Internal gateway retry helpers for coordination flows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.services.openclaw.constants import (
    _COORDINATION_GATEWAY_BASE_DELAY_S,
    _COORDINATION_GATEWAY_MAX_DELAY_S,
    _COORDINATION_GATEWAY_TIMEOUT_S,
    _NON_TRANSIENT_GATEWAY_ERROR_MARKERS,
    _SECURE_RANDOM,
    _TRANSIENT_GATEWAY_ERROR_MARKERS,
)
from app.services.openclaw.gateway_rpc import OpenClawGatewayError

_T = TypeVar("_T")


def _is_transient_gateway_error(exc: Exception) -> bool:
    if not isinstance(exc, OpenClawGatewayError):
        return False
    message = str(exc).lower()
    if not message:
        return False
    if any(marker in message for marker in _NON_TRANSIENT_GATEWAY_ERROR_MARKERS):
        return False
    return ("503" in message and "websocket" in message) or any(
        marker in message for marker in _TRANSIENT_GATEWAY_ERROR_MARKERS
    )


def _gateway_timeout_message(
    exc: OpenClawGatewayError,
    *,
    timeout_s: float,
    context: str,
) -> str:
    rounded_timeout = int(timeout_s)
    timeout_text = f"{rounded_timeout} seconds"
    if rounded_timeout >= 120:
        timeout_text = f"{rounded_timeout // 60} minutes"
    return f"Gateway unreachable after {timeout_text} ({context} timeout). Last error: {exc}"


class GatewayBackoff:
    """Exponential backoff with jitter for transient gateway errors."""

    def __init__(
        self,
        *,
        timeout_s: float = 10 * 60,
        base_delay_s: float = 0.75,
        max_delay_s: float = 30.0,
        jitter: float = 0.2,
        timeout_context: str = "gateway operation",
    ) -> None:
        self._timeout_s = timeout_s
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._jitter = jitter
        self._timeout_context = timeout_context
        self._delay_s = base_delay_s

    def reset(self) -> None:
        self._delay_s = self._base_delay_s

    @staticmethod
    async def _attempt(
        fn: Callable[[], Awaitable[_T]],
    ) -> tuple[_T | None, OpenClawGatewayError | None]:
        try:
            return await fn(), None
        except OpenClawGatewayError as exc:
            return None, exc

    async def run(self, fn: Callable[[], Awaitable[_T]]) -> _T:
        deadline_s = asyncio.get_running_loop().time() + self._timeout_s
        while True:
            value, error = await self._attempt(fn)
            if error is not None:
                exc = error
                if not _is_transient_gateway_error(exc):
                    raise exc
                now = asyncio.get_running_loop().time()
                remaining = deadline_s - now
                if remaining <= 0:
                    raise TimeoutError(
                        _gateway_timeout_message(
                            exc,
                            timeout_s=self._timeout_s,
                            context=self._timeout_context,
                        ),
                    ) from exc

                sleep_s = min(self._delay_s, remaining)
                if self._jitter:
                    sleep_s *= 1.0 + _SECURE_RANDOM.uniform(
                        -self._jitter,
                        self._jitter,
                    )
                sleep_s = max(0.0, min(sleep_s, remaining))
                await asyncio.sleep(sleep_s)
                self._delay_s = min(self._delay_s * 2.0, self._max_delay_s)
                continue
            self.reset()
            if value is None:
                msg = "Gateway retry produced no value without an error"
                raise RuntimeError(msg)
            return value


async def with_coordination_gateway_retry(fn: Callable[[], Awaitable[_T]]) -> _T:
    """Run a gateway call under coordination retry policy."""
    backoff = GatewayBackoff(
        timeout_s=_COORDINATION_GATEWAY_TIMEOUT_S,
        base_delay_s=_COORDINATION_GATEWAY_BASE_DELAY_S,
        max_delay_s=_COORDINATION_GATEWAY_MAX_DELAY_S,
        jitter=0.15,
        timeout_context="gateway coordination",
    )
    return await backoff.run(fn)
