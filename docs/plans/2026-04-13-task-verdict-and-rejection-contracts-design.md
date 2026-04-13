# First-class verdicts + rejection-resolution contracts

**Status:** DRAFT — merged design spec, not yet approved for implementation
**Authors:** operator (Claude) + prior session (Claude Opus 4.6 + Codex gpt-5.4 high)
**Date:** 2026-04-13
**Supersedes:**
- `2026-04-13-task-verdict-first-class-design.md` (earlier today, same session) — schema proposal without proof-type enforcement
- `2026-04-13-rejection-resolution-contracts-design.md` (prior session, 22:56 yesterday) — text-block contracts without first-class rows

Both prior designs converged on the same anti-patterns and the same layered-enforcement philosophy. This doc merges their complementary strengths: typed verdict rows as the storage layer, failure-class taxonomy + proof-type matching as the enforcement constraint, a probe library as the substrate for real evidence production.

**Related commits:**
- `d6174c4` / `8376f37` — API-level rejection-loop counter (already shipped, kept as escalation layer)
- `5cbd8ad` — re-review rule as template prose (already shipped, insufficient alone)
- `350ae7d` — explicit-assignment fix for rework routing (already shipped)

**Related incidents:** Dev-Squad board session 2026-04-12 → 2026-04-13 (task churn on `633fb35e`, `33d552a1`, `d51a3a62`)

---

## 1. Problem

Mission Control's current approval model treats approvals as authoritative state without typed binding to the review evidence they relied on. "Freshness" is inferred from human-readable prose in `payload.qa_evidence` (a free-form text field) and from comment timestamps. The approval guard `_ensure_no_rejection_loop` counts rejections but does not inspect evidence quality. The template-level re-review rule is prose guidance that LLM agents routinely violate under heartbeat pressure.

Four verified anti-patterns observed in a single session (forensic audit available):

1. **Stale-verdict re-citation.** Architect posted "6/6 PASS at 22:04 UTC" on task `633fb35e`, then re-cited that same PASS across four subsequent comments on parent task `d51a3a62` (22:41, 22:42, 22:55, 23:12 UTC) without running a new test. The task had real functional bugs that a fresh test would have caught.

2. **Clean-session laundering.** QA-E2E posted 7/7 PASS at 11:03 UTC, then a fresh re-validation at 11:33 UTC that FAILED 9/12 on PT-BR `document.documentElement.lang`, then a third run at 11:42 UTC with "clean session / cookie clear between routes" methodology that PASSED again. The Supervisor accepted the 11:42 clean-session pass as "newest evidence" superseding the 11:33 FAIL. The underlying bug was a real returning-user initial-load failure that clean-session testing trivially masked. The bug shipped as "approved" until operator re-verification caught it hours later.

3. **Phantom AC false alarm.** QA-E2E at 03:16 UTC claimed a FAIL on a non-existent "AC #7"; self-corrected at 03:17 UTC; Supervisor clarified at 03:20 UTC that the task has 4 task-specific + 4 general ACs. Four agents burned ~15 minutes of heartbeat time on a hallucinated regression.

4. **Post-rejection stale re-cite.** Operator rejected approval `00b52ed9` at 13:20:54 UTC. Operator posted a fix commit `d0c612e` at ~13:22 UTC. At 13:25:29 UTC a new approval `aa5845af` was created with `qa_evidence` literally referencing the "2026-04-13 11:42 UTC clean-session PASS artifact" — the exact evidence the operator had just called stale. The re-submission cited pre-rejection evidence with no acknowledgment that the rejection had occurred.

The common primitive: **agents can mint fresh-looking evidence by posting prose**. Until the backend distinguishes verdict artifacts from ordinary comments AND binds approvals to specific post-rejection verdicts AND enforces that worker proof-type matches what the reviewer asked for, the re-review rule is unenforceable at runtime.

The canonical worst case is task `633fb35e`: AC "Language switcher integration remains functional." Implementation was a bare HTML `<select>` with no `onChange` handler and no React state binding — pure cosmetic DOM. Worker validation: `querySelector('[data-testid="..."]')` confirmed the element exists, marked PASS. Architect review: confirmed the options list (EN/PT-BR/ES/FR) is present, marked PASS. Operator rejection: Chrome MCP click + state-change observation proved selecting a language produced zero observable change. Worker response over 3 rejection cycles: zero code bytes modified. The system accepted narrative as evidence of fix instead of observable proof that the rejected behavior no longer reproduces.

---

## 2. Goals and non-goals

### Goals

- **Typed verdict artifacts.** Reviewer verdicts (QA, Architect, Lead, operator) become first-class rows with reviewer identity, commit/artifact reference, methodology tag, per-AC results, and failure classification — not free-text comments.
- **Approval→verdict binding.** A `move_to_done` approval MUST reference at least one `TaskVerdict` row. The approval create endpoint validates that the referenced verdicts are (a) PASS, (b) created after the last rejection on this task, (c) from appropriate reviewer roles for the task.
- **Failure classification on rejection.** When a reviewer rejects, they MUST attach a `failure_class` and `required_proof_type` to the rejection verdict. This creates a falsifiable contract: "this specific failure mode must be proven gone."
- **Proof-type matching on resubmission.** When a worker posts a new verdict after a rejection, the new verdict's `methodology` MUST match the prior rejection's `required_proof_type`, and the `proof_output` field MUST be non-empty. Empty proof or mismatched type returns HTTP 422.
- **Unbypassable post-rejection freshness.** A DB-level FK timestamp check cannot be defeated by posting filler prose, by regex tricks, or by renaming agents.
- **Probe library as the proof-production substrate.** Provide runnable scripts for the 4 most common failure classes (state_change, persistence, auth, live_update). Workers and reviewers invoke them and paste structured JSON output into their `proof_output` fields.
- **Operator override preserved.** The existing `POST /approvals/{id}/unblock` endpoint remains the only way an operator bypasses the check, matching the pattern already established by `d6174c4`.
- **Backwards compatibility during transition.** Existing approvals without verdict references must continue to work until a feature flag cut-over.

### Non-goals

- **Semantic verdict validation.** The backend does not judge whether a PASS is correct. It only enforces that typed verdicts exist with the right timing, scope, and proof-type match. Correctness is still a reviewer's responsibility — what changes is that reviewers cannot retroactively re-cite their own pre-rejection work, and workers cannot submit empty proof.
- **Git binding in the hot path.** Commit SHAs are stored as strings for traceability. The backend does NOT run `git merge-base`, does NOT fetch repos, does NOT validate SHA ancestry. Three independent reviewers (two subagents + Codex gpt-5.4 high) confirmed git binding creates more availability and complexity problems than it solves.
- **Replacing `_ensure_no_rejection_loop`.** The rejection-loop counter is kept as a separate escalation gate (triggers operator unblock after N rejections in 24h). The new verdict binding is an additional layer that fires earlier.
- **Probe output correctness validation.** The API enforces that `proof_output` exists and has the right type. It cannot enforce that the pasted output actually proves what the worker claims. The probe library makes gaming the output harder (there's a schema) but does not eliminate it. The re-review requirement (reviewer must produce their own fresh evidence) catches worker fakes at the next layer.
- **Catching first-submission defects.** Contracts activate only on rejection. The first review is still narrative-based. If a reviewer approves a broken first submission, that's a reviewer-correctness failure, not a contract failure.
- **Coverage enforcement for all task types.** Initial scope: `move_to_done` approvals only. Other action types are out of scope for this change.
- **Replacing the Architect role.** Architect reviews continue. Contracts constrain what counts as a valid Architect verdict; they don't eliminate the role.

---

## 3. Data model

### 3.1 New table: `task_verdicts`

**File:** `backend/app/models/task_verdicts.py`
**Migration:** new Alembic revision `<rev>_add_task_verdicts.py`

```python
class TaskVerdict(QueryModel, table=True):
    __tablename__ = "task_verdicts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)

    # Reviewer identity — derived at submission time from the authenticated actor, not trusted from client
    reviewer_agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    reviewer_user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    reviewer_role: str = Field(index=True)
    # enum-like strings: "qa_e2e" | "qa_unit" | "architect" | "lead" | "operator" | "dev" (for self-verdict on resubmission)

    # Verdict value
    verdict: str = Field(index=True)  # "pass" | "fail" | "partial"

    # Artifact traceability — strings only, NOT validated as git refs
    commit_sha: str | None = Field(default=None, index=True)
    artifact_ref: str | None = None  # e.g. "test-results/33d552a1-closeout-latest.json", "playwright-trace-abc.zip"

    # Rejection-side contract fields (required when verdict == "fail")
    failure_class: str | None = Field(default=None, index=True)
    # enum-like: "state_change" | "persistence" | "auth" | "live_update" | "other"
    required_proof_type: str | None = None
    # enum-like: "browser_behavioral" | "api_roundtrip" | "db_state" | "unit_test" | "compiled_bundle" | "static_only"
    repro_step: str | None = None  # "concrete steps that currently fail"
    expected_observable_change: str | None = None  # "what the fixed state should show"
    required_proof_surface: str | None = None  # free text: selectors, URLs, endpoints

    # Resubmission/pass-side evidence fields (required when verdict == "pass" AND a prior rejection exists on this task)
    methodology: str | None = Field(default=None, index=True)
    # enum-like matching rejection.required_proof_type: "browser_behavioral" | "api_roundtrip" | etc.
    proof_output: str | None = None  # raw probe output, structured JSON, or reviewer-written free text

    # Per-AC results
    ac_results: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    # keys: AC identifiers ("1", "2", "3", etc.); values: "pass" | "fail" | "partial" | "n/a"

    # Lineage
    supersedes_verdict_id: UUID | None = Field(default=None, foreign_key="task_verdicts.id", index=True)

    # Freeform reviewer notes — replaces comment prose for verdict rationale
    notes: str | None = None

    created_at: datetime = Field(default_factory=utcnow, index=True)
```

**Key invariants (enforced in Pydantic validator, not DB constraint):**

- Exactly one of `reviewer_agent_id` or `reviewer_user_id` must be non-null
- `reviewer_role` is derived from the actor at creation time (from `Agent.identity_profile["role"]` for agents, hardcoded `"operator"` for users with LOCAL_AUTH_TOKEN)
- `verdict` must be one of `pass | fail | partial`
- If `verdict == "fail"`: `failure_class`, `required_proof_type`, and `repro_step` are REQUIRED (can't reject without classifying)
- If `verdict == "pass"` AND a prior `verdict == "fail"` exists on this task: `methodology`, `proof_output`, and `supersedes_verdict_id` are REQUIRED, AND `methodology` must match the prior rejection's `required_proof_type`
- `ac_results` keys should align with the task's declared AC identifiers (initial scope: accept any string keys, don't validate against task description)
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

### 3.3 Minor change to `activity_events`

Add an optional `verdict_id` column so verdict events link cleanly to the typed row without a separate query:

```python
verdict_id: UUID | None = Field(default=None, foreign_key="task_verdicts.id", index=True)
```

### 3.4 Feature flag column on `boards`

```python
require_verdict_backed_approvals: bool = Field(default=False, index=False)
```

Default `False` during rollout; set to `True` per-board after migration.

### 3.5 No changes to existing `Approval` or `ApprovalHistory` tables

- `Approval`: unchanged. Binding is via `ApprovalVerdictLink`, not a column on `approvals`. Preserves existing schema and avoids a nullable-FK-becomes-required migration path.
- `ApprovalHistory`: unchanged. The rejection-loop counter continues to use it as-is.

---

## 4. API surface

### 4.1 New endpoint: `POST /api/v1/agent/boards/{board_id}/tasks/{task_id}/verdicts`

**Auth:** agent token (X-Agent-Token) OR LOCAL_AUTH_TOKEN

**Allowed roles:** any agent whose `identity_profile["role"]` is in `{qa_e2e, qa_unit, architect, lead, dev}`, OR any authenticated user (operator override). `dev` role is allowed for self-verdicts on resubmission (worker produces their own proof that the bug is gone).

**Body (`VerdictCreate`):**

```python
class VerdictCreate(BaseModel):
    verdict: Literal["pass", "fail", "partial"]

    # Reject-side (required when verdict == "fail")
    failure_class: Literal["state_change", "persistence", "auth", "live_update", "other"] | None = None
    required_proof_type: Literal["browser_behavioral", "api_roundtrip", "db_state", "unit_test", "compiled_bundle", "static_only"] | None = None
    repro_step: str | None = None
    expected_observable_change: str | None = None
    required_proof_surface: str | None = None

    # Pass-side (required when posting a resubmission verdict after a prior rejection on this task)
    methodology: str | None = None
    proof_output: str | None = None

    # Shared
    commit_sha: str | None = None
    artifact_ref: str | None = None
    ac_results: dict[str, Literal["pass", "fail", "partial", "n/a"]] = Field(default_factory=dict)
    notes: str | None = None
    supersedes_verdict_id: UUID | None = None
```

**Backend derives at submission time:**
- `reviewer_agent_id` or `reviewer_user_id` from the authenticated actor
- `reviewer_role` from `Agent.identity_profile["role"]` (agents) or hardcoded `"operator"` (users)
- `task_id`, `board_id` from URL path
- `created_at` from `utcnow()`

**Guard function: `_ensure_valid_verdict_schema`**

Called inside the POST handler. Logic:

1. If `verdict == "fail"`:
   - Reject 422 if `failure_class`, `required_proof_type`, or `repro_step` is missing
2. If `verdict == "pass"`:
   - Query for the most recent `task_verdicts` row on this `task_id` with `verdict == "fail"`, ordered by `created_at DESC`
   - If no prior rejection exists: proceed (first-submission pass, no matching required)
   - If a prior rejection exists: enforce
     - `methodology` is non-empty
     - `methodology` equals the prior rejection's `required_proof_type`
     - `proof_output` is non-empty
     - `supersedes_verdict_id` equals the prior rejection's `id`
     - Reject 422 on any violation with a clear message pointing at the mismatch
3. If `supersedes_verdict_id` is supplied, the referenced verdict must exist and be on the same `task_id`

**Behavior:**
- Creates `TaskVerdict` row
- Creates an `ActivityEvent` row with `event_type="task.verdict"`, `verdict_id=<new>`, `message=<notes or default>` for thread visibility
- Returns 201 with the new verdict ID

### 4.2 New endpoint: `GET /api/v1/boards/{board_id}/tasks/{task_id}/verdicts`

**Auth:** operator token or agent token
**Query params:** `role`, `verdict`, `since` (ISO timestamp)
**Response:** list of `VerdictRead` objects sorted by `created_at DESC`

Lets Supervisor (and operator) query recent verdicts when constructing an approval.

### 4.3 Updated endpoint: `POST /api/v1/boards/{board_id}/approvals`

**Schema change:** `ApprovalCreate` gains a new field `relies_on_verdict_ids: list[UUID] = []`.

**New guard function: `_ensure_verdict_backed_approval_for_move_to_done`**

Called inside `create_approval` BEFORE `_ensure_no_rejection_loop`. Logic:

1. If `action_type != "move_to_done"`: return (check only applies to done transitions)
2. Read the board-level feature flag `board.require_verdict_backed_approvals`
3. If flag is `False`: return (backwards compat)
4. If `len(relies_on_verdict_ids) == 0`: raise 422 `"move_to_done approval requires at least one relies_on_verdict_ids entry"`
5. Load all referenced verdicts from DB. Any that don't exist: raise 422
6. For each verdict, enforce:
   - `verdict.task_id == task_id` (no cross-task citing)
   - `verdict.verdict == "pass"` (no citing FAIL or PARTIAL as a pass)
7. Compute `last_rejection` = most recent `task_verdicts` row on this `task_id` with `verdict == "fail"`, fallback to `ApprovalHistory` event_type=rejected if no verdict row exists yet (for backwards compat during transition)
8. If `last_rejection` exists, enforce for each referenced verdict:
   - `verdict.created_at > last_rejection.created_at`
   - Violation message: `"Verdict {verdict_id} is older than last rejection at {last_rejection.created_at}; post a fresh verdict before re-submitting"`
9. Enforce role coverage:
   - Compute `required_roles_for_task` based on a small helper that inspects task scope tags / custom fields
   - Initial scope: require at least one `reviewer_role IN (qa_e2e, qa_unit, architect)` with `verdict == "pass"` among the referenced verdicts
10. On pass: write `ApprovalVerdictLink` rows for the approval ⇄ verdict pairs
11. Continue to existing `_ensure_no_rejection_loop` check

### 4.4 Existing `POST /approvals/{id}/unblock` — unchanged

The operator override path is unchanged. If any verdict check fails and the operator needs to force an approval for a legitimate edge case (scope-rejection, revert, hotfix), they use `POST /unblock` with a reason, same as today.

---

## 5. Probe library

### 5.1 Location and shape

`backend/tests/probes/*.mjs` — runnable Node scripts, one per failure class, parameterized via environment or CLI args.

Each probe:
- Accepts a target URL, task ID, and per-class parameters
- Runs a standard coverage set of checks (see §5.2)
- Outputs structured JSON to stdout
- Exits with `0` on all-pass, `1` on any-fail
- Never mutates state beyond what's required to exercise the behavior being probed

### 5.2 Initial 4 classes and coverage sets

Chosen by actual incident frequency on the dev-squad board, not conceptual neatness.

| Class | Description | Minimum coverage set (3 probes) |
|---|---|---|
| `state_change` | User interaction produces a documented observable change. Examples: toggles, dropdowns, buttons, language switchers, dark mode. | (a) interaction produces visual change, (b) source of truth updates (localStorage, state, URL), (c) reload preserves state |
| `persistence` | Data survives a reload. | (a) write response body contains saved field, (b) read response body contains saved field, (c) reload UI still shows it |
| `auth` | Access is gated, not just visually hidden. | (a) unauth → redirect to `/login`, (b) protected content absent from DOM, (c) API returns 401/403 |
| `live_update` | Async state transitions (SSE, websocket, polling). | (a) trigger event, (b) client reflects within N seconds, (c) state consistent after disconnect/reconnect |

Workers must hit ALL THREE probes of a class for the proof to count. This prevents "probe myopia" where a single hero-text check passes while nav items are still broken.

**i18n is a specialization of `state_change`**, not a separate class. It uses the state_change probe with the "visual state change" coverage element being "text in 3+ page regions changes to the target locale" — which, had it been available as a probe, would have caught the `633fb35e` bare `<select>` bug on the first Worker validation cycle.

### 5.3 Probe output contract

Each probe emits JSON shaped like:

```json
{
  "probe": "state_change",
  "task_id": "633fb35e-...",
  "target": "http://192.168.2.60:3000/",
  "ran_at": "2026-04-13T13:34:01Z",
  "coverage": {
    "interaction_produces_visual_change": {"pass": true, "detail": "..."},
    "source_of_truth_updates": {"pass": true, "detail": "..."},
    "reload_preserves_state": {"pass": true, "detail": "..."}
  },
  "overall_verdict": "pass"
}
```

The worker or reviewer pastes the entire JSON blob into `proof_output` when creating a verdict. The API stores it as a string but validates that the `probe` field matches the rejection's `required_proof_type` (e.g. `required_proof_type="browser_behavioral"` maps to `probe` in `{state_change, persistence, live_update}`).

### 5.4 Probes are advisory at v1, enforced at v2

At v1, workers and reviewers are NOT required to use probes. They can hand-write the `proof_output` field. The enforcement is: `proof_output` must be non-empty AND `methodology` must match `required_proof_type`. Probes just make it easier to produce the right shape.

At v2, after observing real-world usage, consider requiring probes for specific failure classes (e.g. `required_proof_type="browser_behavioral"` MUST have `proof_output` that parses as the probe JSON schema).

---

## 6. Template and agent behavior changes

### 6.1 `backend/templates/BOARD_AGENTS.md.j2`

**Add a new section** after the existing re-review rule block:

```markdown
### Posting verdicts (new — replaces free-text PASS/FAIL comments)

When you complete a review (QA or Architect) OR when you submit a fix as a worker after a rejection, do NOT post your verdict as a task comment. Instead, POST a typed verdict via the verdicts endpoint.

**Reviewer rejecting a task:**
```bash
curl -fsS -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/verdicts" \
  -H "X-Agent-Token: $AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "verdict": "fail",
    "failure_class": "state_change",
    "required_proof_type": "browser_behavioral",
    "repro_step": "Open http://192.168.2.60:3000/, select PT-BR from footer, observe document.documentElement.lang stays \"en\"",
    "expected_observable_change": "document.documentElement.lang updates to \"pt\" on PT-BR selection",
    "required_proof_surface": "http://192.168.2.60:3000/ landing page, footer language select",
    "ac_results": {"3": "fail"},
    "notes": "Language switcher integration is not functional for returning users"
  }'
```

**Worker fixing and resubmitting:**
```bash
# First, run the probe that matches the required_proof_type
node backend/tests/probes/state_change.mjs \
  --target http://192.168.2.60:3000/ \
  --interaction "select_language_PT_BR" \
  --expected-change "document.documentElement.lang=pt" \
  > /tmp/fix-proof.json

# Then post a verdict citing the probe output and the fix commit
curl -fsS -X POST "$BASE_URL/api/v1/agent/boards/$BOARD_ID/tasks/$TASK_ID/verdicts" \
  -H "X-Agent-Token: $AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "verdict": "pass",
    "methodology": "browser_behavioral",
    "proof_output": "'"$(cat /tmp/fix-proof.json | jq -Rs .)"'",
    "commit_sha": "d0c612e",
    "supersedes_verdict_id": "<rejection-verdict-id>",
    "ac_results": {"1": "pass", "2": "pass", "3": "pass", "4": "pass"},
    "notes": "Fixed by adding .then() on i18n.init() to sync html lang on initial load"
  }'
```

**Reviewer re-reviewing after a fix:**

The reviewer CANNOT cite their own previous PASS verdict. They must run the probe themselves and post a new verdict with their own `proof_output`. The API enforces this by requiring that every PASS verdict after a rejection have `methodology == prior_rejection.required_proof_type` and non-empty `proof_output`.

**Why:** the approval create endpoint now requires `relies_on_verdict_ids` referencing typed verdict rows. Free-text PASS/FAIL comments are no longer accepted as evidence for `move_to_done` approvals. Re-citing a pre-rejection verdict will fail at approval creation time (HTTP 422). The re-review rule is now enforced at the API layer: if you were the reviewer and the task was rejected after your verdict, your verdict is automatically stale and cannot be re-cited.
```

