# Agent Harness Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the agent system from heartbeat-driven polling to event-driven continuous work, reduce template overhead by 80%, add calibrated QA evaluation, and fix liveness/token issues — based on Anthropic's "Harness Design for Long-Running Apps" article.

**Architecture:** 11-item improvement plan across 5 layers: infrastructure prerequisites (liveness, tokens), execution model (event-driven), planning/handoff contracts, quality control (QA rubrics and loops), and observability (trace review). Each task is self-contained and deployable independently.

**Tech Stack:** Python/FastAPI backend, Jinja2 templates, OpenClaw gateway (Node.js), PostgreSQL, Redis

> **Operational notes**
> - Heartbeat execution uses the heartbeat model (`minimax-m2.5`), not Supervisor's primary `gpt-5.4`. `gpt-5.4` is still used by Supervisor/Codex delegations, but those are subprocess calls layered on top of the heartbeat loop.
> - `shared/` artifacts referenced below live on the gateway at `/root/.openclaw/workspace/shared/` and are already scaffolded there. They are not tracked in this git repo.
> - Deploy `shared/` files manually (`scp`) or create them in-place from an agent session. Template sync only handles files listed in `DEFAULT_GATEWAY_FILES`.
> - `board-start.sh` already contains template sync support (commit `cb3e6fb`), so none of the tasks below require script changes for template deployment.

## Operating Policies

### Role Split: Supervisor Hub, Architect Specialist

- Supervisor always owns intake and routing: create short task seeds, assign all work, route all QA reviews, make priority decisions, triage inbox, reassign rejected tasks, and escalate to Miguel.
- Architect is a specialist the Supervisor invokes when a task needs product-spec expansion or architecture review. Architect expands the Supervisor seed into a product spec with explicit success criteria, non-goals, quality bar, and a sprint contract that defines what this sprint will and will not deliver.
- Architect does not assign tasks, does not route work to QA, and does not triage inbox. Architect posts its spec/contract back as a task comment for the Supervisor to route.
- The sprint contract must be concrete enough for QA to evaluate before coding starts.
- Bypass rule: LOW priority work, bug fixes, or tasks touching fewer than 3 files skip Architect and pre-build QA contract signoff. Supervisor assigns those tasks directly to Programmer and self-validation is sufficient unless Supervisor explicitly requests QA.
- HIGH/MEDIUM new-feature rule: Supervisor creates the seed, assigns Architect, receives the spec/contract comment back, routes the sprint contract to QA for signoff, then assigns Programmer only after QA approval.

### Context Strategy

- Use `isolatedSession=true` only for heartbeat safety-net checks: idle agents, liveness confirmation, progress posting, and other non-building sessions where no active implementation context must be preserved.
- Use `isolatedSession=false` only for continuous work sessions triggered by `deliver=True`, where an agent already owns an `in_progress` task and needs conversational continuity across plan/build/validate loops.
- Treat this as a strict policy, not a mixed mode. A task run is either a safety-net check or a continuous work session.

### Methodical Rollout Policy

- Implement one task at a time in dependency order. Do not batch-roll multiple workflow changes together.
- After each task, measure impact before moving on: agent throughput (tasks completed per day), token cost (per active task/session where available), and error rate (failed runs, false offline, stuck review loops).
- Use one observation window per task rollout before proceeding. Minimum: the next 10 comparable task runs or one working day, whichever produces more signal.
- Roll back the most recent change if any of the following hold during the observation window:
  - throughput drops by more than 10% without a compensating quality gain,
  - token cost per task rises by more than 15% without a clear reduction in error rate or review churn,
  - error rate or stuck-task rate rises by more than 10%,
  - liveness, contract negotiation, or QA routing stops work from progressing for active tasks.
- **Model reassessment rule:** When a new model version ships (e.g., MiniMax M3, GPT-6), re-evaluate which scaffolding is still load-bearing. Every harness component encodes an assumption about what the model can't do alone — test those assumptions on the new model before carrying them forward.

---

## Task 0: Fix Liveness Prerequisites

**Files:**
- Modify: `backend/app/services/openclaw/constants.py`
- Modify: `backend/app/services/openclaw/provisioning_db.py` (with_computed_status)
- Modify: `backend/tests/test_agent_provisioning_utils.py`

