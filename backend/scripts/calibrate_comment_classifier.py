"""Run the comment classifier against a healthy and a pathological corpus.

Part of the pre-merge gate defined in
``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
section 2 (pre-merge healthy-corpus calibration gate):

- healthy corpus flagged rate must be <= 15% per rule per packet type
- pathological corpus flagged rate must land between 30% and 45%

Expected corpus CSV columns (one row per comment):

    created_at,agent_name,task_id,review_packet_type,message

Timestamps must be ISO-8601. ``review_packet_type`` may be blank to mean
"unset (treat as strict)". ``message`` is the raw comment body.

Usage:

    uv run python scripts/calibrate_comment_classifier.py \\
        --healthy tests/fixtures/comments_healthy.csv \\
        --pathological tests/fixtures/comments_pathological.csv

The script writes a JSON summary to stdout and exits non-zero when any
rule on any corpus violates its gate. CI can bind this to a pre-merge
check.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.comment_classifier import ClassifierFlag, classify

HEALTHY_MAX_FLAG_RATE = 0.15

# Per-rule pathological targets from amendment §9. ±5% band on the
# spec's measured rates (32% ack-only, 7% near-duplicate). The two
# rules have very different expected prevalences, so a single shared
# band overshoots one and undershoots the other.
PATHOLOGICAL_TARGETS: dict[str, tuple[float, float]] = {
    "ack_only": (0.27, 0.37),
    "near_duplicate": (0.02, 0.12),
}


@dataclass(frozen=True)
class CorpusRow:
    created_at: datetime
    agent_name: str
    task_id: str
    packet_type: str | None
    message: str


def _parse_row(row: dict[str, str]) -> CorpusRow:
    raw_packet = (row.get("review_packet_type") or "").strip()
    return CorpusRow(
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        agent_name=row.get("agent_name", ""),
        task_id=row.get("task_id", ""),
        packet_type=raw_packet or None,
        message=row.get("message", ""),
    )


def load_corpus(path: Path) -> list[CorpusRow]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [_parse_row(row) for row in reader]


def _classify_row(row: CorpusRow, prior: CorpusRow | None) -> list[ClassifierFlag]:
    prior_message = prior.message if prior is not None else None
    prior_created_at = prior.created_at if prior is not None else None
    return classify(
        row.message,
        packet_type=row.packet_type,
        prior_comment=prior_message,
        prior_comment_created_at=prior_created_at,
        now=row.created_at,
    )


def classify_corpus(rows: Iterable[CorpusRow]) -> list[tuple[CorpusRow, list[ClassifierFlag]]]:
    """Classify chronologically, feeding each comment its immediate prior
    from the same (agent, task) bucket so near-duplicate detection sees
    realistic prior context.
    """

    ordered = sorted(rows, key=lambda r: r.created_at)
    last_by_bucket: dict[tuple[str, str], CorpusRow] = {}
    results: list[tuple[CorpusRow, list[ClassifierFlag]]] = []
    for row in ordered:
        key = (row.agent_name, row.task_id)
        prior = last_by_bucket.get(key)
        flags = _classify_row(row, prior)
        results.append((row, flags))
        last_by_bucket[key] = row
    return results


@dataclass
class CorpusSummary:
    total: int
    per_rule: dict[str, int]
    per_packet_total: dict[str, int]
    per_rule_per_packet: dict[str, dict[str, int]]

    def rule_rate(self, rule: str) -> float:
        return (self.per_rule.get(rule, 0) / self.total) if self.total else 0.0

    def rule_rate_per_packet(self, rule: str, packet: str) -> float:
        total = self.per_packet_total.get(packet, 0)
        bucket = self.per_rule_per_packet.get(packet, {})
        return (bucket.get(rule, 0) / total) if total else 0.0


def summarize(results: list[tuple[CorpusRow, list[ClassifierFlag]]]) -> CorpusSummary:
    total = len(results)
    per_rule: dict[str, int] = defaultdict(int)
    per_packet_total: dict[str, int] = defaultdict(int)
    per_rule_per_packet: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row, flags in results:
        packet = row.packet_type or "__unset__"
        per_packet_total[packet] += 1
        for flag in flags:
            per_rule[flag.value] += 1
            per_rule_per_packet[packet][flag.value] += 1
    return CorpusSummary(
        total=total,
        per_rule=dict(per_rule),
        per_packet_total=dict(per_packet_total),
        per_rule_per_packet={k: dict(v) for k, v in per_rule_per_packet.items()},
    )


def _evaluate_gate(
    *,
    healthy: CorpusSummary,
    pathological: CorpusSummary,
) -> list[str]:
    failures: list[str] = []

    for rule in (ClassifierFlag.ACK_ONLY.value, ClassifierFlag.NEAR_DUPLICATE.value):
        hrate = healthy.rule_rate(rule)
        if hrate > HEALTHY_MAX_FLAG_RATE:
            failures.append(
                f"healthy[{rule}]: {hrate:.1%} > {HEALTHY_MAX_FLAG_RATE:.0%} gate"
            )
        prate = pathological.rule_rate(rule)
        lo, hi = PATHOLOGICAL_TARGETS[rule]
        if prate < lo:
            failures.append(
                f"pathological[{rule}]: {prate:.1%} < {lo:.0%} gate"
            )
        if prate > hi:
            failures.append(
                f"pathological[{rule}]: {prate:.1%} > {hi:.0%} gate"
            )

    # Per-packet healthy gate
    for packet, total in healthy.per_packet_total.items():
        if total == 0:
            continue
        counts = healthy.per_rule_per_packet.get(packet, {})
        for rule in (ClassifierFlag.ACK_ONLY.value, ClassifierFlag.NEAR_DUPLICATE.value):
            rate = counts.get(rule, 0) / total
            if rate > HEALTHY_MAX_FLAG_RATE:
                failures.append(
                    f"healthy[{packet}][{rule}]: {rate:.1%} > "
                    f"{HEALTHY_MAX_FLAG_RATE:.0%} gate"
                )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthy", required=True, type=Path)
    parser.add_argument("--pathological", required=True, type=Path)
    args = parser.parse_args(argv)

    healthy_rows = load_corpus(args.healthy)
    pathological_rows = load_corpus(args.pathological)
    healthy = summarize(classify_corpus(healthy_rows))
    pathological = summarize(classify_corpus(pathological_rows))
    failures = _evaluate_gate(healthy=healthy, pathological=pathological)

    output = {
        "healthy": {
            "total": healthy.total,
            "per_rule": healthy.per_rule,
            "per_packet_total": healthy.per_packet_total,
            "per_rule_per_packet": healthy.per_rule_per_packet,
        },
        "pathological": {
            "total": pathological.total,
            "per_rule": pathological.per_rule,
            "per_packet_total": pathological.per_packet_total,
            "per_rule_per_packet": pathological.per_rule_per_packet,
        },
        "gates": {
            "healthy_max_flag_rate": HEALTHY_MAX_FLAG_RATE,
            "pathological_targets": {
                rule: {"min": lo, "max": hi}
                for rule, (lo, hi) in PATHOLOGICAL_TARGETS.items()
            },
        },
        "failures": failures,
    }
    json.dump(output, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
