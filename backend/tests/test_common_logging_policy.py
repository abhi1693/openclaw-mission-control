from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from app.core.logging import TRACE_LEVEL, AppLogger, get_logger

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
COMMON_LOGGER_FILE = APP_ROOT / "core" / "logging.py"


def _iter_app_python_files() -> list[Path]:
    files: list[Path] = []
    for path in APP_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def test_common_logger_supports_trace_to_critical_levels() -> None:
    AppLogger.configure(force=True)
    logger = get_logger("tests.common_logging_policy.levels")
    logger.setLevel(TRACE_LEVEL)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(TRACE_LEVEL)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logger.addHandler(handler)

    try:
        logger.log(TRACE_LEVEL, "trace-level")
        logger.debug("debug-level")
        logger.info("info-level")
        logger.warning("warning-level")
        logger.error("error-level")
        logger.critical("critical-level")
    finally:
        logger.removeHandler(handler)
        handler.close()

    lines = [line.strip() for line in stream.getvalue().splitlines() if line.strip()]
    assert lines == [
        "TRACE:trace-level",
        "DEBUG:debug-level",
        "INFO:info-level",
        "WARNING:warning-level",
        "ERROR:error-level",
        "CRITICAL:critical-level",
    ]


def test_backend_app_uses_common_logger() -> None:
    offenders: list[str] = []

    for path in _iter_app_python_files():
        if path == COMMON_LOGGER_FILE:
            continue

        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(BACKEND_ROOT).as_posix()

        if re.search(r"^\s*import\s+logging\b", text, flags=re.MULTILINE):
            offenders.append(f"{rel}: imports logging directly")
        if "logging.getLogger(" in text:
            offenders.append(f"{rel}: calls logging.getLogger directly")

    assert not offenders, "\n".join(offenders)


def test_module_level_loggers_bind_via_get_logger() -> None:
    offenders: list[str] = []
    assignment_pattern = re.compile(r"^\s*logger\s*=\s*(.+)$", flags=re.MULTILINE)

    for path in _iter_app_python_files():
        if path == COMMON_LOGGER_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        for expression in assignment_pattern.findall(text):
            normalized = expression.strip()
            if normalized.startswith("get_logger("):
                continue
            offenders.append(f"{rel}: logger assignment `{normalized}` is not get_logger(...)")

    assert not offenders, "\n".join(offenders)


def test_backend_app_has_all_log_levels_in_use() -> None:
    level_patterns: dict[str, re.Pattern[str]] = {
        "trace": re.compile(
            r"\b(?:self\.)?logger\.log\(\s*TRACE_LEVEL\b|\b(?:self\.)?logger\.trace\("
        ),
        "debug": re.compile(r"\b(?:self\.)?logger\.debug\("),
        "info": re.compile(r"\b(?:self\.)?logger\.info\("),
        "warning": re.compile(r"\b(?:self\.)?logger\.warning\("),
        "error": re.compile(r"\b(?:self\.)?logger\.error\("),
        "critical": re.compile(r"\b(?:self\.)?logger\.critical\("),
    }

    merged_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _iter_app_python_files()
        if path != COMMON_LOGGER_FILE
    )

    missing = [
        name for name, pattern in level_patterns.items() if not pattern.search(merged_source)
    ]
    assert not missing, f"Missing log levels in backend app code: {', '.join(missing)}"