**Problem:** `OFFLINE_AFTER = 10m` marks 30m-heartbeat agents as offline. `DEFAULT_HEARTBEAT_CONFIG` lacks `isolatedSession` and `lightContext`, which completes the unfinished heartbeat-token-optimization work rather than introducing a new configuration idea.

**Step 1: Write the failing test**

```python
def test_default_heartbeat_config_has_isolation():
    from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG
    assert DEFAULT_HEARTBEAT_CONFIG["isolatedSession"] is True
    assert DEFAULT_HEARTBEAT_CONFIG["lightContext"] is True

def test_offline_threshold_exceeds_max_heartbeat():
    from app.core.durations import parse_every_to_seconds
    from app.services.openclaw.constants import (
        DEFAULT_HEARTBEAT_CONFIG,
        HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL,
        OFFLINE_AFTER,
    )

    configured_interval = parse_every_to_seconds(DEFAULT_HEARTBEAT_CONFIG["every"])
    assert OFFLINE_AFTER.total_seconds() > (
        configured_interval + HEARTBEAT_RECOVERY_GRACE_AFTER_INTERVAL.total_seconds()
    )
```

Also keep a provisioning-status regression case with a `30m` heartbeat override so the original false-offline bug stays covered without hardcoding `1800 + 60` into the assertion.

Run: `pytest backend/tests/test_agent_provisioning_utils.py -v -k "isolation or offline_threshold"`
Expected: FAIL

**Step 2: Fix constants.py**

```python
DEFAULT_HEARTBEAT_CONFIG: dict[str, Any] = {
    "every": "10m",
    "target": "last",
    "includeReasoning": False,
    "lightContext": True,
    "isolatedSession": True,
}

OFFLINE_AFTER = timedelta(minutes=35)
```

Note: `35m` plus the existing `1m` recovery grace means Supervisor's 5m heartbeat will not flip to `offline` until roughly 36 minutes after last-seen. Accept that lower sensitivity as a temporary tradeoff to stop false offline status for 30m agents.

TODO: Replace the single global `OFFLINE_AFTER` with per-agent offline detection derived from each agent's effective heartbeat interval.

**Step 3: Run tests**

Run: `pytest backend/tests/ -v -k "heartbeat or offline"`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/app/services/openclaw/constants.py backend/tests/
git commit -m "fix(constants): OFFLINE_AFTER=35m for 30m heartbeats, add isolatedSession defaults"
```

Deployment note: this task only changes backend constants/tests. No `board-start.sh` changes are required.

---

## Task 1: Continuous Workflow Runs

**Files:**
- Modify: `backend/templates/BOARD_HEARTBEAT.md.j2` (worker workflow section, lines 386-421)

**Problem:** Template says "Execute ONE workflow step" and forces stops after PLANNING/IMPLEMENTING. Combined with 30m heartbeat, minimum 3 cycles (90 min) per task. This task is the prompt-side counterpart to the wake-flow work in `docs/plans/2026-03-17-native-event-driven-wake.md`.

**Step 1: Remove forced one-step-per-cycle constraint**

Replace the worker workflow section (lines 386-421) with:

```
   **Execute your workflow.** Read MEMORY.md for your workflow state block. If none exists, start at PLANNING.
   Run through ALL applicable states in one session until work is accepted, you hit a real blocker, or you run out of time.

   **PLANNING:** Read the short task, Architect spec if present, sprint contract if present, comments, and linked docs. If this is a HIGH/MEDIUM new-feature task and the Architect spec or sprint contract is missing, stop and ask @lead to decide whether Architect must be invoked before building. If this is LOW priority work, a bug fix, or a task touching fewer than 3 files, continue without Architect unless @lead says otherwise.
   **CONTRACT CHECK:** If QA review is required for this task, wait for @lead to route the sprint contract to QA and do not implement until `qa_signoff=approved`. If QA rejects the contract, post the needed revision notes and ask @lead to re-route the updated contract to QA.
   **IMPLEMENTING:** Build against the approved sprint contract. Run feedback loops (typecheck, lint, tests). Continue directly to validation when the current slice is ready.
   **VALIDATING:** Run self-validation first. If QA review is required, post the validation summary and ask @lead to route the task to QA. If QA rejects, fix the rejection items and ask @lead to re-route the task to QA for re-test. Maximum 3 QA reject/fix/re-test rounds, then escalate to Supervisor with the rejection history.
   **REFINE OR PIVOT:** If QA rejects twice on the same issue, stop and decide: is the current approach salvageable (refine), or should you try a fundamentally different approach (pivot)? Post your decision as a task comment before continuing. If pivoting, update the handoff file with the new approach.

   Do NOT stop between states unless blocked. Small and large tasks both run continuously.
