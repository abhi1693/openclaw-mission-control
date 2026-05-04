# BTW Permission Gates — Design

Date: 2026-05-04
Status: Draft, pre-implementation
Audience: MC backend + frontend, gateway template authors

## 1. Summary

Wire MC to consume the gateway's `chat.side_result` ("BTW") event so DevOps
agents can pause before prod-touching irreversible actions and ask the
human operator for approval. Operator sees a global header badge on every
MC page with a count of open questions. Click-through opens a card with
the question + reply form. Reply ships through the gateway's existing
`chat.send` and the DB row is marked resolved.

This is a pilot — single agent role, narrow trigger set, rollout-flag
gated. We learn from real traffic before broadening.

## 2. Why

DevOps has elevated scope (systemctl, daemon control, prod config writes)
and historically operates without a formal gate. The "operator regret"
incidents in our memory bank — gateway restarts that kill heartbeats,
openclaw.json edits that trigger deferred restart — would have been caught
by a "ask before doing" prompt. Today the only fallback is operator
attention, which is uneven.

The gateway already broadcasts BTW envelopes; what's missing is the
operator-facing surface. This design adds it without changing gateway
behavior.

## 3. Scope

### 3.1 In scope

- DevOps agent role only.
- Two trigger categories: process control on prod boxes (`.63`/`.64`),
  prod config writes (`/etc/`, `openclaw.json`, gateway env, MC env).
- One pilot board, opt-in via `boards.rollout_flags.btw_questions_v1`.
- Resolution by human users only.
- Wait-indefinitely with UI age escalation; no automatic timeout.

### 3.2 Out of scope

- All non-DevOps roles. Architect, PB, PF, QA, Lead, Supervisor stay
  un-templated for BTW. Their existing workflows are unaffected.
- Mid-task ambiguity / observed-problem-flag triggers. Permission gates
  only.
- WhatsApp / email / ntfy escalation on operator silence.
- Lead-as-quasi-operator resolution. Established approvals pattern allows
  lead to REJECT but not APPROVE; we deliberately tighten that for BTW
  (humans only, both sides).
- Workspace-local destructive ops. `rm` in `/tmp/`, file rewrites in the
  agent's workspace, git ops on the agent's branch — not gated.

## 4. Architecture

Three components, each owned end-to-end.

```
┌─────────────────┐     chat.side_result    ┌──────────────────┐
│ DevOps agent    │ ──────────────────────▶ │ OpenClaw gateway │
│ (emits btw      │                         │ (broadcasts)     │
│  envelope)      │                         └────────┬─────────┘
└─────────────────┘                                  │
                                                     ▼
                                          ┌──────────────────────┐
                                          │ mc-gateway-subscriber│
                                          │ (.64 systemd unit)   │
                                          │ + new projector       │
                                          └────────┬─────────────┘
                                                   │ INSERT
                                                   ▼
                                          ┌──────────────────────┐
                                          │ Postgres (.66)       │
                                          │ board_pending_       │
                                          │ questions table      │
                                          └────────┬─────────────┘
                                                   │
                                                   ▼
┌─────────────────┐  GET /pending-questions ┌──────────────────────┐
│ Operator (web)  │ ◀──────────────────────│ MC backend (FastAPI) │
│ + header badge  │                         │ + new endpoints      │
│ + reply card    │ ──── POST /resolve ────▶│                      │
└─────────────────┘                         └────────┬─────────────┘
                                                     │ chat.send
                                                     ▼
                                            (gateway routes by runId
                                             into agent's next turn)
```

### 4.1 Gateway behavior (verified, no change)

`chat.side_result` is broadcast unfiltered via `context.broadcast(...)`
on `chat.ts:1525` — every connected gateway client receives it without
needing a per-client subscription RPC. Single emit site at `chat.ts:2146`
fires only when an agent reply contains a `btw: {question}` envelope.
Immediately after the broadcast, the gateway calls `broadcastChatFinal`
which terminates the agent's run. So BTW is **end-of-turn**: agent
emits, run ends, agent waits for next user message.

Payload schema (from `chat.ts:199`):

```typescript
type SideResultPayload = {
  kind: "btw";
  runId: string;
  sessionKey: string;
  question: string;
  text: string;
  isError?: boolean;
  ts: number;
};
```

The gateway adds `seq` on broadcast.

### 4.2 System prompt caching (verified)

`agents/bootstrap-cache.ts` keeps `Map<sessionKey, WorkspaceBootstrapFile[]>`
in-memory per session. Once a session loads SOUL.md / AGENTS.md /
HEARTBEAT.md, the contents are cached until session delete or explicit
invalidation. MC's "Sync Templates" endpoint (default `reset_sessions=false`)
writes new files to disk but does not invalidate the in-memory cache.
**Implication:** template rollback is eventually consistent. Active
sessions keep the cached prompt; new and reset sessions read fresh.

## 5. Data model

### 5.1 New table

```python
class BoardPendingQuestion(SQLModel, table=True):
    __tablename__ = "board_pending_questions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    agent_id: str = Field(index=True)
    run_id: str
    session_key: str
    question: str
    text: str
    status: str = Field(default="open", index=True)  # open | resolved
    created_at: datetime = Field(default_factory=utcnow, index=True)

    # Resolution fields, set on operator reply
    resolved_at: datetime | None = None
    resolved_by_user_id: UUID | None = Field(default=None, foreign_key="users.id")

    # Idempotency for resolve send-then-update flow (Section 7)
    sent_idempotency_key: UUID | None = None
    last_send_attempt_at: datetime | None = None
```

### 5.2 Indexes

- `(board_id, status, created_at desc)` — per-board open-questions list.
- `(status, created_at desc)` — cross-board count for header badge.
- `UNIQUE(run_id)` with `ON CONFLICT DO NOTHING` semantics in the
  projector. Subscriber reconnects routinely and the gateway may replay;
  crashing on replay is self-inflicted fragility, so the projector
  swallows duplicates and increments a counter
  (`btw_projection_duplicate_total`).

### 5.3 Migration

Single Alembic revision adds the table + indexes. No data backfill.
Reverse migration drops the table; resolved rows are useful audit
history but not load-bearing for any other system.

## 6. Subscriber wiring

### 6.1 New projector module

`backend/app/services/mc_gateway_subscriber/chat_side_result_projector.py`,
mirroring `session_state_projector.py`:

- Pure `build_pending_question_from_frame(frame)` returning a row or
  `None`. Drops events with malformed payload, missing `runId`,
  off-namespace `sessionKey`, or non-3-segment session keys (sub-session
  BTWs are out of scope for the pilot).
- Async projector class doing DB writes via the existing
  `mc-gateway-subscriber` session.
- Pilot-scope guard: drop events whose source agent isn't on a board
  with `rollout_flags.btw_questions_v1` enabled. Drops are logged
  structured (`btw_drop_reason=flag_disabled|board_not_found|agent_not_found
  |malformed_payload|sub_session_key`) and counted, never silent.

### 6.2 Wiring in `__main__.py`

```python
EVENT_CHAT_SIDE_RESULT = "chat.side_result"  # add to protocol_constants

subscriber.on(EVENT_CHAT_SIDE_RESULT, chat_side_result_projector)
```

No new gateway RPC call. The existing connection receives `chat.side_result`
events automatically because the gateway broadcasts unfiltered. The
existing `sessions.subscribe` RPC stays for `sessions.changed` filtering.

## 7. API

### 7.1 Endpoints

All under `app/api/board_pending_questions.py` plus one cross-board
endpoint at the top level.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/boards/{board_id}/pending-questions` | `BOARD_READ_DEP` | List for one board |
| GET | `/pending-questions` | `AUTH_DEP` | Cross-board list, filtered by `boards_visible_to_user(user)` |
| GET | `/pending-questions/count` | `AUTH_DEP` | Cross-board count + `oldest_open_at` for header badge |
| POST | `/boards/{board_id}/pending-questions/{id}/resolve` | **`get_board_for_user_write`** (human-only) | Send reply + mark resolved |

The resolve endpoint deliberately uses `get_board_for_user_write`, not
the more permissive `get_board_for_actor_write`. Agents (including lead)
cannot resolve BTWs. This tightens against the established approvals
pattern (`approvals.py:764`, where lead can reject); the choice is
deliberate — permission-gate semantics require a human signoff or the
gate is meaningless.

### 7.2 Resolve flow (corrected from "atomic")

WebSocket-RPC and Postgres cannot be atomic. Use a stable idempotency
key derived from the row to make retries safe:

```
1. SELECT FOR UPDATE row by id + board_id
2. Reject if status != "open" → 409
3. If sent_idempotency_key is None: assign uuid4(), persist + commit
   (now we have a stable key tied to this row)
4. UPDATE last_send_attempt_at = NOW()
5. await send_message(reply, session_key=row.session_key, config=config,
                      idempotency_key=row.sent_idempotency_key)
   — gateway dedupes if the row's key was already used
6a. Send succeeds → UPDATE status="resolved", resolved_at, resolved_by_user_id
                  → return 204
6b. Send fails (502/timeout) → leave row open with sent_idempotency_key set
                              → return 502 with retry hint
6c. Send succeeds, DB update fails → row stays open with key set; operator
                                     retries; gateway dedupes; row eventually
                                     resolves on next attempt
```

The `send_message` helper currently generates a fresh idempotency key on
every call (`gateway_rpc.py:703`). Resolve must override this with the
row's `sent_idempotency_key` so retries are safe. Add an
`idempotency_key: UUID | None = None` kwarg to `send_message` to thread
this through.

### 7.3 Frontend retry UX

On 502 the card shows a "Send failed — retry" button. Clicking re-POSTs
to the same `/resolve` URL. Backend re-derives the row's stable key
(already persisted), gateway dedupes if the prior attempt actually
delivered, otherwise retries cleanly.

## 8. Agent template

### 8.1 Where it lands

New section in `backend/templates/devops/SOUL.md.j2`, between the
existing "Privilege & Scope" and "Workflow" sections. Section title:
`## Permission Gates (BTW)`.

### 8.2 Content

```markdown
## Permission Gates (BTW)

Before running ANY of the following on prod (.63 / .64), end your turn
with a `btw` envelope and wait for operator reply:

- **Process control:** `systemctl restart`, `systemctl stop`, `kill -9`,
  daemon stop/start of running services.
- **Prod config writes:** edits to `/etc/`, `openclaw.json`, gateway env
  files, MC env files.

Workspace-local destructive ops (rm in `/tmp/`, file rewrites in your
own workspace, git ops on your branch) are NOT BTW-gated. Read-only
diagnostic commands (`systemctl status`, `journalctl`, `cat`) are NOT
BTW-gated.

### Format

End your reply with the literal envelope:

\`\`\`
btw: { "question": "Restart mc-backend on .64? Kills heartbeat ~8s, agents may need re-auth.", "text": "Background: ... | Alternative: ... | Blast radius: ..." }
\`\`\`

Keep `question` to one sentence (it's what the operator sees first).
Put detail in `text`. End the turn after the envelope; do NOT run the
gated command before operator reply arrives.
```

### 8.3 Sync layers

Per `feedback_template_update_checklist`: change ripples to (1)
`templates/devops/SOUL.md.j2`, (2) DevOps `identity_template` DB cache,
(3) DevOps `soul_template` DB cache. After scp + Sync Templates API call.

## 9. Frontend

### 9.1 Components

`frontend/src/components/molecules/PendingQuestionsBadge.tsx`:
- Bell icon + count pill in the global header.
- Polls `/api/v1/pending-questions/count` on a 15s `setInterval`.
- Color escalation by `oldest_open_at` age: green <30m, yellow 30m–2h,
  red >2h.
