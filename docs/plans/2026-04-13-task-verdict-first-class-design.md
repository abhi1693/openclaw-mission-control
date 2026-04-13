# First-class `TaskVerdict`: binding reviewer evidence to approvals

**Status:** SUPERSEDED — merged into `2026-04-13-task-verdict-and-rejection-contracts-design.md`
**Superseded by:** `2026-04-13-task-verdict-and-rejection-contracts-design.md` (same day, later version)
**Reason:** The merged spec combines this schema proposal with the proof-type-matching and probe-library elements from the sibling `2026-04-13-rejection-resolution-contracts-design.md`. This standalone spec lacks failure classification at reject time and proof-type matching at resubmission, which the merged spec adds. Kept on disk as historical record; do not implement.

**Original status:** DRAFT — design spec, not yet approved for implementation
**Author:** operator (Claude) in collaboration with Miguel
**Date:** 2026-04-13
**Reviewers needed:** Miguel, any backend owner
**Related commits:** `d6174c4` (rejection-loop API enforcement), `5cbd8ad` (re-review template prose), `350ae7d` (explicit-assignment fix)
**Related incidents:** Dev-Squad board session 2026-04-12 → 2026-04-13 (task churn on `633fb35e`, `33d552a1`, `d51a3a62`)

---

## 1. Problem

Mission Control's current approval model treats approvals as authoritative state without any typed binding to the review evidence they relied on. "Freshness" is inferred from human-readable prose in `payload.qa_evidence` (a free-form text field) and from comment timestamps. The approval guard `_ensure_no_rejection_loop` (commit `d6174c4`) counts rejections but does not inspect evidence quality. The template-level re-review rule (commit `5cbd8ad`) is prose guidance that LLM agents routinely violate under heartbeat pressure.

Four verified anti-patterns observed in a single session (forensic audit available):

1. **Stale-verdict re-citation.** Architect posted "6/6 PASS at 22:04 UTC" on task `633fb35e`, then re-cited that same PASS across four subsequent comments on parent task `d51a3a62` (22:41, 22:42, 22:55, 23:12 UTC) without running a new test. The task had real functional bugs that a fresh test would have caught.

2. **Clean-session laundering.** QA-E2E posted 7/7 PASS at 11:03 UTC, then a fresh re-validation at 11:33 UTC that FAILED 9/12 on PT-BR `document.documentElement.lang`, then a third run at 11:42 UTC with "clean session / cookie clear between routes" methodology that PASSED again. The Supervisor accepted the 11:42 clean-session pass as "newest evidence" superseding the 11:33 FAIL. The underlying bug was a real returning-user initial-load failure that clean-session testing trivially masked. The bug shipped as "approved" until operator re-verification caught it hours later.

3. **Phantom AC false alarm.** QA-E2E at 03:16 UTC claimed a FAIL on a non-existent "AC #7"; self-corrected at 03:17 UTC; Supervisor clarified at 03:20 UTC that the task has 4 task-specific + 4 general ACs. Four agents burned ~15 minutes of heartbeat time on a hallucinated regression.

4. **Post-rejection stale re-cite.** Operator rejected approval `00b52ed9` at 13:20:54 UTC. Operator posted a fix commit `d0c612e` at ~13:22 UTC. At 13:25:29 UTC a new approval `aa5845af` was created with `qa_evidence` literally referencing the "2026-04-13 11:42 UTC clean-session PASS artifact" — the exact evidence the operator had just called stale. The re-submission cited pre-rejection evidence with no acknowledgment that the rejection had occurred.

The common primitive: **agents can mint fresh-looking evidence by posting prose**. Until the backend distinguishes verdict artifacts from ordinary comments and binds approvals to specific post-rejection verdicts, the re-review rule is unenforceable at runtime.

---

## 2. Goals and non-goals

### Goals

- **Typed verdict artifacts.** Reviewer verdicts (QA, Architect, Lead) become first-class rows with reviewer identity, commit/artifact reference, methodology tag, and per-AC results — not free-text comments.
- **Approval→verdict binding.** A `move_to_done` approval MUST reference at least one `TaskVerdict` row. The approval create endpoint validates that the referenced verdicts are (a) PASS, (b) created after the last rejection on this task, (c) from appropriate reviewer roles for the task.
- **Unbypassable post-rejection freshness.** A DB-level FK timestamp check cannot be defeated by posting filler prose, by regex tricks, or by renaming agents.
- **Operator override preserved.** The existing `POST /approvals/{id}/unblock` endpoint remains the only way an operator bypasses the check, matching the pattern already established by `d6174c4`.
- **Backwards compatibility during transition.** Existing approvals without verdict references must continue to work until a feature flag or migration cut-over.

