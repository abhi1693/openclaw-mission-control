# LEAD_PLAYBOOK.md

Supplemental reference for board leads. `HEARTBEAT.md` remains the execution source
of truth; this file provides optional examples.

## Goal Intake Question Bank
Use 3-7 targeted questions in one board-chat message:

1. Objective: What is the single most important outcome? (1-2 sentences)
2. Success metrics: What 3-5 measurable indicators mean done?
3. Deadline: Target date or milestones, and what drives them?
4. Constraints: Budget/tools/brand/technical constraints?
5. Scope: What is explicitly out of scope?
6. Stakeholders: Who approves final output and who needs updates?
7. Update preference: Daily/weekly/asap, and expected detail level?

Suggested prompt shape:
- "To confirm the goal, I need a few quick inputs:"
- "1) ..."
- "2) ..."
- "3) ..."

## Agent Profile Examples
Role naming guidance:
- Use specific domain + function titles (2-5 words).
- Avoid generic labels.
- If duplicated specialization, use suffixes (`Role 1`, `Role 2`).

Example role titles:
- `Partner Onboarding Coordinator`
- `Lifecycle Marketing Strategist`
- `Data Governance Analyst`
- `Incident Response Coordinator`
- `Design Systems Specialist`

Example personality axes:
- speed vs correctness
- skeptical vs optimistic
- detail vs breadth

Optional custom-instruction examples:
- always cite sources
- always include acceptance criteria
- prefer smallest reversible change
- ask clarifying questions before execution
- surface policy risks early

## Soul Update Mini-Checklist
- Capture source URL(s).
- Summarize borrowed principles.
- Propose minimal diff-like change.
- Include rollback note.
- Request approval before non-trivial updates.

## Cron Pattern Examples
Rules:
- Prefix names with `[board:${BOARD_ID}]`.
- Prefer non-delivery jobs.
- Prefer main session system events.
- Remove stale jobs.

Common patterns:
- Daily check-in.
- Weekly review.
- One-shot blocker reminder.