- Wraps `<Link href="/pending-questions">`.

`app/pending-questions/page.tsx`:
- Server component. Calls `GET /api/v1/pending-questions` (cross-board).
- Renders list of question cards, sorted oldest-first.

`frontend/src/components/organisms/PendingQuestionCard.tsx`:
- Header row: agent name, board name, "open for 1h 23m".
- `question` body prominent.
- `text` body collapsed under "show context" toggle.
- Reply form: textarea + "Send & Resolve" button → `POST /resolve`.
- 204 → optimistically remove from list.
- 502 → toast error + "Send failed — retry" button on the card.

### 9.2 Tests

- Vitest: badge count rendering, color thresholds, click-through.
- Vitest: card form submit, optimistic remove, 502 retry button.

## 10. Auth scope

| Action | Required | Why |
|---|---|---|
| List pending questions on a board | `board_read` (user OR agent) | Lead may want visibility |
| List pending questions cross-board | logged-in user | Header badge needs count for any operator |
| Resolve | human user with `board_write` | Permission-gate semantics — gate is meaningless if any agent can sign off |

## 11. Rollout flag

Add `btw_questions_v1` to the existing `boards.rollout_flags` enum at
`app/schemas/boards.py`. Default: not enabled. Enable on the pilot
staging board only. Projector reads this flag during the pilot-scope
guard; disabled boards drop events with structured log
(`btw_drop_reason=flag_disabled`).

When the pilot graduates: flip the flag default to enabled and remove
the guard, OR leave the flag in place as a per-board kill switch.

## 12. Rollback

Two layers, two consumers:

| Layer | Action | Effect | Latency |
|---|---|---|---|
| MC subscriber kill switch | Comment out `subscriber.on(EVENT_CHAT_SIDE_RESULT, ...)`, `systemctl restart mc-gateway-subscriber` | No new DB rows, no badge increments. Operator-facing surface goes silent. | < 30s |
| Template rollback | Remove "Permission Gates (BTW)" section from `SOUL.md.j2`, scp + Sync Templates API | New sessions stop emitting BTWs. Active sessions keep emitting until reset (cached system prompt). | Eventually consistent (minutes to hours, until session resets) |

For an emergency stop, do the subscriber kill switch first, then the
template rollback to clean up. The kill switch alone leaves agents
emitting BTW envelopes that go nowhere — the agent's gated work stalls
until session reset, so the template removal is necessary for full
agent recovery.

The DB table can persist (resolved rows are audit history) or be dropped
via reverse migration if you want a clean wipe.

## 13. Telemetry & success metrics

### 13.1 Logged events (structured, JSON)

- `btw_question_projected` — board_id, agent_id, run_id, created_at.
- `btw_drop` — drop_reason, board_id (if known), agent_id (if known).
- `btw_question_resolved` — id, resolver_user_id, time_to_resolve_seconds.
- `btw_send_failed` — id, gateway_error, attempt_number.
- `btw_projection_duplicate_total` — counter; on every ON CONFLICT hit.

### 13.2 Pilot success criteria (14-day window)

| Metric | Target | Failure means |
|---|---|---|
| BTW volume | ≥3 emitted | 0 → trigger criteria isn't matching real DevOps work; revise template |
| Operator response time | median < 60m | Higher → notification surface isn't catching attention; consider per-board widget or escalation channel |
| Missed gates | 0 prod-touching irreversibles ran without preceding BTW (audited via DevOps trajectory log) | >0 → agent forgets; promote template→skill (Q7-B) |
| False-positive gates | ≤2 operator-reported "didn't need a BTW" | >2 → triggers too broad; tighten |
| Send failures | <5% of resolves | Higher → idempotency-key flow needs hardening or the gateway path is unhealthy |

### 13.3 Decision after 14 days

- All metrics hit → expand to all DevOps agents across all boards (flag
  default enabled).