### Non-goals

- **Semantic verdict validation.** The backend does not try to judge whether a PASS is correct. It only enforces that SOME typed verdict exists with the right timing and scope. Correctness is still a reviewer's responsibility — what changes is that reviewers cannot retroactively re-cite their own pre-rejection work.
- **Git binding in the hot path.** Commit SHAs are stored as strings for traceability. The backend does NOT run `git merge-base`, does NOT fetch repos, does NOT validate SHA ancestry. The adversarial review (three independent reviewers: two subagents + Codex gpt-5.4 high-reasoning) confirmed git binding creates more availability and complexity problems than it solves.
- **Replacing `_ensure_no_rejection_loop`.** The rejection-loop counter is kept as a separate escalation gate (triggers operator unblock after N rejections in 24h). The new verdict binding is an additional layer that fires earlier.
- **Coverage enforcement for all task types.** Initial scope: `move_to_done` approvals only. Other action types (`delete`, `reassign`, etc.) are out of scope for this change.
- **Live methodology auditing.** The `methodology` field is a reviewer-asserted tag. The backend cannot tell whether a reviewer ran a clean-session or returning-user test; it just makes the claim auditable and queryable.

---

## 3. Data model changes

### 3.1 New table: `task_verdicts`

**File:** `backend/app/models/task_verdicts.py`
**Migration:** new Alembic revision `<rev>_add_task_verdicts.py`

```python
class TaskVerdict(QueryModel, table=True):
    __tablename__ = "task_verdicts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)

    # Reviewer identity — derived at submission time, not trusted from client
    reviewer_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    reviewer_user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    reviewer_role: str = Field(index=True)  # "qa_e2e" | "qa_unit" | "architect" | "lead" | "operator"

    # What was reviewed
    verdict: str = Field(index=True)  # "pass" | "fail" | "partial"
    commit_sha: str | None = Field(default=None, index=True)  # optional, string, NOT validated as git ref
    artifact_ref: str | None = None  # free-text: "test-results/33d552a1-closeout.json", "playwright-trace-abc.zip", etc.

    # Methodology — reviewer-asserted, queryable
    methodology: str | None = Field(default=None, index=True)
    # free-text enum-like: "clean_session" | "returning_user" | "both" | "code_review" | "manual_spot_check" | "static_only"

    # Per-AC results — jsonb dict {ac_id: "pass" | "fail" | "partial" | "n/a"}
    ac_results: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))

    # Freeform notes — replaces comment prose for verdict rationale
    notes: str | None = None

    # Lineage: if this verdict supersedes an earlier one (e.g., re-test after feedback)
    supersedes_verdict_id: UUID | None = Field(default=None, foreign_key="task_verdicts.id", index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)
```

**Key invariants (enforced in schema validator, not DB constraint):**
- Exactly one of `reviewer_agent_id` or `reviewer_user_id` must be non-null
- `reviewer_role` is derived from the actor at creation time (from `Agent.identity_profile["role"]` for agents, hardcoded `"operator"` for users with LOCAL_AUTH_TOKEN)
- `verdict` must be one of `pass | fail | partial`
- `ac_results` keys must match the task's declared AC identifiers at submission time (stored in task description — parsed by a small helper, not DB-enforced)
- `supersedes_verdict_id` must reference a verdict on the same `task_id`

### 3.2 New join table: `approval_verdict_links`

**File:** `backend/app/models/approval_verdict_links.py`
**Purpose:** many-to-many between approvals and verdicts (one approval may rely on multiple verdicts — QA + Architect + Lead).

```python
class ApprovalVerdictLink(QueryModel, table=True):
    __tablename__ = "approval_verdict_links"

    approval_id: UUID = Field(foreign_key="approvals.id", primary_key=True)
    verdict_id: UUID = Field(foreign_key="task_verdicts.id", primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
```

### 3.3 No changes to existing tables