```

**Step 2: Verify template renders under 20K**

Run: `python3 -c "from jinja2 import Environment, FileSystemLoader; ..."`
Expected: Worker < 20000 chars

**Step 3: Deploy and commit**

```bash
scp backend/templates/BOARD_HEARTBEAT.md.j2 root@192.168.2.64:/home/mcontrol/.../templates/
git add backend/templates/BOARD_HEARTBEAT.md.j2
git commit -m "feat(heartbeat): continuous workflow — remove one-step-per-cycle constraint"
```

---

## Task 2: Shrink HEARTBEAT Template (19KB → 8-10KB)

**Files:**
- Modify: `backend/templates/BOARD_HEARTBEAT.md.j2`
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/docs/validation-cookbook.md`
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/docs/qa-routing.md`
- Modify: `backend/tests/test_template_size_budget.py`

**Problem:** 19KB of prompt overhead before any coding. Most is inline curl/jq blocks, validation cookbook, and policy prose the model doesn't need every cycle.

**Step 1: Identify what to cut**

Keep (essential, target rendered size ~8-10KB):
- Role identification (is_lead/is_worker)
- Auth: read TOOLS.md, check-in endpoint
- Task selection: fetch assigned task, read comments
- Workflow: continuous plan/build/validate
- Result posting: PATCH to review, post comment
- HEARTBEAT_OK gate

Move to on-demand docs (agent can read when needed):
- Inline curl/jq API discovery blocks (~2KB)
- Full validation cookbook with deployment steps A-E (~3KB)
- Port/URL consistency section (~1KB)
- Interrupted ACP session recovery (~1KB)
- Test failure classification rules (~1KB)
- Lead: full Codex review prompt (~3KB)
- Lead: full Claude Code routing prompt (~2KB)

**Step 2: Extract to callable scripts/docs**

Create plain markdown files at `/root/.openclaw/workspace/shared/docs/validation-cookbook.md` and `/root/.openclaw/workspace/shared/docs/qa-routing.md`. Template references them directly: "For deployment validation steps, read `$SHARED_WORKSPACE/docs/validation-cookbook.md`."

Do not use Jinja2 `includes/` here. Includes reduce template source duplication, but they do not shrink the rendered heartbeat prompt. The extracted content needs to live as separate `.md` files in `shared/docs/` on the gateway.

Deployment note: these `shared/docs/` files are outside the repo and outside template sync. Copy them with `scp` or have an agent create/update them on the gateway workspace.

**Step 3: Write size test**

```python
def test_worker_template_under_10kb():
    rendered = render_template(is_lead=False, ...)
    assert len(rendered) <= 10000, f"Worker template {len(rendered)} chars > 10000"
```

Budget note: aim to land in the 8-10KB range after cleanup rather than forcing an artificially small 4KB target.

**Step 4: Rewrite template to target 8-10KB**

Minimal worker template structure:
```
# HEARTBEAT.md
## Setup
Read TOOLS.md for BASE_URL, AUTH_TOKEN, BOARD_ID.
## Pre-Flight
1) Check in: POST $BASE_URL/api/v1/agent/heartbeat
2) If fails, stop.
## Work
1) Fetch assigned task. If none, post idle and return HEARTBEAT_OK.
2) Run continuously: PLAN → CONTRACT CHECK → IMPLEMENT → VALIDATE.
3) For HIGH/MEDIUM new-feature work, do not code until @lead has routed the sprint contract to QA and `qa_signoff=approved`.
4) LOW priority work, bug fixes, and tasks touching fewer than 3 files skip Architect and pre-build QA contract signoff unless @lead says otherwise.
5) If QA rejects a contract or validation review, fix the issue, ask @lead to re-route it to QA, and repeat for up to 3 rounds before escalating.
6) Activate skills: frontend-design, feature-dev, superpowers, simplify.
7) Post progress comment every 30 min while working.
8) Stay in your role. Ask @lead for cross-role work, Architect involvement, or QA routing.
9) For validation details: read $SHARED_WORKSPACE/docs/validation-cookbook.md
## HEARTBEAT_OK
Say HEARTBEAT_OK only when check-in succeeded and work is complete or reported.
```

**Step 5: Commit**

```bash
git add backend/templates/ backend/tests/
git commit -m "refactor(heartbeat): shrink worker template from 19KB to 8-10KB"
```

---

## Task 3: Structured Task Handoff Files

**Files:**
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/tasks/README.md` (schema documentation)
- Modify: `backend/templates/BOARD_HEARTBEAT.md.j2` (reference handoff files)

