"""Unit tests for ``mc_hooks.py``.

Validates the offline pieces — argparse wiring, env-var fallback,
hook-token file resolution, stdin-message handling, and the HTTP
plumbing layer (with ``urllib.request.urlopen`` stubbed). The script
wraps the OpenClaw inbound hooks endpoint (``POST /hooks/wake`` and
``POST /hooks/agent``) so MC operator cron / scripts can fire one-shot
agent runs without hand-rolled curl.

Per ``feedback_tdd_discipline``: this file expresses the contracts the
script MUST satisfy. The script may change so long as these assertions
still pass.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mc_hooks.py"
_spec = importlib.util.spec_from_file_location("mc_hooks", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["mc_hooks"] = _module
_spec.loader.exec_module(_module)

build_parser = _module.build_parser
main = _module.main
HttpError = _module.HttpError


# --- argparse wiring ---


class TestArgparse:
    def test_no_subcommand_errors(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_wake_requires_text(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["wake"])

    def test_wake_minimal(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["wake", "--text", "hello"])
        assert args.command == "wake"
        assert args.text == "hello"
        assert args.mode == "next-heartbeat"  # default

    def test_wake_mode_constrained(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["wake", "--text", "x", "--mode", "bogus"])

    def test_wake_mode_now(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["wake", "--text", "x", "--mode", "now"])
        assert args.mode == "now"

    def test_agent_requires_message(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["agent"])

    def test_agent_minimal(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "--message", "ping"])
        assert args.command == "agent"
        assert args.message == "ping"

    def test_agent_full_payload(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "agent",
            "--message", "ping",
            "--name", "smoke-test",
            "--agent-id", "lead-x",
            "--model", "openai-codex/gpt-5.4",
            "--timeout-seconds", "60",
        ])
        assert args.name == "smoke-test"
        assert args.agent_id == "lead-x"
        assert args.model == "openai-codex/gpt-5.4"
        assert args.timeout_seconds == 60


# --- token / base-url resolution ---


class TestTokenResolution:
    def test_explicit_flag_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "from-env")
        token = _module._resolve_token(_namespace(token="from-flag"))
        assert token == "from-flag"

    def test_env_var_used_when_flag_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "from-env")
        token = _module._resolve_token(_namespace(token=None))
        assert token == "from-env"

    def test_token_file_used_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_HOOK_TOKEN", raising=False)
        env_file = tmp_path / "env"
        env_file.write_text("OPENCLAW_HOOK_TOKEN=from-file-abc\n", encoding="utf-8")
        monkeypatch.setattr(_module, "DEFAULT_TOKEN_FILE", str(env_file))
        token = _module._resolve_token(_namespace(token=None))
        assert token == "from-file-abc"

    def test_missing_token_exits_2(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("OPENCLAW_HOOK_TOKEN", raising=False)
        monkeypatch.setattr(_module, "DEFAULT_TOKEN_FILE", str(tmp_path / "no-such"))
        with pytest.raises(SystemExit) as exc:
            _module._resolve_token(_namespace(token=None))
        assert "OPENCLAW_HOOK_TOKEN" in str(exc.value)

    def test_token_file_other_keys_ignored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_HOOK_TOKEN", raising=False)
        env_file = tmp_path / "env"
        env_file.write_text(
            "# comment\nOTHER=irrelevant\nOPENCLAW_HOOK_TOKEN=t\nEXTRA=x\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "DEFAULT_TOKEN_FILE", str(env_file))
        assert _module._resolve_token(_namespace(token=None)) == "t"


class TestBaseUrlResolution:
    def test_explicit_flag_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_URL", "http://from-env")
        url = _module._resolve_base_url(_namespace(base_url="http://from-flag"))
        assert url == "http://from-flag"

    def test_env_var_used_when_flag_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_URL", "http://from-env")
        url = _module._resolve_base_url(_namespace(base_url=None))
        assert url == "http://from-env"

    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENCLAW_HOOK_URL", raising=False)
        url = _module._resolve_base_url(_namespace(base_url=None))
        assert url == _module.DEFAULT_BASE_URL

    def test_trailing_slash_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        url = _module._resolve_base_url(_namespace(base_url="http://x:18789////"))
        assert url == "http://x:18789"


# --- stdin message ---


class TestStdinMessage:
    def test_dash_reads_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("body from stdin\n"))
        ns = _namespace(message="-")
        _module._resolve_message_stdin(ns)
        assert ns.message == "body from stdin"

    def test_dash_strips_trailing_newlines_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("multi\nline\n  body\n\n"))
        ns = _namespace(message="-")
        _module._resolve_message_stdin(ns)
        assert ns.message == "multi\nline\n  body"

    def test_non_dash_unchanged(self) -> None:
        ns = _namespace(message="literal")
        _module._resolve_message_stdin(ns)
        assert ns.message == "literal"

    def test_empty_stdin_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        with pytest.raises(SystemExit):
            _module._resolve_message_stdin(_namespace(message="-"))


# --- HTTP layer ---


class _StubResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> "_StubResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class TestHttpFlow:
    def test_wake_posts_correct_payload(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "tok")
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["auth"] = req.headers.get("Authorization")
            return _StubResponse(b'{"ok":true,"mode":"now"}')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            rc = main([
                "--base-url", "http://test:18789",
                "wake", "--text", "external trigger", "--mode", "now",
            ])

        assert rc == 0
        assert captured["url"] == "http://test:18789/hooks/wake"
        assert captured["method"] == "POST"
        assert captured["auth"] == "Bearer tok"
        assert json.loads(captured["data"]) == {"text": "external trigger", "mode": "now"}
        out = capsys.readouterr().out
        assert json.loads(out) == {"ok": True, "mode": "now"}

    def test_agent_posts_full_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "tok")
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = req.data
            return _StubResponse(b'{"ok":true,"runId":"r-1"}')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            rc = main([
                "--base-url", "http://test:18789",
                "agent",
                "--message", "summarize",
                "--name", "smoke",
                "--agent-id", "lead-x",
                "--model", "openai-codex/gpt-5.4",
                "--timeout-seconds", "30",
            ])

        assert rc == 0
        assert captured["url"] == "http://test:18789/hooks/agent"
        body = json.loads(captured["data"])
        assert body["message"] == "summarize"
        assert body["name"] == "smoke"
        assert body["agentId"] == "lead-x"
        assert body["model"] == "openai-codex/gpt-5.4"
        assert body["timeoutSeconds"] == 30

    def test_agent_omits_unset_optional_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Optional flags shouldn't show up as ``null`` in the payload — they
        should be omitted entirely so the gateway picks its own defaults."""
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "tok")
        captured: dict[str, Any] = {}

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            return _StubResponse(b'{"ok":true,"runId":"r-1"}')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            main(["--base-url", "http://test", "agent", "--message", "hi"])

        body = json.loads(captured["data"])
        assert body == {"message": "hi"}

    def test_401_exits_2_with_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "tok")

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", hdrs={},  # type: ignore[arg-type]
                fp=io.BytesIO(b"Unauthorized"),
            )

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            rc = main(["--base-url", "http://test", "wake", "--text", "x"])

        assert rc == 2
        err = capsys.readouterr().err
        assert "HTTP 401" in err

    def test_network_error_exits_3(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "tok")

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("dns failure")

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            rc = main(["--base-url", "http://test", "wake", "--text", "x"])

        assert rc == 3
        err = capsys.readouterr().err
        assert "dns failure" in err.lower() or "network" in err.lower()


# --- helpers ---


def _namespace(**kwargs: Any) -> Any:
    """Build an argparse.Namespace-like object with arbitrary attributes."""
    import argparse
    ns = argparse.Namespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns
