# Agent Activity Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a right-side dashboard panel that shows live board-agent activity from the gateway without breaking auth, board scoping, or multi-board dashboard behavior.

**Architecture:** Mission Control keeps a long-lived gateway WebSocket per gateway and manages `sessions.subscribe` / `sessions.unsubscribe` over that persistent connection. The backend exposes a board-scoped SSE endpoint guarded by existing board-read dependencies. The frontend consumes that SSE stream via authenticated `fetch` streaming, not native `EventSource`, so local-auth and Clerk bearer-token flows continue to work.

**Tech Stack:** Python/FastAPI + `sse-starlette` + `websockets` (backend), React/Next.js + fetch streaming + `TextDecoder` (frontend), generated API client via `make api-gen`.

**Codebase notes:**
- The dashboard page is org-wide, not board-scoped. Do **not** silently bind the panel to `boards[0]`; expose an explicit board selector in the panel UI.
- Existing board-scoped stream routes use `/boards/{board_id}/...` plus `get_board_for_actor_read` / `require_user_or_agent` access checks. Follow that pattern.
- Local auth is header-based (`Authorization: Bearer ...`) in `frontend/src/api/mutator.ts` and `backend/app/core/auth.py`. Native `EventSource` cannot send that header, so it is not acceptable here.
- `backend/app/services/openclaw/gateway_rpc.py` currently uses one-shot `openclaw_call(...)` connections. Real-time activity requires a persistent WebSocket reader loop, not a fire-and-forget subscribe RPC.
- `backend/app/main.py` already owns app lifespan. Wire activity-service startup/shutdown there so background gateway tasks are cleaned up correctly.
- Keep MVP scoped to agent identity, model, tool calls, tool output, and timestamps. Do **not** invent `task_id` / `task_title` fields unless a reliable source exists in committed code.

---

### Task 1: Backend model + event classification

**Files:**
- Create: `backend/app/services/openclaw/activity_stream.py`
- Test: `backend/tests/test_activity_stream.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_activity_stream.py
from __future__ import annotations

from app.services.openclaw.activity_stream import AgentEvent


def test_classify_assistant_text_event() -> None:
    raw = {
        "type": "event",
        "event": "session.message",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Checking logs now"}],
            },
            "model": "gpt-5.4",
            "usage": {"input": 10, "output": 5, "cost": {"total": 0.02}},
        },
    }

    event = AgentEvent.from_gateway_event(raw, agent_name="Planner")

    assert event is not None
    assert event.type == "thinking"
    assert event.agent_id == "mc-123"
    assert event.agent_name == "Planner"
    assert event.content == "Checking logs now"
    assert event.model == "gpt-5.4"
    assert event.session_tokens == 15
    assert event.session_cost == 0.02


def test_classify_tool_call_event() -> None:
    raw = {
        "type": "event",
        "event": "session.message",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "name": "exec_command",
                        "arguments": {"cmd": "curl -s http://localhost:8000/health"},
                    }
                ],
            },
        },
    }

    event = AgentEvent.from_gateway_event(raw, agent_name="Planner")

    assert event is not None
    assert event.type == "tool_call"
    assert event.tool_name == "exec_command"
    assert "curl" in (event.tool_args or "")


def test_classify_tool_result_event() -> None:
    raw = {
        "type": "event",
        "event": "session.tool",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "toolName": "exec_command",
            "content": [{"type": "text", "text": '{"ok": true}'}],
            "exitCode": 0,
            "durationMs": 120,
        },
    }

    event = AgentEvent.from_gateway_event(raw, agent_name="Planner")

    assert event is not None
    assert event.type == "tool_result"
    assert event.output == '{"ok": true}'
    assert event.exit_code == 0
    assert event.duration_ms == 120


def test_ignore_non_assistant_message() -> None:
    raw = {
        "type": "event",
        "event": "session.message",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        },
    }

    assert AgentEvent.from_gateway_event(raw, agent_name="Planner") is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_activity_stream.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing `AgentEvent`

**Step 3: Write minimal implementation**

Create `backend/app/services/openclaw/activity_stream.py` with:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_CONTENT_CHARS = 500
MAX_ARGS_CHARS = 200
MAX_OUTPUT_CHARS = 300


@dataclass(slots=True)
class AgentEvent:
    type: str
    agent_id: str
    agent_name: str
    timestamp: str
    model: str | None = None
    content: str | None = None
    tool_name: str | None = None
    tool_args: str | None = None
    exit_code: int | None = None
    output: str | None = None
    duration_ms: int | None = None
    session_tokens: int | None = None
    session_cost: float | None = None

    @classmethod
    def from_gateway_event(
        cls,
        raw: dict[str, Any],
        *,
        agent_name: str,
    ) -> AgentEvent | None:
        ...

    def to_dict(self) -> dict[str, Any]:
        ...
```

