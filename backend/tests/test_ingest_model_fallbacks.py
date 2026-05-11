"""Unit tests for the model_fallback ingestion script.

Validates the pure-functional pieces of ``ingest_model_fallbacks.py``:
gateway-log parsing, evidence-dict shape, idempotency hashing, and the
``ACP_EXECUTOR_STARTED`` marker regex used to correlate run UUIDs to
task ids. HTTP-side functions are exercised via integration tests
elsewhere; this file deliberately stays offline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load the script as a module without depending on package layout.
# Register in sys.modules BEFORE exec — Python 3.13's @dataclass decorator
# walks sys.modules to resolve the cls.__module__ owner, and a missing
# entry crashes with ``'NoneType' object has no attribute '__dict__'``.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ingest_model_fallbacks.py"
_spec = importlib.util.spec_from_file_location("ingest_model_fallbacks", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["ingest_model_fallbacks"] = _module
_spec.loader.exec_module(_module)

FallbackEvent = _module.FallbackEvent
parse_gateway_log = _module.parse_gateway_log
EXECUTOR_STARTED_RE = _module.EXECUTOR_STARTED_RE
TASK_ID_FROM_LABEL_RE = _module.TASK_ID_FROM_LABEL_RE
load_state = _module.load_state
save_state = _module.save_state


# --- gateway-log parser ---


def _write_log_lines(tmp_path: Path, lines: list[dict[str, object]]) -> Path:
    path = tmp_path / "openclaw.log"
    with path.open("w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")
    return path


def test_parse_yields_only_model_fallback_events(tmp_path: Path) -> None:
    log = _write_log_lines(
        tmp_path,
        [
            {
                "0": "{}",
                "1": {"event": "something_else", "runId": "abc"},
                "time": "2026-04-30T12:00:00.000Z",
            },
            {
                "0": "{}",
                "1": {
                    "event": "model_fallback_decision",
                    "runId": "11111111-2222-3333-4444-555555555555",
                    "fallbackStepFromModel": "ollama/qwen3.5:cloud",
                    "fallbackStepToModel": "ollama/glm-5.1:cloud",
                    "fallbackStepFromFailureReason": "timeout",
                    "fallbackStepChainPosition": 1,
                    "fallbackStepFinalOutcome": "next_fallback",
                },
                "_meta": {"name": '{"subsystem":"model-fallback/decision"}'},
                "time": "2026-04-30T12:01:00.000Z",
            },
        ],
    )
    events = list(parse_gateway_log(log))
    assert len(events) == 1
    event = events[0]
    assert event.run_id == "11111111-2222-3333-4444-555555555555"
    assert event.from_model == "ollama/qwen3.5:cloud"
    assert event.to_model == "ollama/glm-5.1:cloud"
    assert event.reason == "timeout"
    assert event.chain_position == 1
    assert event.final_outcome == "next_fallback"


def test_parse_tolerates_non_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "openclaw.log"
    with path.open("w") as fh:
        fh.write("Banner: starting up\n")
        fh.write("not json at all\n")
        fh.write(
            json.dumps(
                {
                    "0": "{}",
                    "1": {
                        "event": "model_fallback_decision",
                        "runId": "abcd1234-5678-90ef-abcd-ef1234567890",
                        "fallbackStepFromModel": "x",
                        "fallbackStepToModel": "y",
                        "fallbackStepFromFailureReason": "billing",
                    },
                    "time": "2026-04-30T12:00:00.000Z",
                }
            )
            + "\n"
        )
    events = list(parse_gateway_log(path))
    assert len(events) == 1
    assert events[0].reason == "billing"


def test_parse_skips_events_without_run_id(tmp_path: Path) -> None:
    log = _write_log_lines(
        tmp_path,
        [
            {
                "0": "{}",
                "1": {
                    "event": "model_fallback_decision",
                    "fallbackStepFromModel": "x",
                    "fallbackStepToModel": "y",
                },
                "time": "2026-04-30T12:00:00.000Z",
            },
        ],
    )
    assert list(parse_gateway_log(log)) == []


# --- evidence dict shape ---


class TestEvidence:
    def test_includes_required_keys_for_mc_validator(self) -> None:
        event = FallbackEvent(
            run_id="r1",
            timestamp="2026-04-30T12:00:00.000Z",
            from_model="ollama/qwen3.5:cloud",
            to_model="ollama/glm-5.1:cloud",
            reason="timeout",
            chain_position=1,
            final_outcome="next_fallback",
            raw_subsystem="model-fallback/decision",
        )
        ev = event.evidence()
        # MC's MODEL_FALLBACK_REQUIRED_EVIDENCE_KEYS check:
        for key in ("from_model", "to_model", "reason"):
            assert key in ev
            assert ev[key] is not None

    def test_falls_back_to_unknown_when_fields_missing(self) -> None:
        event = FallbackEvent(
            run_id="r1",
            timestamp="2026-04-30T12:00:00.000Z",
            from_model=None,
            to_model=None,
            reason=None,
            chain_position=None,
            final_outcome=None,
            raw_subsystem="model-fallback/decision",
        )
        ev = event.evidence()
        assert ev["from_model"] == "unknown"
        assert ev["to_model"] == "none"
        assert ev["reason"] == "unknown"


# --- idempotency hash ---


class TestIdempotencyHash:
    def _event(self, **overrides: object) -> FallbackEvent:
        defaults = {
            "run_id": "r1",
            "timestamp": "2026-04-30T12:00:00.000Z",
            "from_model": "a",
            "to_model": "b",
            "reason": "timeout",
            "chain_position": 1,
            "final_outcome": "next_fallback",
            "raw_subsystem": "model-fallback/decision",
        }
        defaults.update(overrides)
        return FallbackEvent(**defaults)  # type: ignore[arg-type]

    def test_same_inputs_yield_same_hash(self) -> None:
        a = self._event()
        b = self._event()
        assert a.idempotency_hash() == b.idempotency_hash()

    def test_different_run_id_changes_hash(self) -> None:
        a = self._event()
        b = self._event(run_id="r2")
        assert a.idempotency_hash() != b.idempotency_hash()

    def test_different_chain_position_changes_hash(self) -> None:
        a = self._event(chain_position=1)
        b = self._event(chain_position=2)
        assert a.idempotency_hash() != b.idempotency_hash()


# --- ACP_EXECUTOR_STARTED regex ---


class TestExecutorStartedRegex:
    def test_matches_canonical_marker(self) -> None:
        message = (
            "ACP_EXECUTOR_STARTED child=agent:claude:acp:74c88880-9188-4cb3-a243-9c4504d7628f "
            "run=ec09e033-c5b4-48b2-9dd4-40cd5f395279 label=mc-task-c8c664d2-impl-a1"
        )
        match = EXECUTOR_STARTED_RE.search(message)
        assert match is not None
        assert match.group("run") == "ec09e033-c5b4-48b2-9dd4-40cd5f395279"
        assert match.group("label") == "mc-task-c8c664d2-impl-a1"

    def test_extracts_task_id_from_label(self) -> None:
        label = "mc-task-c8c664d2-0664-4c1e-8c9e-be33a502b71c-impl-a1"
        match = TASK_ID_FROM_LABEL_RE.match(label)
        assert match is not None
        assert match.group("task_id") == "c8c664d2-0664-4c1e-8c9e-be33a502b71c"

    def test_handles_label_with_codex_suffix(self) -> None:
        message = (
            "ACP_EXECUTOR_STARTED child=agent:codex:acp:30ba3b79-b8de-41d4-8c32-dd080dd92b83 "
            "run=691d027f-667a-4270-9f96-d0421476963a "
            "label=mc-task-9ac55b51-9fc2-4a99-9638-5ce7a9a55dfe-impl-codex-a2"
        )
        match = EXECUTOR_STARTED_RE.search(message)
        assert match is not None
        assert match.group("run") == "691d027f-667a-4270-9f96-d0421476963a"
        assert match.group("label") == (
            "mc-task-9ac55b51-9fc2-4a99-9638-5ce7a9a55dfe-impl-codex-a2"
        )

    def test_matches_review_stage_label(self) -> None:
        """Codex F5: regex must accept non-impl stage suffixes too."""
        message = (
            "ACP_EXECUTOR_STARTED child=agent:claude:acp:abc "
            "run=12345678-1234-1234-1234-123456789abc "
            "label=mc-task-deadbeef-dead-beef-dead-beefdeadbeef-review-a1"
        )
        match = EXECUTOR_STARTED_RE.search(message)
        assert match is not None
        assert match.group("run") == "12345678-1234-1234-1234-123456789abc"
        label_match = TASK_ID_FROM_LABEL_RE.match(match.group("label"))
        assert label_match is not None
        assert label_match.group("task_id") == "deadbeef-dead-beef-dead-beefdeadbeef"

    def test_matches_validation_stage_label(self) -> None:
        """Codex F5: validation-stage labels must extract task_id correctly."""
        message = (
            "ACP_EXECUTOR_STARTED child=agent:codex:acp:xyz "
            "run=abcd1234-abcd-abcd-abcd-abcdef123456 "
            "label=mc-task-cafebabe-cafe-babe-cafe-babecafebabe-validation-a2"
        )
        match = EXECUTOR_STARTED_RE.search(message)
        assert match is not None
        label_match = TASK_ID_FROM_LABEL_RE.match(match.group("label"))
        assert label_match is not None
        assert label_match.group("task_id") == "cafebabe-cafe-babe-cafe-babecafebabe"

    def test_existing_impl_label_still_matches(self) -> None:
        """Regression: F5 fix must not break the impl-* path that prod uses."""
        label = "mc-task-c8c664d2-0664-4c1e-8c9e-be33a502b71c-impl-a1"
        match = TASK_ID_FROM_LABEL_RE.match(label)
        assert match is not None
        assert match.group("task_id") == "c8c664d2-0664-4c1e-8c9e-be33a502b71c"

    def test_finds_multiple_markers_in_one_comment(self) -> None:
        message = (
            "First retry: ACP_EXECUTOR_STARTED child=agent:claude:acp:aaa run=11111111-1111-1111-1111-111111111111 label=mc-task-aaa-aaa-impl-a1\n"
            "Second retry: ACP_EXECUTOR_STARTED child=agent:claude:acp:bbb run=22222222-2222-2222-2222-222222222222 label=mc-task-aaa-aaa-impl-a2\n"
        )
        runs = [m.group("run") for m in EXECUTOR_STARTED_RE.finditer(message)]
        assert runs == [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]


# --- state file roundtrip ---


class TestStateFile:
    def test_load_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        assert load_state(tmp_path / "absent.json") == set()

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        state_file = tmp_path / "nested" / "state.json"
        save_state(state_file, {"abc", "def"})
        assert load_state(state_file) == {"abc", "def"}

    def test_load_returns_empty_on_corrupt_state(self, tmp_path: Path) -> None:
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("{not valid json")
        assert load_state(state_file) == set()

    def test_save_is_atomic_via_tmp_replace(self, tmp_path: Path) -> None:
        """Codex F6: writes go through a tmp file + os.replace.

        Verify by stubbing os.replace to fail mid-write — the original
        state file (if any) must remain intact, and no .tmp leftover
        survives.
        """
        import os as os_mod
        from unittest import mock

        state_file = tmp_path / "state.json"
        state_file.write_text(__import__("json").dumps({"posted_hashes": ["original"]}))
        with mock.patch.object(os_mod, "replace", side_effect=OSError("simulated fs error")):
            with pytest.raises(OSError):
                save_state(state_file, {"new1", "new2"})
        # Original state preserved
        assert load_state(state_file) == {"original"}
        # No tmp leftover in the dir
        leftovers = list(tmp_path.glob(state_file.name + ".*.tmp"))
        assert leftovers == [], f"tmp leftovers not cleaned up: {leftovers}"


# --- pagination (Codex F4) ---


class TestPaginateGet:
    """Verify _paginate_get walks offset until total exhausted or empty page.

    The bug fixed by F4: prior version made a single ``?limit=200`` fetch
    with no offset loop, silently dropping any items beyond the first
    page.
    """

    def _stub_pages(
        self,
        page_results: list[dict[str, object]],
    ) -> object:
        """Return a urlopen replacement that serves successive pages."""
        call_count = {"i": 0}
        captured_urls: list[str] = []

        class _Resp:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *exc: object) -> None:
                pass

            def read(self) -> bytes:
                return self._body

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            idx = call_count["i"]
            call_count["i"] = idx + 1
            if idx >= len(page_results):
                return _Resp(b'{"items": [], "total": 0}')
            return _Resp(__import__("json").dumps(page_results[idx]).encode())

        return fake_urlopen, captured_urls, call_count

    def test_walks_offset_until_total_exhausted(self) -> None:
        from unittest import mock

        # Use total=400 to force a second page (page size in script is 200).
        # First page returns 200 items; second page returns the remaining 200.
        page_one_items = [{"id": f"t{i}"} for i in range(200)]
        page_two_items = [{"id": f"t{i}"} for i in range(200, 400)]
        pages = [
            {"items": page_one_items, "total": 400},
            {"items": page_two_items, "total": 400},
        ]
        fake_urlopen, urls, _ = self._stub_pages(pages)
        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            items = list(
                _module._paginate_get(
                    base_url="http://test",
                    path="/api/v1/boards/b/tasks",
                    token="tok",
                )
            )
        # Got all 400 across both pages — F4 fix: prior version would
        # have stopped after page 1 with only 200 items.
        assert len(items) == 400
        assert items[0]["id"] == "t0"
        assert items[-1]["id"] == "t399"
        # Issued exactly 2 requests
        assert len(urls) == 2
        assert "offset=0" in urls[0]
        assert "offset=200" in urls[1]

    def test_stops_on_empty_items(self) -> None:
        from unittest import mock

        pages = [
            {"items": [{"id": "t1"}], "total": 999},
            {"items": [], "total": 999},
        ]
        fake_urlopen, urls, _ = self._stub_pages(pages)
        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            items = list(
                _module._paginate_get(
                    base_url="http://test",
                    path="/api/v1/boards/b/tasks",
                    token="tok",
                )
            )
        assert [t["id"] for t in items] == ["t1"]
        assert len(urls) == 2  # one fetch + one empty page that signals stop

    def test_handles_list_response_without_envelope(self) -> None:
        """Some endpoints return a bare list, not {items, total} envelope."""
        from unittest import mock

        class _Resp:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *exc: object) -> None:
                pass

            def read(self) -> bytes:
                return self._body

        def fake_urlopen(req, timeout=None):
            return _Resp(b'[{"id": "a"}, {"id": "b"}]')

        with mock.patch.object(_module.urllib.request, "urlopen", fake_urlopen):
            items = list(
                _module._paginate_get(
                    base_url="http://test",
                    path="/test",
                    token="tok",
                )
            )
        # List shape returns once; no infinite loop
        assert [t["id"] for t in items] == ["a", "b"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