- `Approval` model: unchanged. The binding is via `ApprovalVerdictLink`, not a column on `approvals`. This preserves the existing schema and avoids a nullable-FK-becomes-required migration path.
- `ApprovalHistory`: unchanged. Still records lifecycle events. The rejection-loop counter continues to use it.
- `ActivityEvent`: unchanged. Verdict submission creates an `ActivityEvent` row for thread visibility (so the Kanban UI still shows "QA-E2E posted PASS verdict on task X"), but the event points to the `TaskVerdict` row via a new optional `verdict_id` field.

**Minor addition** to `ActivityEvent`:
```python
verdict_id: UUID | None = Field(default=None, foreign_key="task_verdicts.id", index=True)
```
This lets the frontend link verdict events to their typed rows without requiring a separate query.

---

## 4. API surface

### 4.1 New endpoint: `POST /api/v1/agent/boards/{board_id}/tasks/{task_id}/verdicts`

**Auth:** agent token (X-Agent-Token) OR LOCAL_AUTH_TOKEN
**Allowed roles:** any agent whose `identity_profile["role"]` is in `{qa_e2e, qa_unit, architect, lead}`, OR any authenticated user (operator override)
**Body (Pydantic schema `VerdictCreate`):**
```python
class VerdictCreate(BaseModel):
    verdict: Literal["pass", "fail", "partial"]
    commit_sha: str | None = None
    artifact_ref: str | None = None
    methodology: str | None = None
    ac_results: dict[str, Literal["pass", "fail", "partial", "n/a"]] = Field(default_factory=dict)
    notes: str | None = None
    supersedes_verdict_id: UUID | None = None
```

**Backend derives at submission time:**
- `reviewer_agent_id` or `reviewer_user_id` from the authenticated actor
- `reviewer_role` from `Agent.identity_profile["role"]` (agents) or hardcoded `"operator"` (users)
- `task_id`, `board_id` from URL path
- `created_at` from `utcnow()`

**Behavior:**
- Creates `TaskVerdict` row
- Creates `ActivityEvent` row with `event_type="task.verdict"`, `verdict_id=<new>`, `message=<notes or default>`
- Returns 201 with the new verdict ID
- Returns 403 if agent role is not allowed
- Returns 422 if schema is invalid

### 4.2 New endpoint: `GET /api/v1/boards/{board_id}/tasks/{task_id}/verdicts`

**Auth:** operator token
**Query params:** `role`, `verdict`, `since` (ISO timestamp)
**Response:** list of `VerdictRead` objects sorted by `created_at DESC`

### 4.3 Updated endpoint: `POST /api/v1/boards/{board_id}/approvals`

**Schema change:** `ApprovalCreate` gains an optional field `relies_on_verdict_ids: list[UUID] = []`.

**New guard function:** `_ensure_verdict_backed_approval_for_move_to_done`

Called inside `create_approval` BEFORE `_ensure_no_rejection_loop`. Logic:

1. If `action_type != "move_to_done"`: return (check only applies to done transitions)
2. Read the board-level feature flag `board.require_verdict_backed_approvals` (new column, default `False` during rollout; set to `True` after migration)
3. If flag is `False`: return (backwards compat)
4. If `len(relies_on_verdict_ids) == 0`: raise 422 `"move_to_done approval requires at least one relies_on_verdict_ids entry"`
5. Load all referenced verdicts from DB. Any that don't exist: raise 422
6. For each verdict, enforce:
   - `verdict.task_id == task_id` (no cross-task citing)
   - `verdict.verdict == "pass"` (no citing FAIL or PARTIAL as a pass)
7. Compute `last_rejection` = most recent `ApprovalHistory` row with `task_id=task_id, event_type="rejected"`
8. If `last_rejection` exists, enforce:
   - For each referenced verdict: `verdict.created_at > last_rejection.created_at`
   - Violation message: `"Verdict {verdict_id} is older than last rejection at {last_rejection.created_at}; post a fresh verdict before re-submitting"`
9. Enforce role coverage:
   - The task's required reviewer roles are derived from the task's `depends_on` and `custom_field_values` (e.g., tasks with i18n scope require a QA-E2E verdict with `methodology IN ('returning_user', 'both')`)
   - This mapping is in a new helper `_required_verdict_roles_for_task(task)` — a simple dict lookup by task type/scope
   - For the first phase: require at least one `reviewer_role IN (qa_e2e, qa_unit, architect)` with `verdict=pass`