**Problem:** MEMORY.md is thin prose. Agents lose context between sessions. Article recommends structured handoff artifacts.

**Step 1: Define handoff schema**

Create `/root/.openclaw/workspace/shared/tasks/README.md`:
```markdown
# Task Handoff Schema
Each in-progress task has a file: shared/tasks/<task_id>.md

## Required Fields
- task_id: UUID
- objective: one sentence
- sprint_contract: what "done" looks like for this sprint
- qa_signoff: pending | approved | rejected | not_required
- qa_round: integer, start at 0 and cap at 3 before Supervisor escalation
- files_touched: list of files modified
- commands_run: last 5 commands with output summary
- last_build_result: pass/fail + error if fail
- deployment_target: URL
- blockers: list or "none"
- next_action: exact next step to take
```

**Step 2: Update template to read/write handoff files**

Add to worker workflow:
```
Before starting work, read handoff file if it exists:
  cat $SHARED_WORKSPACE/tasks/$TASK_ID.md 2>/dev/null
If `qa_signoff` is `pending` or `rejected`, ask @lead to route or re-route the sprint contract to QA before implementation.
Do not begin coding until `qa_signoff` is `approved` for HIGH/MEDIUM new-feature work.
If this is LOW priority work, a bug fix, or a task touching fewer than 3 files, set `qa_signoff` to `not_required` unless @lead explicitly routes QA.
If `qa_signoff` is `not_required`, self-validation is sufficient unless the developer asks @lead to route QA review.
After each work session, update the handoff file with current state.
After each QA rejection, increment `qa_round`, record the rejection summary, fix the issue, and ask @lead to route the next QA re-test.
```

Deployment note: `shared/tasks/` lives on the gateway workspace, not in this repo.

**Step 3: Commit**

```bash
git commit -m "feat(handoff): add structured task handoff files in shared workspace"
```

---

## Task 4: High-Level Task Specs

**Problem:** 500+ word task descriptions with inline code samples cause anchoring. Article says high-level specs work better.

**Action:** This is a process change, not a code change. Document the rule:

Create `/root/.openclaw/workspace/shared/docs/task-spec-guidelines.md`:
```markdown
# Task Specification Guidelines
- Supervisor writes a short task seed only: goal, priority, constraints, references
- Architect, when assigned by Supervisor, expands that seed into a full spec before implementation
- Goal: one sentence
- Constraints: tech/deployment/compatibility limits
- Success criteria: 3-5 bullet points (what "done" looks like)
- Sprint contract: the exact slice QA must approve before coding begins
- Non-goals: what this sprint will not attempt
- References: links to specs, plans, shared docs
- Do NOT include inline code samples — put those in linked spec files
- Do NOT specify implementation approach — let the agent decide
- LOW priority work, bug fixes, and tasks touching fewer than 3 files bypass Architect and pre-build QA contract signoff unless Supervisor explicitly opts in
```

**Supervisor-hub planning workflow:**

1. Supervisor creates a short task with priority, goal, constraints, and references.
2. For HIGH/MEDIUM new-feature work, Supervisor assigns the task to Architect.
3. Architect expands the seed into a high-level product spec with success criteria, quality bar, non-goals, and sprint contract.
4. Architect posts the spec package back to the task as a comment for Supervisor review and routing.
5. Supervisor routes the sprint contract to QA for signoff and handles any rejected contract reassignment.
6. Only after QA approval does Supervisor assign the task to Programmer.
7. For LOW priority work, bug fixes, or tasks touching fewer than 3 files, Supervisor bypasses Architect and pre-build QA contract signoff and assigns Programmer directly.