### 6.2 Supervisor routing update

The Supervisor currently populates `payload.qa_evidence` as free text. After this change, the Supervisor must:

1. Query the task's recent verdicts via `GET /verdicts`
2. Collect the verdict IDs from qualifying reviewers (QA-E2E, Architect) with `verdict=pass` and `created_at > last_rejection.created_at`
3. Pass them in `relies_on_verdict_ids` to the approval create
4. Populate `payload.qa_evidence` as a human-readable summary (free text, no longer enforced — the binding is on the FK)

If no fresh qualifying verdicts exist, the Supervisor does NOT create the approval; they nudge the appropriate reviewer to post a fresh verdict first.

### 6.3 Budget check

Template size budget: the existing `BOARD_AGENTS.md.j2` has 3 variants (lead, worker, QA/review). Each variant has a per-file char budget (23000 for lead on the current dev-squad config). The verdict section adds ~1.2KB raw which fits in all 3 variants after a ~500-byte trim of the obsolete free-text PASS/FAIL guidance that the verdict endpoint replaces. Budget check: PASS.

---

## 7. Migration plan

### Phase 0 — schema migration (backwards compatible, feature flagged)

**Alembic revision 1:** `add_task_verdicts_and_approval_links`
- Create `task_verdicts` table
- Create `approval_verdict_links` join table
- Add nullable `verdict_id` column to `activity_events`
- Add `require_verdict_backed_approvals` bool column to `boards` (default `False`)

**Feature flag:** `boards.require_verdict_backed_approvals`. When `False`, the new guard is a no-op. When `True`, the guard enforces.

### Phase 1 — wire endpoints (flag still `False` on all boards)

- Implement `POST /tasks/{id}/verdicts` endpoint with `_ensure_valid_verdict_schema` guard
- Implement `GET /tasks/{id}/verdicts` endpoint
- Add `_ensure_verdict_backed_approval_for_move_to_done` guard but gate it on the board flag
- Deploy; nothing changes for existing workflows

### Phase 2 — probe library and templates

- Write 4 probes as standalone `.mjs` scripts in `backend/tests/probes/`
- Each probe outputs structured JSON and exits with correct codes
- Update `BOARD_AGENTS.md.j2` with the verdict section (§6.1)
- Update `BOARD_AGENTS.md.j2` Supervisor section (§6.2)
- Template size budget check across lead/worker/QA variants
- Deploy template via `POST /gateways/{id}/templates/sync`

### Phase 3 — dogfood on dev-squad board

- Manually set `boards.require_verdict_backed_approvals = True` on the dev-squad board only
- Observe for at least 24 hours: do agents successfully use the verdict endpoint? Do approvals flow through the FK-backed path? Do rejection cycles shorten?
- Metrics to track:
  - Approval create 422 rate (expected to spike initially, then decline as agents adapt)
  - Rejection-loop count per task (expected to decline)
  - Mean time from first rejection to done (expected to increase initially as agents actually run probes, then decline as probes become cheap)

### Phase 4 — rollout to other boards

- Enable flag on other boards one at a time
- Update any board-specific templates that diverge from `BOARD_AGENTS.md.j2`
- Leave flag as a per-board override in case a board needs to opt out temporarily

### Phase 5 — tighten

