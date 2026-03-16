"""ASGI middleware for configurable security response headers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Inject configured security headers into every HTTP response."""

    _X_CONTENT_TYPE_OPTIONS = b"x-content-type-options"
    _X_FRAME_OPTIONS = b"x-frame-options"
    _REFERRER_POLICY = b"referrer-policy"
    _PERMISSIONS_POLICY = b"permissions-policy"

    def __init__(
        self,
        app: ASGIApp,
        *,
        x_content_type_options: str = "",
        x_frame_options: str = "",
        referrer_policy: str = "",
        permissions_policy: str = "",
    ) -> None:
        self._app = app
        self._configured_headers = self._build_configured_headers(
            x_content_type_options=x_content_type_options,
            x_frame_options=x_frame_options,
            referrer_policy=referrer_policy,
            permissions_policy=permissions_policy,
        )

    @classmethod
    def _build_configured_headers(
        cls,
        *,
        x_content_type_options: str,
        x_frame_options: str,
        referrer_policy: str,
        permissions_policy: str,
    ) -> tuple[tuple[bytes, bytes, bytes], ...]:
        configured: list[tuple[bytes, bytes, bytes]] = []
        for header_name, value in (
            (cls._X_CONTENT_TYPE_OPTIONS, x_content_type_options),
            (cls._X_FRAME_OPTIONS, x_frame_options),
            (cls._REFERRER_POLICY, referrer_policy),
            (cls._PERMISSIONS_POLICY, permissions_policy),
        ):
            normalized = value.strip()
            if not normalized:
                continue
            configured.append(
                (
                    header_name.lower(),
                    header_name,
                    normalized.encode("latin-1"),
                )
            )
        return tuple(configured)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Append configured security headers unless already present."""
        if scope["type"] != "http" or not self._configured_headers:
            await self._app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Starlette uses `list[tuple[bytes, bytes]]` for raw headers.
                headers: list[tuple[bytes, bytes]] = message.setdefault("headers", [])
                existing = {key.lower() for key, _ in headers}
                for key_lower, key, value in self._configured_headers:
                    if key_lower not in existing:
                        headers.append((key, value))
                        existing.add(key_lower)
            await send(message)

        await self._app(scope, receive, send_with_security_headers)