Deployment note: this is a plain markdown doc in the gateway `shared/docs/` workspace, not a repo-backed template.

---

## Task 5: Design-Quality Prompt Anchoring

**Problem:** No quality anchor in task specs. Article shows "museum quality" phrasing shapes output.

**Step 1: Add quality anchor to template**

In the worker workflow section, add:
```
Design quality anchor: Build interfaces that feel professionally designed for a government operations center.
Think Linear meets Bloomberg Terminal — information-dense but never cluttered, calm but not boring.
Never produce generic AI aesthetics (default gradients, cookie-cutter layouts, Inter/Roboto fonts).
```

**Step 2: Add to task creation guidance**

Update lead template task creation section to include quality anchor in task descriptions.

---

## Task 6: QA Grading Rubric

**Files:**
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/qa/rubric.md`
- Modify: QA-E2E IDENTITY.md (reference rubric)
- Modify: QA-Unit IDENTITY.md (reference rubric)

**Step 1: Create rubric**

```markdown
# QA Grading Rubric

## Review Entry Policy
- Supervisor routes all QA work.
- QA review is required for HIGH/MEDIUM new-feature tasks.
- For LOW priority work, or bug fixes touching fewer than 3 files, self-validation is sufficient and the developer may set `qa_signoff: not_required` unless Supervisor explicitly routes QA.
- Any developer may still ask Supervisor to route QA review voluntarily.
- For QA-required tasks, Supervisor sends the sprint contract to QA first and QA must set `qa_signoff: approved` before implementation begins.

## Review Loop
1. Supervisor sends the sprint contract to QA.
2. If QA rejects the pre-build contract, Supervisor routes it back to Architect for revision and re-submits it to QA.
3. During implementation review, QA rejection goes back through Supervisor, who reassigns the task to Programmer for fixes.
4. Programmer fixes the issues and asks @lead to route the task back to QA.
5. Supervisor re-routes the task to QA for re-test.
6. Stop after 3 reject/fix/re-test rounds and have Supervisor decide whether to re-scope, pause, or escalate to Miguel with the rejection history and proposed decision.

## Frontend Tasks
| Dimension | Weight | Fail Threshold | How to Check |
|-----------|--------|----------------|-------------|
| Spec Fidelity | 15% | <6/10 | Compare against plan docs and sprint contract |
| Interaction | 15% | <7/10 | Click/drag/toggle all features |
| Visual Quality | 15% | <7/10 | Typography, color, spacing, motion |
| Originality | 20% | <6/10 | Check for custom decisions, not cookie-cutter patterns |
| Craft | 15% | <6/10 | Assess code cleanliness, polish, and absence of hacks |
| Responsiveness | 5% | <5/10 | Resize viewport to mobile/tablet |
| Console/Network | 10% | Any error = fail | Chrome MCP list_console_messages |
| Code Quality | 5% | Typecheck fails = fail | tsc --noEmit, npm run lint |

## Backend Tasks
| Dimension | Weight | Fail Threshold | How to Check |
|-----------|--------|----------------|-------------|
| API Contract | 30% | Missing endpoint = fail | curl all endpoints from spec |
| Data Accuracy | 25% | Wrong data = fail | Compare API response vs DB |
| Error Handling | 15% | Crash on bad input = fail | Send invalid params |
| Performance | 10% | >5s response = fail | time curl |
| Test Coverage | 20% | <80% pass rate = fail | pytest --tb=short |

