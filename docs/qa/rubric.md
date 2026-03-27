# QA Grading Rubric

Read this ENTIRE file before starting any validation. Score every dimension. Post scores in your validation comment.

## Evidence Rules

**QA-E2E (browser validation):**
- You MUST use Chrome MCP for ALL UI/frontend tasks.
- Evidence must quote the **literal tool result** — not a summary, not "I checked and saw no errors." Paste the actual output.
- The BUILD hash MUST be captured from the browser network log (`mcp__chrome-devtools__list_network_requests`), not from memory or a prior validation.
- Bundle/code grep is NEVER valid evidence for UI dimensions.
- Re-validate EVERY time with a FRESH Chrome MCP session. Previous PASS/FAIL is irrelevant.
- If the URL is unreachable, report FAIL — that IS the bug.
- If the build hash changes during your validation (different from the one in the review comment), STOP and report "BUILD CHANGED — validation invalid. Waiting for stable build." Do NOT re-validate on the new build — the developer must freeze and re-request QA.
- If your validation does not include at least one `mcp__chrome-devtools__navigate_page` call, you have not started.

**QA-Unit (mechanical checks):**
- Run typecheck, lint, and tests in the actual workspace.
- Post exact command output as evidence.

## Review Loop

1. Supervisor routes task to QA after Architect review (or directly for bugfixes/<3 files).
2. QA scores each dimension (0-10) using Chrome MCP evidence.
3. If ANY hard fail → REJECT with specific dimension and evidence.
4. If all pass → POST with scores and evidence.
5. On rejection: Supervisor routes back to developer → developer fixes → asks @lead to re-route.
6. **Maximum 3 reject/fix/retest rounds.** After round 3, Supervisor escalates to @Miguel with rejection history.

## Frontend Task Scoring

| Dimension | Weight | Fail | How to Check |
|-----------|--------|------|--------------|
| Spec Fidelity | 15% | <6 | Compare rendered DOM against task description acceptance criteria |
| Interaction | 15% | <7 | `mcp__chrome-devtools__click` on interactive elements, verify state changes |
| Visual Quality | 15% | <7 | `mcp__chrome-devtools__take_screenshot` — check typography, color, spacing |
| Originality | 20% | <6 | Take screenshot, describe 2+ specific non-generic design decisions. Score ≤5 if none found |
| Craft | 15% | <6 | Code cleanliness — no hacks, no TODO/FIXME in production. Check via evaluate_script if needed |
| Console/Network | 10% | >0 errors | `mcp__chrome-devtools__list_console_messages({"types": ["error"]})` — must return ZERO |
| Code Quality | 5% | typecheck fail | `npm run typecheck` and `npm run lint` — must exit 0 |
| Responsiveness | 5% | <5 | `mcp__chrome-devtools__resize_page({"width": 375, "height": 812})` — check layout |

### Scoring Guide
- **10/10:** Exceeds spec. Polished, delightful.
- **8-9:** Meets spec fully. Minor polish opportunities.
- **6-7:** Meets spec with gaps. Functional but rough.
- **4-5:** Partially meets spec. Missing features or broken states.
- **1-3:** Major issues. Broken or spec mismatch.
- **0:** Not implemented or completely wrong.

## Backend Task Scoring

| Dimension | Weight | Fail | How to Check |
|-----------|--------|------|--------------|
| API Contract | 30% | missing endpoint | `curl` each endpoint from spec, verify status codes + response shape |
| Data Accuracy | 25% | wrong data | Compare API response vs expected |
| Error Handling | 15% | crash on bad input | Send invalid params, verify 4xx not 5xx |
| Performance | 10% | >5s response | `time curl` on each endpoint |
| Test Coverage | 20% | <80% pass | `pytest --tb=short` output |

## Hard Fail Rules (ANY = automatic REJECT)

- Console errors > 0 (the `types: ["error"]` filter already excludes warnings)
- Typecheck fails
- Build fails
- Service returns 5xx on valid requests
- URL unreachable (CORS, network, server down)
- Validation comment contains no `mcp__chrome-devtools__` tool call references for UI tasks

## Validation Comment Format

Post as a task comment with this format:

```
QA-E2E validation

BUILD: [hash from mcp__chrome-devtools__list_network_requests — the index-XXXX.js filename]
URL: http://192.168.2.63:3000/boards/BOARD_ID

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Spec Fidelity | 15% | X/10 | [what was checked vs spec] |
| Visual Quality | 15% | X/10 | [screenshot reference] |
| Interaction | 15% | X/10 | [what was clicked/tested] |
| Originality | 20% | X/10 | [2+ design decisions or "none found"] |
| Craft | 15% | X/10 | [code observations] |
| Console/Network | 10% | X/10 | [literal tool output — error count] |
| Code Quality | 5% | X/10 | [typecheck/lint exit code] |
| Responsiveness | 5% | X/10 | [mobile viewport result] |

**Weighted total:** (Spec×0.15)+(Visual×0.15)+(Interaction×0.15)+(Originality×0.20)+(Craft×0.15)+(Console×0.10)+(CodeQuality×0.05)+(Responsive×0.05) = XX/10
**Verdict: PASS/FAIL**
**Fail reason:** [dimension that triggered fail, if any]

@lead
```

## Be SKEPTICAL

LLMs tend toward leniency — fight that instinct. A prior QA-E2E pass was based on bundle inspection with no Chrome MCP session. That is the exact pattern this rubric prevents.

Rules:
- If evidence is ambiguous, score LOWER.
- If you can't verify a dimension via Chrome MCP, score 0 and explain why.
- Never PASS based on "it probably works" — only on verified tool output.
- Paraphrasing tool output ("I saw no errors") is NOT evidence. Quote the literal result.
- If your session has zero `mcp__chrome-devtools__` calls, you have not validated anything.
