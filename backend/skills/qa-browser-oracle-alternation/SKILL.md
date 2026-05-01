---
name: qa-browser-oracle-alternation
description: Use to assign the browser-validation oracle by role — PF self-validates with one oracle while QA-E2E cross-checks with the other. Companion to qa-validation-verdict; that skill owns the verdict format, this one owns the oracle assignment.
---

# QA Browser Oracle — by-role assignment (Playwright vs Codex Computer Use)

Two independent browser oracles look at the same live build through
different sensors. Rather than picking one and accepting its blind
spots, **assign each oracle to a different role**:

| Role | Oracle | Why |
|---|---|---|
| **PF (Programmer-Frontend)** | **Playwright** | Fast, deterministic, scriptable. Right for the implementer's own self-validation loop and CI-style assertions tied to specific selectors. |
| **QA-E2E** | **Codex Computer Use** | Vision-based, exploratory, surfaces issues that selector-driven tests miss (animation races, render glitches, real-Chrome rendering vs headless). Right for the gate reviewer who validates against the user-experience surface, not the test contract. |

Two oracles run on every review cycle automatically, with no
selection logic and no state to track. If they agree → high
confidence. If they disagree → the disagreement is the signal.

## Selection rule

**Default: role determines the oracle. No alternation, no parity, no
selection state.**

- Acting as PF (implementing or self-validating)? Use Playwright.
- Acting as QA-E2E (gate reviewer)? Use Codex Computer Use.

If your role isn't one of those (e.g., Architect doing a visual review,
DevOps validating a deploy), pick whichever fits the work and record
the choice in the evidence dict. Architects and review-only roles
typically don't drive browsers — they read packets and source.

### Operator override