- After all boards are on the new path for ≥1 week with zero approval-create failures due to missing verdicts, consider:
  - Making the feature flag default `True` and removing the per-board opt-out
  - Requiring `proof_output` to parse as probe JSON for `required_proof_type IN (state_change, persistence, auth, live_update)` — closing the "hand-written output" bypass
  - Expanding the failure class taxonomy based on incident frequency on each board

### Backfill strategy for pre-existing approvals

No backfill. Existing approved approvals remain approved. The FK check only fires on NEW approval creations for `move_to_done` actions on boards with the flag enabled. Historical state is untouched — no retroactive invalidation.

---

## 8. Test plan

### Unit tests (`backend/tests/test_task_verdicts.py` — new file)

- `test_create_fail_verdict_as_qa_agent_succeeds`
- `test_create_fail_verdict_without_failure_class_returns_422`
- `test_create_fail_verdict_without_repro_step_returns_422`
- `test_create_fail_verdict_without_required_proof_type_returns_422`
- `test_create_pass_verdict_first_submission_succeeds`
- `test_create_pass_verdict_after_rejection_without_methodology_returns_422`
- `test_create_pass_verdict_after_rejection_with_mismatched_methodology_returns_422`
- `test_create_pass_verdict_after_rejection_with_empty_proof_output_returns_422`
- `test_create_pass_verdict_after_rejection_with_matching_methodology_and_proof_output_succeeds`
- `test_create_verdict_as_programmer_agent_with_dev_role_succeeds_for_resubmission`
- `test_create_verdict_as_programmer_agent_forbidden_for_reviewer_role_tasks`
- `test_create_verdict_with_supersedes_wrong_task_returns_422`
- `test_get_verdicts_sorted_desc`
- `test_get_verdicts_filtered_by_role`
- `test_get_verdicts_filtered_by_since_timestamp`

### Integration tests (`backend/tests/test_approvals_verdict_binding.py` — new file)

Each test targets one of the four verified anti-patterns.

1. **Stale re-citation blocked (anti-pattern 1).**
   - Setup: PASS verdict V1 at T0, rejection verdict V2 at T1, no new verdict at T2
   - Act: try to create approval with `relies_on_verdict_ids=[V1]`
   - Assert: 422 with message about V1 being older than V2
   - Direct test for Architect re-citing 22:04 PASS

2. **Clean-session laundering exposed (anti-pattern 2).**
   - Setup: rejection verdict V1 with `required_proof_type="browser_behavioral"`, worker posts V2 with `methodology="browser_behavioral"` and `proof_output="clean-session PASS"`, then a fresh V3 with `methodology="browser_behavioral"` and `proof_output="returning-user PASS"`
   - Act: operator queries GET /verdicts, sees both methodology+output for review
   - Assert: both V2 and V3 are recorded with their methodology tags; operator can see what methodology each reviewer claimed
   - Note: the test documents that methodology tagging exposes the issue for operator review, even though the API cannot reject clean_session outputs semantically

3. **Phantom AC false alarm reduced (anti-pattern 3).**
   - Setup: task with AC list `{"1", "2", "3", "4"}` (task-specific) + `{"G1", "G2", "G3", "G4"}` (general)
   - Act: agent posts a rejection verdict with `ac_results={"7": "fail"}`
   - Assert: at v1, the API accepts the invalid AC key (per non-goal §2). The frontend flags the mismatched key, cutting the multi-agent debate short.
   - Note: v2 can tighten this to reject at API level after AC parsing is first-class

4. **Post-rejection stale re-cite blocked at FK level (anti-pattern 4).**
   - Setup: rejection verdict V1 at T0, pre-rejection PASS verdict V0 from an earlier cycle
   - Act: create approval with `relies_on_verdict_ids=[V0]`
   - Assert: 422 with clear error about V0 being older than V1
   - Direct test for `aa5845af` citing the 11:42 clean-session artifact after the 13:20 rejection

5. **Proof-type match required.**
   - Setup: rejection verdict V1 with `required_proof_type="browser_behavioral"`
   - Act: worker posts PASS verdict with `methodology="static_only"`, `supersedes_verdict_id=V1`, `proof_output="grep found the string"`
   - Assert: 422 with message "methodology 'static_only' does not match rejection.required_proof_type 'browser_behavioral'"

6. **Multiple verdict types required for multi-role tasks.**
   - Setup: task with required roles `{qa_e2e, architect}`, only QA-E2E PASS verdict exists
   - Act: create approval citing only QA-E2E verdict
   - Assert: 422 with message about missing Architect verdict

7. **Cross-task citing blocked.**
   - Setup: verdict V1 on task A
   - Act: create approval for task B with `relies_on_verdict_ids=[V1]`
   - Assert: 422

8. **Operator override via unblock endpoint.**
   - Setup: rejection verdict exists, operator has no time to post a fresh verdict, needs to force approval for a scope-rejection edge case
   - Act: call `POST /{approval_id}/unblock` with a reason
   - Assert: approval goes through; verdict check bypassed
   - Confirms the existing override path is still functional

9. **Backwards compat during rollout.**
   - Setup: board with `require_verdict_backed_approvals=False`
   - Act: create approval with no `relies_on_verdict_ids`
   - Assert: 200 (old path still works)

