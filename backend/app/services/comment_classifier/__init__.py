"""Shared comment-signal classifier.

Single source of ack-only + near-duplicate detection consumed by:

- Phase 0 shadow-metric emitter (records flags as observability events,
  no enforcement, no hiding)
- Phase I ``CommentPolicyService`` (reads flags, gated per-board via
  ``Board.rollout_flags.comment_policy_v1``, applies
  ``Board.comment_signal_filter`` semantics)

See ``docs/plans/2026-04-17-mc-delivery-enforcement-plan-phase-1-amendments.md``
section A.2 for why the classifier is extracted once rather than
re-implemented at two call sites.
"""

from __future__ import annotations

from app.services.comment_classifier.classifier import (
    ClassifierFlag,
    classify,
)

__all__ = ["ClassifierFlag", "classify"]