Implementation requirements:
- Parse `agent_id` from `sessionKey` values like `agent:mc-<uuid>:main`.
- Only classify assistant `session.message` events.
- Support `text` -> `thinking`, `toolCall` -> `tool_call`, and `session.tool` -> `tool_result`.
- Truncate text, args, and output using the constants above.
- Serialize only non-empty optional fields from `to_dict()`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_activity_stream.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/services/openclaw/activity_stream.py backend/tests/test_activity_stream.py
git commit -m "feat(activity): add agent event classifier"
```

---

### Task 2: Backend gateway connection manager

**Files:**
- Modify: `backend/app/services/openclaw/activity_stream.py`
- Test: `backend/tests/test_activity_stream_connection.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_activity_stream_connection.py
from __future__ import annotations

import asyncio

import pytest

from app.services.openclaw.activity_stream import GatewayActivityConnection


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.recv_queue: asyncio.Queue[dict] = asyncio.Queue()
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def recv_json(self) -> dict:
        return await self.recv_queue.get()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_connection_sends_subscribe_for_new_session_keys() -> None:
    socket = FakeSocket()
    conn = GatewayActivityConnection(
        gateway_id="gw-1",
        connect=lambda: socket,
        publish=lambda board_id, event: None,
    )

    await conn.update_subscriptions({"agent:mc-1:main", "agent:mc-2:main"})

    assert socket.sent[0]["method"] == "sessions.subscribe"
    assert socket.sent[0]["params"]["sessionKey"] == "agent:mc-1:main"
    assert socket.sent[1]["params"]["sessionKey"] == "agent:mc-2:main"


@pytest.mark.asyncio
async def test_connection_sends_unsubscribe_for_removed_session_keys() -> None:
    socket = FakeSocket()
    conn = GatewayActivityConnection(
        gateway_id="gw-1",
        connect=lambda: socket,
        publish=lambda board_id, event: None,
    )

    await conn.update_subscriptions({"agent:mc-1:main", "agent:mc-2:main"})
    socket.sent.clear()

    await conn.update_subscriptions({"agent:mc-2:main"})

    assert socket.sent == [
        {"method": "sessions.unsubscribe", "params": {"sessionKey": "agent:mc-1:main"}}
    ]
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_activity_stream_connection.py -v`
Expected: FAIL with missing `GatewayActivityConnection`

**Step 3: Implement persistent connection management**

Extend `backend/app/services/openclaw/activity_stream.py` with:

```python
class GatewayActivityConnection:
    def __init__(self, gateway_id: str, *, connect, publish) -> None:
        self.gateway_id = gateway_id
        self._connect = connect
        self._publish = publish
        self._socket = None
        self._desired_session_keys: set[str] = set()
        self._subscribed_session_keys: set[str] = set()
        self._reader_task: asyncio.Task[None] | None = None

    async def ensure_started(self) -> None:
        ...

    async def update_subscriptions(self, session_keys: set[str]) -> None:
        ...

    async def aclose(self) -> None:
        ...