## Hard Fail Rules (any = REJECT)
- Console errors > 0 (excluding warnings and third-party deprecation notices)
- Typecheck fails
- Build fails
- Service returns 5xx
- Data mismatch vs database
```

**Step 2: Update QA identities**

Update QA-E2E and QA-Unit identities to:
- read the rubric before review,
- enforce the pre-build sprint-contract signoff for HIGH/MEDIUM work,
- expect Supervisor to route every QA request and skip QA automatically only when `qa_signoff=not_required`,
- run the reject -> fix -> re-test loop with a hard stop at 3 rounds before Supervisor escalation.

Deployment note: keep the rubric in `shared/qa/` on the gateway and reference it from the QA identities there.

---

## Task 7: Few-Shot QA Calibration

**Files:**
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/qa/examples/pass-frontend-kanban.md`
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/qa/examples/fail-frontend-regression.md`
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/qa/examples/pass-backend-api.md`
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/qa/examples/fail-backend-endpoint.md`

**Problem:** QA checks pass/fail without calibrated judgment. Article says few-shot examples align evaluator.

**Action:** Extract 4 labeled examples from our actual history (Kanban task approval, UX regression rejection, API spec validation, comments endpoint 404). Each example MUST include:
- Task context (what was built, what was reviewed)
- Dimension-by-dimension scores using the rubric from Task 6 (e.g., Spec Fidelity: 8/10, Originality: 7/10, ...)
- Overall verdict: PASS or FAIL with the specific dimension that triggered the decision
- Evaluator reasoning: why each score was given, what evidence supported it

This scored-breakdown format calibrates the evaluator's judgment, not just the pass/fail boundary.

---

## Task 8: Trace Review and Prompt Tuning Loop

**Files:**
- Create on gateway shared workspace: `/root/.openclaw/workspace/shared/docs/trace-review-loop.md`

**Problem:** Without regularly reading Architect/Programmer/QA session traces, prompt failures show up as anecdotes instead of actionable fixes. The system needs a standing review loop that turns observed failures into targeted prompt and template improvements.

**Action:** Create a standing trace-review playbook that says:
- review session traces after every escalation and at least once per 5 completed tasks,
- identify prompt failures such as missing contract negotiation, skipped QA routing, repeated rejection loops, tool misuse, or bloated context,
- tune one template/instruction at a time based on observed failures,
- log the hypothesis, change made, and the next observation window,
- treat this as an ongoing operating practice, not a one-time cleanup task.

---

## Task 9: Cost Tracking Per Task (Future Investigation)

**No implementation in this plan.** Descope this until the gateway API for session token usage is understood.

**Problem:** No per-task cost attribution today, and it is not yet verified that the gateway exposes session token usage in a stable API shape that the backend can consume.

**Next step:** Investigate gateway/session APIs first:
- Confirm whether per-session token usage is exposed via API, persisted metadata, or logs.
- Decide whether task comments should ingest usage directly, or whether the gateway needs a new endpoint/field.
- Only then scope backend changes in `backend/app/api/tasks.py` and `backend/app/schemas/tasks.py`.

---

## Task 10: Agent Consolidation Analysis (Future)

**No code changes.** Document analysis for future reference.

Create `docs/plans/2026-03-25-agent-consolidation-analysis.md`:
- Current: 7 agents with 30m heartbeats = 4 layers of latency
- Proposed: 3 functional roles (Supervisor hub, Programmer, Evaluator/QA), with Architect capability retained as a Supervisor-invoked specialist pass when needed
- Benefit: fewer agents = fewer token rotations, simpler routing, less Supervisor overhead
- Risk: less specialization, harder to parallelize
- Decision: defer until items 0-3 deliver measurable improvement

---

## Dependency Graph

```
Task 0 (liveness) ──→ Task 1 (continuous workflow) ──→ Task 2 (shrink template)
                                                       │
                                                       ├──→ Task 3 (handoff files)
                                                       ├──→ Task 5 (quality anchor)

Task 4 (task specs) ──→ Task 6 (QA rubric) ──→ Task 7 (few-shot calibration)
                                              └──→ Task 8 (trace review loop, ongoing)

Task 8 (trace review) — ongoing feedback loop into Tasks 1/3/4/6
Task 9 (cost tracking) — future investigation, independent
Task 10 (consolidation) — future, no dependencies
```

## Estimated Effort

| Task | Effort | Impact |
|------|--------|--------|
| 0. Liveness | 15 min | Unblocks 30m heartbeats |
| 1. Continuous workflow runs | 30 min | Eliminates 90-min minimum per task |
| 2. Shrink template | 3-4 hours | Lower prompt overhead without losing critical guidance |
| 3. Handoff files | 30 min | Better context preservation |
| 4. Task specs | 15 min | Process doc only |
| 5. Quality anchor | 15 min | Shapes output quality |
| 6. QA rubric | 2 hours | Calibrated evaluation and contract gating |
| 7. Few-shot calibration | 1 hour | Aligned QA judgment |
| 8. Trace review loop | 30 min setup + ongoing | Continuous prompt tuning from real traces |
| 9. Cost tracking | Future | Requires gateway API investigation first |
| 10. Consolidation | 0 (doc only) | Future reference |
