"""Entry-point + env-file tests for ``mc_gateway_subscriber.__main__``.

Per ``feedback_tdd_discipline``: contracts encoded as failing
assertions FIRST, then implementation written to satisfy them.

Out of scope here: actual WS lifecycle (covered in
``test_mc_gateway_subscriber.py``). These tests cover the operator-
facing wiring: env resolution, config validation, exit codes, signal
handling.
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from app.services.mc_gateway_subscriber import __main__ as entry


# --- env-file parsing (mirrors mc_hooks.py contracts) ---


class TestEnvFileLoader:
    def test_reads_required_keys(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text(
            "OPENCLAW_GATEWAY_WS_URL=ws://192.168.2.60:18789/ws\n"
            "OPENCLAW_GATEWAY_TOKEN=abc123\n",
            encoding="utf-8",
        )
        cfg = entry.load_env_file(str(env_file))
        assert cfg == {
            "OPENCLAW_GATEWAY_WS_URL": "ws://192.168.2.60:18789/ws",
            "OPENCLAW_GATEWAY_TOKEN": "abc123",
        }

    def test_strips_inline_comment_on_unquoted_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text(
            "OPENCLAW_GATEWAY_TOKEN=abc123 # prod token\n", encoding="utf-8"
        )
        cfg = entry.load_env_file(str(env_file))
        assert cfg["OPENCLAW_GATEWAY_TOKEN"] == "abc123"

    def test_preserves_inline_hash_inside_quoted_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text(
            'OPENCLAW_GATEWAY_TOKEN="abc#123"\n', encoding="utf-8"
        )
        cfg = entry.load_env_file(str(env_file))
        assert cfg["OPENCLAW_GATEWAY_TOKEN"] == "abc#123"

    def test_strips_quotes(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text(
            'OPENCLAW_GATEWAY_TOKEN="quoted"\nOPENCLAW_GATEWAY_WS_URL=\'single\'\n',
            encoding="utf-8",
        )
        cfg = entry.load_env_file(str(env_file))
        assert cfg["OPENCLAW_GATEWAY_TOKEN"] == "quoted"
        assert cfg["OPENCLAW_GATEWAY_WS_URL"] == "single"

    def test_handles_crlf(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_bytes(b"OPENCLAW_GATEWAY_TOKEN=abc\r\n")
        cfg = entry.load_env_file(str(env_file))
        assert cfg["OPENCLAW_GATEWAY_TOKEN"] == "abc"
        assert "\r" not in cfg["OPENCLAW_GATEWAY_TOKEN"]

    def test_skips_comment_lines_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text(
            "# header\n\nOPENCLAW_GATEWAY_TOKEN=abc\n# trailing\n",
            encoding="utf-8",
        )
        cfg = entry.load_env_file(str(env_file))
        assert cfg == {"OPENCLAW_GATEWAY_TOKEN": "abc"}

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert entry.load_env_file(str(tmp_path / "nonexistent")) == {}


# --- config resolution: env var > env file > error ---


class TestConfigResolution:
    def test_env_var_wins_over_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("OPENCLAW_GATEWAY_TOKEN=from-file\n", encoding="utf-8")
        monkeypatch.setenv("OPENCLAW_GATEWAY_WS_URL", "ws://from-env")
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "from-env")
        cfg = entry.resolve_config(env_file_path=str(env_file))
        assert cfg.url == "ws://from-env"
        assert cfg.token == "from-env"

    def test_file_used_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_GATEWAY_WS_URL", raising=False)
        monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
        env_file = tmp_path / "env"
        env_file.write_text(
            "OPENCLAW_GATEWAY_WS_URL=ws://from-file\n"
            "OPENCLAW_GATEWAY_TOKEN=from-file\n",
            encoding="utf-8",
        )
        cfg = entry.resolve_config(env_file_path=str(env_file))
        assert cfg.url == "ws://from-file"
        assert cfg.token == "from-file"

    def test_subscriptions_default_node_invoke_request(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Per design Decision 3 — v1 ships with the smallest scope. The
        existing gateway protocol delivers ACP child completion via
        ``node.invoke.request`` events. Default subscription = the RPC
        that produces those events.
        """
        monkeypatch.setenv("OPENCLAW_GATEWAY_WS_URL", "ws://x")
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "t")
        cfg = entry.resolve_config(env_file_path=str(tmp_path / "no-such"))
        # Subscriber sends a ``sessions.subscribe`` RPC to start the
        # event stream; the events of interest (sessions.changed,
        # node.invoke.request, etc.) flow through that subscription.
        assert "sessions.subscribe" in cfg.subscriptions

    def test_missing_url_exits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_GATEWAY_WS_URL", raising=False)
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "t")
        with pytest.raises(SystemExit) as exc:
            entry.resolve_config(env_file_path=str(tmp_path / "no-such"))
        assert "OPENCLAW_GATEWAY_WS_URL" in str(exc.value)

    def test_missing_token_exits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OPENCLAW_GATEWAY_WS_URL", "ws://x")
        monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            entry.resolve_config(env_file_path=str(tmp_path / "no-such"))
        assert "OPENCLAW_GATEWAY_TOKEN" in str(exc.value)


# --- main() lifecycle: signal handlers stop the worker cleanly ---


class TestMainLifecycle:
    @pytest.mark.asyncio
    async def test_run_async_stops_when_event_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``run_async(stop, config)`` returns when the stop event is set,
        without raising.
        """
        # Stub the Subscriber so we don't need a live WS server.
        captured: dict[str, Any] = {}

        class _StubSubscriber:
            def __init__(self, **kwargs: Any) -> None:
                captured["kwargs"] = kwargs

            def on(self, *args: Any, **kwargs: Any) -> None:
                captured.setdefault("on_calls", []).append((args, kwargs))

            async def run(self, stop: asyncio.Event) -> None:
                await stop.wait()

        monkeypatch.setattr(entry, "Subscriber", _StubSubscriber)

        cfg = entry.SubscriberConfig(
            url="ws://x",
            token="t",
            subscriptions=("sessions.subscribe",),
        )
        stop = asyncio.Event()

        async def stopper() -> None:
            await asyncio.sleep(0.05)
            stop.set()

        await asyncio.gather(entry.run_async(stop, cfg), stopper())
        assert captured["kwargs"]["url"] == "ws://x"
        assert captured["kwargs"]["token"] == "t"
        assert captured["kwargs"]["subscriptions"] == ("sessions.subscribe",)