```

Implementation requirements:
- Keep one live socket per gateway.
- Send `sessions.subscribe` only for newly-added session keys.
- Send `sessions.unsubscribe` only for removed session keys.
- Start a background reader loop once per connection.
- Reader loop must reconnect with bounded exponential backoff and re-subscribe after reconnect.
- Connection code must not rely on one-shot `openclaw_call(...)`.

Pragmatic note:
- If `gateway_rpc.py` needs a small public helper for authenticated persistent connects, add it there.
- Do **not** add dead wrapper functions that just call `openclaw_call("sessions.subscribe", ...)`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_activity_stream_connection.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add backend/app/services/openclaw/activity_stream.py backend/tests/test_activity_stream_connection.py
git commit -m "feat(activity): add persistent gateway activity connection"
```

---

### Task 3: Backend broker + board metadata

**Files:**
- Modify: `backend/app/services/openclaw/activity_stream.py`
- Test: `backend/tests/test_activity_stream_broker.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_activity_stream_broker.py
from __future__ import annotations

import asyncio

import pytest

from app.services.openclaw.activity_stream import AgentActivityBroker, AgentEvent


@pytest.mark.asyncio
async def test_broker_fans_out_only_to_matching_board() -> None:
    broker = AgentActivityBroker()
    q1 = broker.subscribe("board-1")
    q2 = broker.subscribe("board-2")

    event = AgentEvent(
        type="thinking",
        agent_id="mc-1",
        agent_name="Planner",
        timestamp="2026-04-08T00:00:00+00:00",
        content="hello",
    )

    await broker.publish("board-1", event)

    assert (await q1.get()).content == "hello"
    assert q2.empty()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_activity_stream_broker.py -v`
Expected: FAIL with missing `AgentActivityBroker`

**Step 3: Implement broker and board registration**

In `backend/app/services/openclaw/activity_stream.py`, add:

```python
class AgentActivityBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[AgentEvent]]] = {}
        self._gateway_connections: dict[str, GatewayActivityConnection] = {}
        self._board_ref_counts: dict[str, int] = {}

    def subscribe(self, board_id: str) -> asyncio.Queue[AgentEvent]:
        ...

    def unsubscribe(self, board_id: str, queue: asyncio.Queue[AgentEvent]) -> None:
        ...

    async def publish(self, board_id: str, event: AgentEvent) -> None:
        ...
```

Add one more service class in the same file:

```python
class AgentActivityService:
    async def attach_board(self, *, board, session) -> None:
        ...

    async def detach_board(self, *, board_id: str) -> None:
        ...

    async def shutdown(self) -> None:
        ...
```

Implementation requirements:
- Resolve board agents from the DB using `Agent.board_id == board.id` and non-empty `Agent.openclaw_session_id`.
- Map each session key to `(board_id, agent_name)` so incoming gateway events can be enriched before publish.
- Create one `GatewayActivityConnection` per gateway, not per browser tab.
- Track board ref-counts so disconnecting one browser tab does not tear down another tab’s subscription.
- Drop per-agent `task_id` / `task_title` enrichment from MVP.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_activity_stream_broker.py -v`
Expected: 1 passed

**Step 5: Commit**

```bash
git add backend/app/services/openclaw/activity_stream.py backend/tests/test_activity_stream_broker.py
git commit -m "feat(activity): add board-scoped activity broker"
```

---

### Task 4: Backend API route with real auth and lifecycle wiring

**Files:**
- Create: `backend/app/api/agent_activity.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_agent_activity_api.py`

**Step 1: Write the failing API tests**

```python
# backend/tests/test_agent_activity_api.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.main import app


@pytest.mark.asyncio
async def test_stream_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/boards/00000000-0000-0000-0000-000000000000/agent-activity/stream")
    assert response.status_code == 401
```

Add a second test that uses a real local-auth header plus a patched activity service so the response returns an initial `connected` event with HTTP 200.

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_agent_activity_api.py -v`
Expected: FAIL because route does not exist

**Step 3: Implement the board-scoped stream route**

Create `backend/app/api/agent_activity.py`:

```python
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ActorContext, get_board_for_actor_read, require_user_or_agent
from app.models.boards import Board
from app.services.openclaw.activity_stream import activity_service

router = APIRouter(prefix="/boards/{board_id}/agent-activity", tags=["agent-activity"])


@router.get("/stream")
async def stream_agent_activity(
    request: Request,
    board: Board = Depends(get_board_for_actor_read),
    _actor: ActorContext = Depends(require_user_or_agent),
) -> EventSourceResponse:
    ...
```

Implementation requirements:
- Scope the route to `/api/v1/boards/{board_id}/agent-activity/stream`.
- Use existing board-read dependencies.
- On connect: `await activity_service.attach_board(board=board, session=...)`.
- Subscribe the SSE client queue after the board is attached.
- Emit an initial `connected` event, then `agent_event` events, and a keepalive heartbeat when idle.
- On disconnect: unsubscribe the client queue and decrement board ref-counts.

Update `backend/app/main.py`:
- Import and register the new router.
- In `lifespan(...)`, call `await activity_service.shutdown()` in the `finally:` block.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_agent_activity_api.py -v`
Expected: passing auth coverage for unauthorized and authorized cases

**Step 5: Commit**

```bash
git add backend/app/api/agent_activity.py backend/app/main.py backend/tests/test_agent_activity_api.py
git commit -m "feat(api): add authorized board activity stream"
```

---

### Task 5: Regenerate frontend API client

**Files:**
- Modify: `frontend/src/api/generated/**` (via generator only)

**Step 1: Regenerate the client**

Run:

```bash
make api-gen
```

Expected:
- New generated endpoint for `/api/v1/boards/{board_id}/agent-activity/stream`
- No manual edits inside `frontend/src/api/generated/`

**Step 2: Verify generated artifacts changed**

Run: `git status --short frontend/src/api/generated`
Expected: generated files updated for the new route

**Step 3: Commit**

```bash
git add frontend/src/api/generated
git commit -m "chore(api): regenerate client for agent activity stream"
```

---

### Task 6: Frontend authenticated stream transport

**Files:**
- Create: `frontend/src/lib/sse.ts`
- Create: `frontend/src/hooks/useAgentActivityStream.ts`
- Test: `frontend/src/hooks/useAgentActivityStream.test.ts`

**Step 1: Write the failing frontend tests**

Add a hook test that:
- Mocks the generated stream API call or `customFetch`
- Returns a `ReadableStream` with two SSE frames:
  - `event: connected`
  - `event: agent_event`
- Verifies the hook reports `connected: true` and stores one event

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- useAgentActivityStream`
Expected: FAIL with missing hook/parser

**Step 3: Implement authenticated fetch-based SSE parsing**

Create `frontend/src/lib/sse.ts`:

```ts
export type SseMessage = {
  event: string;
  data: string;
};

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseMessage> {
  ...
}
```

Create `frontend/src/hooks/useAgentActivityStream.ts`:

```ts
import { useEffect, useRef, useState } from "react";

export type AgentEvent = {
  type: "thinking" | "tool_call" | "tool_result";
  agent_id: string;
  agent_name: string;
  timestamp: string;
  model?: string;
  content?: string;
  tool_name?: string;
  tool_args?: string;
  exit_code?: number;
  output?: string;
  duration_ms?: number;
  session_tokens?: number;
  session_cost?: number;
};

export function useAgentActivityStream(boardId: string | null) {
  ...
}
```

Implementation requirements:
- Use authenticated `fetch` / generated raw client, not `new EventSource(...)`.
- Pass an `AbortController.signal` so cleanup closes the stream immediately.
- Reconnect with bounded exponential backoff.
- Reset connection state on board change.
- Buffer at most 200 events per agent.
- Keep only fields that the backend actually emits.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- useAgentActivityStream`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/lib/sse.ts frontend/src/hooks/useAgentActivityStream.ts frontend/src/hooks/useAgentActivityStream.test.ts
git commit -m "feat(frontend): add authenticated agent activity stream hook"
```

---

### Task 7: Frontend panel components

**Files:**
- Create: `frontend/src/components/agents/StreamEvent.tsx`
- Create: `frontend/src/components/agents/AgentStream.tsx`
- Create: `frontend/src/components/agents/AgentActivityPanel.tsx`
- Test: `frontend/src/components/agents/AgentActivityPanel.test.tsx`

**Step 1: Write the failing component test**

Add a render test for `AgentActivityPanel` that:
- Receives two boards
- Renders a board selector
- Shows an explicit empty state before a board is chosen or when no events exist

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- AgentActivityPanel`
Expected: FAIL with missing component

**Step 3: Implement the UI**

`StreamEvent.tsx`
- Render `thinking`, `tool_call`, and `tool_result`
- Keep expand/collapse only where it actually changes output
- Use stable visual status colors, but preserve existing dashboard look and feel

`AgentStream.tsx`
- Render agent header, model label, event feed, and footer counters
- Auto-scroll only while the user is already near the bottom

`AgentActivityPanel.tsx`
- Accept `boards: { id: string; name: string }[]`
- Persist `open` and `selectedBoardId` in `localStorage`
- Render a board selector in the header
- Call `useAgentActivityStream(selectedBoardId)`
- Show explicit states:
  - no boards configured
  - board not selected
  - connecting
  - connected with zero activity

Do **not** hardcode the first board as hidden state. If you choose a default, make it visible in the selector and persist it.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- AgentActivityPanel`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/components/agents/StreamEvent.tsx frontend/src/components/agents/AgentStream.tsx frontend/src/components/agents/AgentActivityPanel.tsx frontend/src/components/agents/AgentActivityPanel.test.tsx
git commit -m "feat(ui): add agent activity panel components"
```

---

### Task 8: Dashboard integration

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx`

**Step 1: Add the panel to the dashboard**

Implementation requirements:
- Import `AgentActivityPanel`
- Derive `boardOptions` from the existing `boards` memo:

```tsx
const boardOptions = boards.map((board) => ({ id: board.id, name: board.name }));
```

- Render:

```tsx
<AgentActivityPanel boards={boardOptions} />
```

- Keep the panel outside the main content container so it can overlay without disturbing the existing dashboard cards

**Step 2: Run typecheck/build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no type errors

**Step 3: Commit**

```bash
git add frontend/src/app/dashboard/page.tsx
git commit -m "feat(dashboard): integrate agent activity panel"
```

---

### Task 9: End-to-end verification

**Step 1: Run backend tests**

```bash
cd backend && python -m pytest \
  tests/test_activity_stream.py \
  tests/test_activity_stream_connection.py \
  tests/test_activity_stream_broker.py \
  tests/test_agent_activity_api.py -v
```

Expected: all pass

**Step 2: Run frontend targeted tests**

```bash
cd frontend && npm run test -- useAgentActivityStream AgentActivityPanel
```

Expected: all pass

**Step 3: Run frontend build**

```bash
cd frontend && npm run build
```

Expected: build succeeds

**Step 4: Manual local-auth smoke test**

1. Start backend: `cd backend && uv run uvicorn app.main:app --port 8001`
2. Start frontend: `cd frontend && npm run dev`
3. Log in through local auth
4. Open `/dashboard`
5. Open the panel, select a board, confirm the request succeeds instead of 401
6. Trigger a real board-agent action that produces a `session.message` or `session.tool` event
7. Confirm the panel shows that event within a few seconds

**Step 5: Manual disconnect/reconnect smoke test**

1. With the panel open, stop or block the gateway connection temporarily
2. Confirm the panel shows reconnecting state
3. Restore the gateway
4. Confirm new events resume without reloading the page

**Step 6: Final commit**

```bash
git status
```

Expected: clean working tree

Do not claim completion until:
- a real authenticated board stream works
- gateway reconnect logic has been exercised once
- the dashboard panel scope is visibly board-specific