10. **Revert/rollback works normally.**
   - Setup: rejection verdict V1 exists, the "fix" is a revert (older commit, older tree)
   - Act: worker posts PASS verdict with `methodology` matching V1's `required_proof_type`, `proof_output` from running the probe on the reverted state
   - Assert: 200 — the check is on freshness of the VERDICT, not the commit tree

### Probe tests (`backend/tests/test_probes.py` — new file)

- `test_state_change_probe_all_pass`
- `test_state_change_probe_fails_on_missing_interaction`
- `test_persistence_probe_all_pass`
- `test_auth_probe_all_pass`
- `test_live_update_probe_all_pass`
- For each probe: test that the JSON output shape matches the contract in §5.3

---

## 9. Rollback plan

If the feature causes approval-create failures in unexpected ways on a live board:

1. Set `boards.require_verdict_backed_approvals = False` on the affected board — takes effect on next approval-create call, no restart needed.
2. The agent templates still reference the verdicts endpoint — this is fine, the endpoint still works, just no longer gates approvals.
3. If the schema migration itself needs to be rolled back: the `task_verdicts` table has only one incoming FK (from `approval_verdict_links`, which is separate). Drop `approval_verdict_links`, drop `task_verdicts`, drop the `verdict_id` column on `activity_events`, drop the flag column on `boards`. One Alembic downgrade.

---

## 10. Open questions

1. **Role derivation reliability.** `reviewer_role` is derived from `Agent.identity_profile["role"]` — a JSONB field that's not indexed and can be edited. Should we normalize this to an `Agent.role` column with an enum? Separate migration, scope creep for this PR, but the brittleness matters long-term.

2. **AC identifier parsing.** `ac_results` keys should match the task's AC list. Today ACs are free-text lists in task descriptions. Do we parse them with a simple regex (`^\d+\.\s+...`)? Or require task creators to supply a structured AC list in `custom_field_values`? Initial scope: accept any string keys, don't validate against the task description. Tightens at v2.

3. **Methodology → required_proof_type mapping.** The reject side has `required_proof_type` as an enum (browser_behavioral, api_roundtrip, db_state, unit_test, compiled_bundle, static_only). The pass side has `methodology` which must match. Should these be the same enum? Or should `methodology` be more specific (e.g., `browser_behavioral:returning_user_scenario`)? Initial scope: same enum, the specificity is captured in `proof_output` text.

4. **Probe implementation language.** Node/Playwright for browser probes is natural. But `api_roundtrip` could be curl + bash, `db_state` could be psql, `unit_test` could be pytest. Do we standardize on one language per probe family, or accept mixed? Initial scope: each probe is its own runtime — `.mjs` for browser, `.sh` or `.py` for API/DB/unit. The probe library directory has one subdirectory per class.

5. **Does `reviewer_role == "operator"` count as "Architect" for role coverage?** If the operator posts a verdict, does that satisfy the Architect requirement for tasks that need Architect review? Initial scope: operator verdict satisfies any role requirement — operator is the terminal gate. Document this in template.

6. **Multi-board / cross-board tasks.** Not currently a concern, but if a task is moved between boards, the `board_id` on `task_verdicts` might not match the destination board. Initial scope: lock verdict to the board the task was on at verdict creation time. If the task moves, the verdict follows via `task_id`.

7. **Concurrent verdict races.** Two reviewers post verdicts at the same time. Should the later one automatically set `supersedes_verdict_id` on the earlier? Initial scope: no automatic supersession. Reviewers explicitly set it when retesting.

8. **What about rejections for reasons unrelated to evidence quality?** E.g., the operator rejects because of a scope constraint (task is out of scope for this sprint), not a bad verdict. Does requiring a fresh verdict make sense? Answer: no — but the existing `POST /unblock` endpoint is the right escape hatch. Operator force-unblocks, posts a reason, approval proceeds without a new verdict. Document in the override guidance.

9. **Probe output fakeability.** The worker can still paste fake `proof_output`. What stops them? The re-review requirement. A reviewer posting a PASS verdict after a rejection must produce their OWN fresh `proof_output`, not cite the worker's. So if the worker fakes, the reviewer either runs their own probe (and catches the fake) or fakes their own re-review (and is now on the hook, and their verdict is typed and auditable). The chain of accountability shifts from prose to typed attestations.

10. **Does this design actually prevent Codex's "fakeable ceremony" concern?** Codex's concern was: "add more fields, agent just fills them in plausibly." The difference here is that the `proof_output` field, when generated by a probe, has a schema. A hand-written fake can still pass the presence check but can't pass a parse-against-probe-schema check at v2. At v1, the fake still works if the reviewer doesn't re-verify; at v2, the parse check makes it significantly harder.

---

## 11. Estimated scope

| Component | LOC estimate |
|---|---|
| New models (`task_verdicts`, `approval_verdict_links`, activity_events column) | ~120 |
| Schemas (`VerdictCreate`, `VerdictRead`, `ApprovalCreate` extension) | ~100 |
| API endpoints (POST /verdicts, GET /verdicts) | ~180 |
| Guard functions (`_ensure_valid_verdict_schema`, `_ensure_verdict_backed_approval_for_move_to_done`) | ~150 |
| Alembic migration | ~100 |
| Probe library (4 probes × ~100 LOC each) | ~400 |
| Template updates (BOARD_AGENTS.md.j2 — reviewer, worker, supervisor sections) | ~80 lines markdown |
| Unit tests (test_task_verdicts.py) | ~300 |
| Integration tests (test_approvals_verdict_binding.py) | ~500 |
| Probe tests (test_probes.py) | ~200 |
| Docstrings, error messages, logging | ~100 |