If the operator explicitly nominates one oracle in the task
description or a comment ("use Codex Computer Use here, the Playwright
test was wrong last cycle"), honor that for the cycle. Override
overrides role.

### Forced fallback

If your assigned oracle is unreachable (Playwright harness offline,
`cua-driver` not installed, etc.), use the other and record the
substitution reason in the evidence dict's `selection_reason` field.
Don't skip browser validation — `INFRA_BLOCKED` is the right verdict
if neither oracle is reachable.

## Recording the choice

Use the canonical `evidence_type` value via `mc_review_event_create`
(MCP tool) or `mc_client.py review-event-create` (CLI):

| Oracle used | `evidence_type` value |
|---|---|
| Playwright | `browser` |
| Codex Computer Use | `browser_codex_computer_use` |
| Both ran (cross-validation, both PASS) | `browser_cross_validated` |
| Both ran, disagreed | use the FAILing oracle's evidence_type; verdict is `INCONCLUSIVE` |

These strings are free-form on the MC schema (`evidence_type` is
non-constrained `str | None`), so adding new values doesn't require a
backend change. The convention here is what makes them useful for
audit grep and review-routing.

## Required evidence per oracle

### Playwright (`evidence_type: "browser"`) — used by PF

Same as the existing `qa-validation-verdict` § "QA-E2E PASS Evidence":

- exact target URL
- browser navigation and snapshot output for every route/state under test
- DOM text dump and raw i18n-key scan
- console error and failed-network output
- exact action plus before/after observation for every interactive AC
- responsive/layout evidence when applicable
- browser-observed UI state plus API/readback proof for API-backed UI
- loaded build hash or artifact id

PF posts this as part of their own packet (the implementation
worker's self-validation), not as a `qa_e2e` review event.

### Codex Computer Use (`evidence_type: "browser_codex_computer_use"`) — used by QA-E2E

Equivalent rigor, different sensor format:

- exact target URL
- screenshots at each AC checkpoint (Codex CU returns vision frames; save and reference them in the evidence dict)
- visible-text extraction at each checkpoint
- explicit action transcript ("clicked Submit", "typed 'foo' into input[name=q]", "scrolled to footer")
- before/after screenshot for every interactive AC
- console / network errors as captured by `cua-driver mcp` if available
- loaded build hash or artifact id (read from page meta or footer)

The Codex CU evidence dict should include keys:

```json
{
  "oracle": "codex_computer_use",
  "cua_driver_version": "<version string from /codex computer-use status>",
  "screenshots": [
    {"step": "ac1_initial", "ref": "<screenshot id or path>"},
    {"step": "ac1_after_submit", "ref": "..."}
  ],
  "actions": [
    {"step": "ac1", "action": "click", "target": "button[aria-label='Submit']"},
    {"step": "ac1", "action": "wait_for", "target": "text=Saved"}
  ],
  "build_hash": "...",
  "summary": "1-3 sentence verdict context"
}
```

QA-E2E posts this as the `qa_e2e` review event.

## Cross-validation: the natural by-role outcome

Because PF runs Playwright in its own packet and QA-E2E runs Codex
Computer Use as the gate review, every review cycle naturally has
**both oracles**. The pattern:

1. PF implements + self-validates with Playwright. Posts evidence in
   their packet.
2. QA-E2E reviews the same live build with Codex Computer Use. Posts
   review event with `evidence_type: "browser_codex_computer_use"`.
3. **Agreement** (PF Playwright PASS + QA-E2E Codex CU PASS) →
   high-confidence PASS. Lead can route to approval per
   `lead-review-routing`.
4. **Disagreement** (one PASSes, the other FAILs) → high-signal alert.
   QA-E2E posts `INCONCLUSIVE` with both oracle outputs and a
   `disagreement_summary`. Lead does NOT silently route to either
   verdict; operator decides which oracle was right.

### Disagreement evidence shape

```json
{
  "oracle": "disagreement",
  "playwright_packet": "<commit/build/path of PF's Playwright evidence>",
  "playwright_verdict": "pass",
  "codex_computer_use": {
    "verdict": "fail",
    "evidence": { /* full codex_computer_use evidence shape */ },
    "failure_detail": "Codex CU caught a render glitch on AC3 that the headless Playwright didn't surface."
  },
  "disagreement_summary": "1-3 sentence operator-readable summary of where the oracles disagreed"
}
```

## Pre-flight: is Codex Computer Use available?

Before posting QA-E2E review with `browser_codex_computer_use`, confirm
the oracle is operational:

```bash
# On the QA-E2E host
codex computer-use status
```

If status is "not installed" and you're QA-E2E, either:
- Trigger install: `codex computer-use install` (fetches `cua-driver`
  from the trycua upstream)
- Or escalate to the operator (file under `INFRA_BLOCKED` if neither
  oracle is reachable)

`/codex computer-use install` works on Linux gateway hosts (like
`.60`) via `cua-driver`; on macOS, it integrates with the OpenClaw.app
PeekabooBridge instead.

## Routing of verdicts

After posting the review event, the lead's `lead-review-routing` skill
sees the verdict + evidence_type and routes accordingly:

- `pass` + (`browser` | `browser_codex_computer_use` | `browser_cross_validated`) → eligible to gate done (subject to other reviewer roles)
- `fail` → rework
- `inconclusive` (especially with `oracle: disagreement`) → operator escalation; do NOT auto-rework
- `infra_blocked` → DevOps routing (the validation environment is broken, not the product)

## Cross-reference

- `qa-validation-verdict` — the canonical verdict format and per-role
  evidence requirements. Always read this AFTER picking the oracle.
- `mc-board-api` — the typed MCP tool / CLI for posting the review
  event. Use `mc_review_event_create` rather than building curl by
  hand.
- `lead-review-routing` — the lead's verdict-routing logic. The new
  `evidence_type` values are free-form strings, so the lead skill
  needs no change to recognize them.

## Why role-based, not cycle-alternation

An earlier draft of this skill alternated by review-cycle parity (even
cycle = Playwright, odd = Codex Computer Use). Operator pointed out
the cleaner design: **the role IS the alternation**. PF and QA-E2E
naturally run on every cycle, so assigning them different oracles
gives two-oracle coverage automatically with no state-tracking. The
parity scheme was solving a problem that the role split already
solves.