10. On pass: write `ApprovalVerdictLink` rows for the approval ⇄ verdict pairs
11. Continue to existing `_ensure_no_rejection_loop` check

### 4.4 Updated `ApprovalHistory` — no change to table, new read pattern

The `_ensure_no_rejection_loop` guard and the new verdict guard both read from `ApprovalHistory`. To avoid double-loading `last_rejection`, extract a helper `_last_rejection_event(session, task_id) -> ApprovalHistory | None` that both guards call.

---

## 5. Template and agent behavior changes

### 5.1 `backend/templates/BOARD_AGENTS.md.j2`

**Add a new section** after the existing re-review rule block, explaining the verdict endpoint:

```markdown
### Posting verdicts (new — replaces free-text PASS/FAIL comments)

When you complete a review (QA or Architect), do NOT post your verdict as a task comment. Instead, POST a typed verdict via the verdicts endpoint:

```bash
curl -fsS -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/verdicts" \
  -H "X-Agent-Token: $AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "verdict": "pass",
    "commit_sha": "0af7a3e",
    "artifact_ref": "test-results/33d552a1-closeout-latest.json",
    "methodology": "returning_user",
    "ac_results": {"1": "pass", "2": "pass", "3": "pass", "4": "pass"},
    "notes": "Full scope validated on live target with Playwright; EN/PT/ES/FR all pass on returning-user scenario."
  }'
```

**Why:** The approval create endpoint now requires `relies_on_verdict_ids` referencing typed verdict rows. Free-text PASS/FAIL comments are no longer accepted as evidence for `move_to_done` approvals. Re-citing a pre-rejection verdict will fail at approval creation time (HTTP 422).

**The re-review rule is now enforced at the API layer:** if you were the reviewer and the task was rejected after your verdict, your verdict is automatically stale and cannot be re-cited. You must post a new verdict (with a new ID, new commit SHA, and new methodology) before the approval can be re-created.
```

### 5.2 Supervisor routing update

The Supervisor creates the approval and currently populates `payload.qa_evidence` as free text. After this change, the Supervisor must:
1. Query the task's recent verdicts via `GET /verdicts`
2. Collect the verdict IDs from QA-E2E and Architect with `verdict=pass` and `created_at > last_rejection.created_at`
3. Pass them in `relies_on_verdict_ids` to the approval create
4. Populate `payload.qa_evidence` as a summary string (still free text, but now for human readability — the enforcement is on the FK, not the string)

Add to the Supervisor section of `BOARD_AGENTS.md.j2`:

```markdown
### Creating move_to_done approvals (updated)

Before creating a move_to_done approval, you MUST:
1. Verify at least one fresh QA verdict exists (post-rejection if there was one)
2. Verify Architect verdict exists (if the task has a review:code_review AC)
3. Collect their IDs and pass to relies_on_verdict_ids

If no fresh verdicts exist, do NOT create the approval. Nudge the appropriate reviewer to post a fresh verdict first.
```

---

## 6. Migration plan

### Phase 0 — schema migration (backwards compatible, feature flagged)

**Alembic revision 1:** `add_task_verdicts_table`
- Create `task_verdicts` table
- Create `approval_verdict_links` join table
- Add nullable `verdict_id` column to `activity_events`
- Add `require_verdict_backed_approvals` bool column to `boards` (default `False`)

**Feature flag:** `boards.require_verdict_backed_approvals`. When `False`, the new guard is a no-op. When `True`, the guard enforces.

### Phase 1 — wire endpoints (flag still `False`)

- Implement `POST /tasks/{id}/verdicts` endpoint
- Implement `GET /tasks/{id}/verdicts` endpoint
- Add `_ensure_verdict_backed_approval_for_move_to_done` guard but gate it on the board flag
- Deploy; nothing changes for existing workflows

### Phase 2 — dogfood on dev-squad board

- Manually set `boards.require_verdict_backed_approvals = True` on the dev-squad board
- Update the dev-squad board's agent templates to use the verdict endpoint
- Sync templates via the existing `POST /gateways/{id}/templates/sync` API
- Observe: do agents successfully use the verdict endpoint? Do approvals flow through the FK-backed path?