- Volume + response time hit, missed gates fail → add `devops-permission-gate`
  skill before broadening.
- False-positive fail → tighten triggers, restart pilot.
- Volume zero → revisit trigger criteria with real DevOps log audit.

## 14. Testing strategy

### 14.1 Unit

`tests/test_chat_side_result_projector.py`:
- Pure parser: valid frame → row; missing runId/sessionKey/payload → drop;
  off-namespace key → drop; sub-session key → drop; ON CONFLICT path
  increments duplicate counter without crashing.
- Async projector: insert one row; idempotency with replay frame returns
  no error; pilot-scope guard drops non-flag boards with structured log.

`tests/test_board_pending_questions_service.py`:
- Resolve happy path → 204, row marked resolved.
- Send fails → row stays open, `sent_idempotency_key` persisted,
  `last_send_attempt_at` updated.
- Retry after send-failure → reuses persisted idempotency_key.
- Already-resolved → 409 without side effects.
- Send succeeds, DB update fails → row stays open with key set; next
  retry succeeds.

`tests/test_board_pending_questions_api.py`:
- Auth: agent token on resolve → 403; user without `board_write` → 403;
  user with `board_read` on list endpoints → 200.
- Cross-board list/count respects `boards_visible_to_user`.

### 14.2 Integration

`tests/test_pending_questions_integration.py`:
- Build `chat.side_result` frame, push through `Subscriber.dispatch`,
  assert row inserted.
- Call `/resolve` via `httpx_async_client` with a mocked `send_message`,
  assert 204 + row resolved + reply attempted with stable key.
- Replay same frame, assert no second row, assert duplicate counter
  incremented.

### 14.3 Manual smoke

Pre-pilot test on staging:
1. Deploy to .64.
2. Enable `btw_questions_v1` on staging board.
3. Coach DevOps to emit a BTW for a low-stakes "should I run systemctl
   status" envelope (intentionally false-positive to test the surface).
4. Verify: badge increments, click-through lands on the question card,
   reply round-trips, agent receives reply on next turn.
5. Check `mc-gateway-subscriber` journal — zero unexpected drops or
   errors.

## 15. Open questions for implementation

- Stable idempotency-key UUID type vs string in `send_message` —
  the existing helper takes whatever the gateway accepts; verify the
  gateway accepts caller-provided keys (current code generates them).
  If gateway rejects, we need a different dedup strategy.
- Header badge placement in the existing layout — does the current
  `app/layout.tsx` have a header slot, or do we need to add one?
  Frontend recon before coding.
- Whether to namespace the rollout flag (`btw.permission_gates.v1`)
  for room to add other BTW pilots (mid-task ambiguity, observed-problem
  flags) without flag collision. Probably yes; cheap insurance.

## 16. References

### Gateway 5.3 source (`.60`)

- `gateway/server-methods/chat.ts:199` — `SideResultPayload` type
- `gateway/server-methods/chat.ts:1520-1529` — `broadcastSideResult`
- `gateway/server-methods/chat.ts:2146-2160` — emit site + immediate
  `broadcastChatFinal`
- `agents/bootstrap-cache.ts` — system prompt cache map (verifies
  template rollback latency)

### MC source

- `app/services/openclaw/gateway_rpc.py:703` — `send_message` helper
  (needs `idempotency_key` kwarg added)
- `app/services/mc_gateway_subscriber/__main__.py:115` — projector
  registration site
- `app/services/mc_gateway_subscriber/session_state_projector.py` —
  pattern to mirror
- `app/api/approvals.py:764` — established lead-can-reject-not-approve
  pattern (BTW deliberately tightens this to humans-only)
- `app/api/deps.py:160` — `get_board_for_actor_write` (do NOT use here);
  we use the human-only sibling
- `app/schemas/boards.py:17,78` — rollout-flag pattern to extend
- `app/services/openclaw/provisioning.py:1227` — Sync Templates writes
  to workspace files (does not invalidate gateway's in-memory cache)