**Total:** ~2,250 LOC net new + ~80 lines template. Roughly 1.5–2 focused days for an experienced FastAPI/SQLModel developer, plus 0.5 day for probe authoring and dogfooding on the dev-squad board.

---

## 12. What this does NOT fix

- **Reviewer honesty.** A reviewer can still post a PASS verdict with a lie in the `methodology` field and fake `proof_output`. The backend records the claim but cannot validate it. The operator is still the terminal gate for catching this. What changes: lies are now typed and auditable — `SELECT * FROM task_verdicts WHERE verdict='pass' AND methodology='clean_session'` is a one-line audit.
- **First-submission defects.** If a reviewer approves a broken first submission, no rejection ever happens and contracts never activate. This is a reviewer-correctness failure, not a contract failure.
- **Out-of-band bypasses.** If an operator directly PATCHes the `approvals` table or uses a privileged database fixture, they can still approve anything. The operator role is assumed trusted.
- **Probe output correctness at v1.** The worker can still hand-write a plausible-looking JSON blob and paste it into `proof_output`. At v2, schema-parse validation closes this.
- **Heartbeat-time agent bugs.** Hallucinations like the phantom AC #7 still happen. What changes: invalid AC keys in `ac_results` are a structured signal the frontend can flag immediately, cutting debate time.
- **Catching "required_proof_type is wrong" at reject time.** If a reviewer chooses `static_only` as the proof type for a state_change bug, the worker's grep-based proof passes the match check even though it doesn't prove the behavior. Choosing the right proof type is a reviewer skill; the API can't validate it.

---

## 13. Relationship to existing enforcement

| Layer | Commit | Fires on | What it checks |
|---|---|---|---|
| Template prose | `5cbd8ad` | Agent heartbeat | "re-test, not re-cite" guidance (no runtime enforcement) |
| Rejection count | `d6174c4` / `8376f37` | `create_approval` | ≥4 rejections in 24h → 409 unless unblocked |
| **Verdict schema** | **this spec** | **`POST /verdicts`** | **Reject verdicts: require failure_class + required_proof_type + repro_step. Pass verdicts after rejection: require methodology match + non-empty proof_output + supersedes_verdict_id.** |
| **Verdict binding** | **this spec** | **`create_approval`** | **At least one typed verdict row with `created_at > last_rejection.created_at` and `verdict=pass`** |
| Operator override | `d6174c4` | `POST /unblock` | Manual reset by authenticated user/lead |

The five enforcement layers are complementary. Verdict schema catches bad reject classification at the verdict-post time. Verdict binding catches stale re-cites at the approval-create time. The rejection counter catches repeated-bad-verdict patterns over 24h. The unblock endpoint catches all edge cases. Template prose is still guidance but now refers to the typed API contract, not vague "re-test" language.

---

## 14. Appendix: things the prior two specs proposed that we're explicitly dropping

From the earlier "`task-verdict-first-class-design.md`" draft, dropped:
- No failure classification on rejection — now required via sibling spec's `failure_class` + `required_proof_type`
- No proof-type matching on resubmission — now required
- `methodology` as free-text — now constrained to the enum shared with `required_proof_type`
- No probe library — now included as Phase 2 deliverable

From the earlier "`rejection-resolution-contracts-design.md`" draft, dropped:
- Comment-text convention for rejection contracts (parsing REJECTION CONTRACT blocks out of comment prose) — now replaced with typed rows. The contract shape is captured in the `task_verdicts` row columns, not in comment text.
- `RESUBMISSION` block in comments — now replaced with a typed pass verdict
- `RE-REVIEW` block in comments — now replaced with a typed pass verdict with `supersedes_verdict_id` pointing at the original rejection
- `fingerprint_before_rejection` / `fingerprint_after` mechanism — not needed. The FK timestamp check on `task_verdicts.created_at > last_rejection.created_at` is cleaner than a separate fingerprint column.
- LLM classifier for auto-generating rejection contracts — not at v1. Reviewer manually sets failure_class and required_proof_type.

Both prior specs had good bones and bad bones. The good bones (from both) are the merged spec above. The bad bones (comment-text parsing, untyped methodology, no probe library) are gone.

---

## Decision needed

Approve this merged design for implementation, request revisions, or reject. If approved, the next step is a detailed implementation plan via `superpowers:writing-plans` and then execution. If rejected, the escape hatch is to keep both prior specs on disk as historical alternatives and note that no implementation was approved.

**Recommendation from the author:** approve this merged spec for implementation. It's substantially more work than either prior spec alone (~2,250 LOC vs ~1,100 or ~800), but it catches all 4 verified anti-patterns with layered enforcement that doesn't rely on prose parsing, typed rows, or probe output correctness individually — each layer plugs holes in the others. The "cheap workaround" alternative (my earlier "fresh comment after last rejection" gate) was rejected by Codex adversarial review as regex theater. This is the real fix.