### Phase 3 — rollout

- Enable flag on other boards
- Update all templates in the repo
- Leave flag as a per-board override in case a board needs to opt out temporarily

### Phase 4 — tighten

- After all boards are on the new path for ≥1 week with zero approval-create failures due to missing verdicts, consider making the column non-nullable and removing the feature flag
- Add role-specific methodology enforcement (e.g., i18n tasks require `methodology IN ('returning_user', 'both')`)

### Backfill strategy for pre-existing approved approvals

No backfill. Existing approved approvals remain approved. The FK check only fires on NEW approval creations for `move_to_done` actions on boards with the flag enabled. Historical state is untouched — no retroactive invalidation.

---

## 7. Test plan

### Unit tests (`backend/tests/test_task_verdicts.py` — new file)

- `test_create_verdict_as_qa_agent_succeeds`
- `test_create_verdict_as_programmer_agent_forbidden` (role check)
- `test_create_verdict_as_operator_user_succeeds`
- `test_create_verdict_invalid_verdict_value_returns_422`
- `test_create_verdict_with_supersedes_non_existent_id_returns_422`
- `test_create_verdict_with_supersedes_different_task_returns_422`
- `test_get_verdicts_sorted_desc`
- `test_get_verdicts_filtered_by_role`
- `test_get_verdicts_filtered_by_since_timestamp`

### Integration tests (`backend/tests/test_approvals_verdict_binding.py` — new file)

Each test targets one of the four verified anti-patterns:

1. **Stale re-citation blocked.**
   - Setup: task with a PASS verdict at T0, rejection at T1, no new verdict at T2
   - Act: try to create approval with `relies_on_verdict_ids=[T0 verdict id]`
   - Assert: 422 with message about the verdict being older than the last rejection
   - This is the direct test for anti-pattern #1 (Architect re-citing 22:04 PASS)

2. **Clean-session laundering is auditable.**
   - Setup: task with PASS verdict using `methodology="clean_session"` at T0, rejection at T1, new PASS verdict at T2 using `methodology="clean_session"` again
   - Act: create approval with `relies_on_verdict_ids=[T2 verdict id]`
   - Assert: 200 (the check doesn't reject; it just exposes the methodology field for operator review)
   - Note: this test documents that methodology tagging alone is not enforcement — the operator must review

3. **Post-rejection stale re-cite blocked at DB level.**
   - Setup: rejection at T1, verdict at T0 (pre-rejection)
   - Act: create approval citing T0 verdict
   - Assert: 422 with clear error about pre-rejection verdict
   - This is the direct test for anti-pattern #4 (`aa5845af` citing 11:42 artifact after 13:20 rejection)

4. **Multiple verdict types required for multi-role tasks.**
   - Setup: task with `required_verdict_roles=["qa_e2e", "architect"]`, only QA-E2E verdict exists
   - Act: create approval citing only QA-E2E verdict
   - Assert: 422 with message about missing Architect verdict

5. **Operator override via unblock endpoint.**
   - Setup: task with no post-rejection verdict; operator wants to force approval
   - Act: call `POST /{approval_id}/unblock` with a reason
   - Assert: approval goes through; the verdict check is bypassed
   - This confirms the override path already established by `d6174c4`

6. **Backwards compat during rollout.**
   - Setup: board with `require_verdict_backed_approvals=False`
   - Act: create approval with no `relies_on_verdict_ids`
   - Assert: 200 (old path still works)

7. **Cross-task citing blocked.**
   - Setup: verdict on task A, try to cite it in approval for task B
   - Act: create approval for B with `relies_on_verdict_ids=[A verdict]`
   - Assert: 422

---

## 8. Rollback plan

If the feature causes approval-create failures in unexpected ways on a live board:

1. Set `boards.require_verdict_backed_approvals = False` on the affected board — takes effect on next approval-create call, no restart needed
2. The agent templates still reference the verdicts endpoint — this is fine, the endpoint still works, just no longer gates approvals
3. If the schema migration itself needs to be rolled back: the `task_verdicts` table is append-only with no FKs pointing IN to it from the approvals table (the join table is separate). Drop `approval_verdict_links`, drop `task_verdicts`, drop the `verdict_id` column on `activity_events`, drop the flag column on `boards`. One Alembic downgrade.

---

## 9. Open questions

1. **Role derivation reliability.** `reviewer_role` is derived from `Agent.identity_profile["role"]` — a JSONB field that's not indexed and can be edited. Should we normalize this to an `Agent.role` column with an enum? (Separate migration, scope creep for this PR, but the brittleness matters long-term.)

2. **AC identifier parsing.** `ac_results` keys should match the task's AC list. Today ACs are free-text lists in task descriptions. Do we parse them with a simple regex (`^\d+\.\s+...`)? Or require task creators to supply a structured AC list in `custom_field_values`? (Initial scope: accept any string keys, don't validate against the task description.)

