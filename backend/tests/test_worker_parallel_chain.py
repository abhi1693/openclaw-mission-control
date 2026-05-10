# ruff: noqa: S101
"""Regression coverage for the worker-parallel ACP instruction chain."""

from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
OPENCLAW_SKILLS_ROOT = Path("/root/.openclaw/skills")


def _backend_skill(name: str) -> str:
    return (BACKEND_ROOT / "skills" / name / "SKILL.md").read_text()


def _live_skill(name: str) -> str:
    return (OPENCLAW_SKILLS_ROOT / name / "SKILL.md").read_text()


def test_worker_parallel_scheduler_source_matches_live_skill() -> None:
    assert _backend_skill("worker-parallel-scheduler") == _live_skill(
        "worker-parallel-scheduler",
    )


def test_worker_parallel_scheduler_documents_atomic_spawn_gate() -> None:
    skill = _backend_skill("worker-parallel-scheduler")

    assert "WT_SCHED_LOCK" in skill
    assert 'exec 8>"$WT_SCHED_LOCK"' in skill
    assert "flock -w 30 8" in skill
    assert "Keep file descriptor 8 open" in skill
    assert "through `sessions_spawn` and `ACP_EXECUTOR_STARTED`" in skill


def test_worker_parallel_scheduler_reviews_before_merge() -> None:
    skill = _backend_skill("worker-parallel-scheduler")

    assert "Do NOT merge child work before parent verification" in skill
    assert "required stage-2 review PASS" in skill
    assert "POST_MERGE_VERIFICATION_PASSED" in skill
    assert skill.index("required stage-2 review PASS") < skill.index(
        "git -C \"$WORKSPACE_PATH\" merge",
    )


def test_worker_parallel_scheduler_uses_board_scoped_worktrees() -> None:
    skill = _backend_skill("worker-parallel-scheduler")

    assert 'BOARD_SHORT="$(printf \'%s\' "$BOARD_ID" | cut -c1-8)"' in skill
    assert 'WT_PATH="/tmp/mc-${BOARD_SHORT}-wt-$TASK_SHORT"' in skill
    assert 'WT_BRANCH="wt/${BOARD_SHORT}/$TASK_SHORT"' in skill
    assert 'git -C "$WT_PATH" rev-parse --abbrev-ref HEAD' in skill
    assert 'git -C "$WT_PATH" status --short' in skill


def test_acp_delegation_worker_mode_is_not_frontend_only() -> None:
    for root in (BACKEND_ROOT / "skills", OPENCLAW_SKILLS_ROOT):
        skill = (root / "acp-delegation" / "SKILL.md").read_text()
        assert "PF worktree mode" not in skill
        assert "worker worktree mode" in skill
        assert "identity.worker_parallel_mode=worktree" in skill
        assert 'WT_PATH="/tmp/mc-${BOARD_SHORT}-wt-$TASK_SHORT"' in skill


def test_acp_post_review_documents_worktree_pre_merge_gate() -> None:
    for root in (BACKEND_ROOT / "skills", OPENCLAW_SKILLS_ROOT):
        skill = (root / "acp-post-review" / "SKILL.md").read_text()
        assert "## Worktree Pre-Merge Gate" in skill
        assert "before merging the child worktree" in skill
        assert "review-only child against the worktree diff" in skill
        assert "post-merge verification" in skill