3. **Methodology enum vs free-text.** Should `methodology` be a database enum (forces compile-time additions) or free-text string (flexible but lets agents invent new values)? (Initial scope: free-text with template-recommended values. A follow-up can tighten.)

4. **Does `reviewer_role == "operator"` count as "Architect" for role coverage?** If I post an operator verdict, does that satisfy the Architect requirement for tasks that need Architect review? (Initial scope: operator verdict satisfies any role requirement — operator is the terminal gate.)

5. **Multi-board / cross-board tasks.** Not currently a concern, but if a task is moved between boards, the `board_id` on `task_verdicts` might not match the destination board. (Initial scope: lock verdict to the board the task was on at verdict creation time. If the task moves, the verdict follows via `task_id`.)

6. **Concurrent verdict races.** Two reviewers post verdicts at the same time. Should the later one automatically set `supersedes_verdict_id` on the earlier? (Initial scope: no automatic supersession. Reviewers explicitly set it when retesting.)

---

## 10. Estimated scope

- New model file + schema: ~80 LOC
- New join table model: ~20 LOC
- New endpoints (POST + GET): ~120 LOC
- New guard function: ~60 LOC
- Alembic migration: ~80 LOC
- Template changes: ~50 lines of BOARD_AGENTS.md.j2 updates
- Unit tests: ~200 LOC
- Integration tests: ~400 LOC
- Docstrings, error messages, logging: ~80 LOC

**Total:** ~1,100 LOC net new, one schema migration, two new endpoints, one updated endpoint guard, one template section.

**Time estimate:** ~1 focused day for an experienced FastAPI/SQLModel developer. Add ~0.5 day for template syncing and dogfooding on the dev-squad board.

---

## 11. What this does NOT fix

- **Reviewer honesty.** A QA agent can still post a PASS verdict with a lie in the `methodology` field. The backend records the claim but cannot validate it. The operator is still the terminal gate for catching this.
- **Incorrect AC interpretation.** If a reviewer interprets an AC loosely and passes it when they shouldn't, the verdict is typed and traceable but still wrong.
- **Out-of-band bypasses.** If an operator directly PATCHes the `approvals` table or uses a privileged database fixture, they can still approve anything. The operator role is assumed to be trusted.
- **Heartbeat-time agent bugs.** Hallucinations like the phantom AC #7 still happen. What changes: instead of the Supervisor spending 15 minutes on a 4-agent coordination thread clarifying a non-existent AC, the Supervisor sees a `TaskVerdict` with `ac_results={"AC #7": "fail"}` — an invalid AC key that the frontend can flag immediately, cutting the debate short.

---

## 12. Relationship to existing enforcement

| Layer | Commit | Fires on | What it checks |
|---|---|---|---|
| Template prose | `5cbd8ad` | Agent heartbeat | "re-test, not re-cite" guidance (no enforcement) |
| Rejection count | `d6174c4` | `create_approval` | ≥4 rejections in 24h → 409 unless unblocked |
| **Verdict binding (new)** | **this spec** | **`create_approval`** | **at least one typed verdict row with `created_at > last_rejection.created_at`** |
| Operator override | `d6174c4` | `POST /unblock` | manual reset by authenticated user/lead |

The three enforcement layers are complementary. The verdict binding fires first (catches stale re-cites before the rejection counter matters). The rejection counter catches repeated-bad-verdict patterns (counts rejections over time). The unblock endpoint catches both.

---

## Decision needed

Approve this design for implementation, request revisions, or reject. If approved, the next step is a detailed implementation plan via `superpowers:writing-plans` and then execution.
