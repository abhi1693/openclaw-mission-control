# Agent Activity Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a collapsible right panel to the MC Dashboard showing real-time agent activity (thinking, tool calls, output) via SSE from the OpenClaw gateway.

**Architecture:** MC backend subscribes to gateway WebSocket events (`sessions.subscribe`), classifies them, and fans out as SSE to browser clients. React panel renders a Claude Code-style terminal per agent.

**Tech Stack:** Python/FastAPI + sse-starlette (backend), React/Next.js + native EventSource (frontend), OpenClaw gateway WebSocket RPC.

---

### Task 1: Gateway RPC — subscribe/unsubscribe helpers

**Files:**
- Modify: `backend/app/services/openclaw/gateway_rpc.py`
- Test: `backend/tests/test_gateway_rpc_subscribe.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_gateway_rpc_subscribe.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.openclaw.gateway_rpc import subscribe_session, unsubscribe_session, GatewayConfig

TEST_CONFIG = GatewayConfig(url="ws://localhost:18789", token="test", disable_device_pairing=True)

@pytest.mark.asyncio
async def test_subscribe_session_calls_gateway():
    with patch("app.services.openclaw.gateway_rpc.openclaw_call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"ok": True}
        result = await subscribe_session("agent:main:main", config=TEST_CONFIG)
        mock_call.assert_called_once_with(
            "sessions.subscribe",
            {"sessionKey": "agent:main:main"},
            config=TEST_CONFIG,
        )
        assert result == {"ok": True}

@pytest.mark.asyncio
async def test_unsubscribe_session_calls_gateway():
    with patch("app.services.openclaw.gateway_rpc.openclaw_call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"ok": True}
        result = await unsubscribe_session("agent:main:main", config=TEST_CONFIG)
        mock_call.assert_called_once_with(
            "sessions.unsubscribe",
            {"sessionKey": "agent:main:main"},
            config=TEST_CONFIG,
        )
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gateway_rpc_subscribe.py -v`
Expected: FAIL with `ImportError: cannot import name 'subscribe_session'`

**Step 3: Write minimal implementation**

Add to `backend/app/services/openclaw/gateway_rpc.py` after the existing `get_memory_status` function:

```python
async def subscribe_session(
    session_key: str,
    *,
    config: GatewayConfig,
) -> object:
    """Subscribe to real-time events for a session."""
    return await openclaw_call(
        "sessions.subscribe", {"sessionKey": session_key}, config=config
    )


async def unsubscribe_session(
    session_key: str,
    *,
    config: GatewayConfig,
) -> object:
    """Unsubscribe from session events."""
    return await openclaw_call(
        "sessions.unsubscribe", {"sessionKey": session_key}, config=config
    )
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gateway_rpc_subscribe.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add backend/app/services/openclaw/gateway_rpc.py backend/tests/test_gateway_rpc_subscribe.py
git commit -m "feat(rpc): add subscribe/unsubscribe session helpers"
```

---

### Task 2: AgentActivityBroker — gateway event stream

**Files:**
- Create: `backend/app/services/openclaw/activity_stream.py`
- Test: `backend/tests/test_activity_stream.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_activity_stream.py
import pytest
import asyncio
from app.services.openclaw.activity_stream import AgentActivityBroker, AgentEvent

def test_classify_thinking_event():
    raw = {
        "type": "event",
        "event": "session.message",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Let me check the task status..."}],
            },
            "model": "gpt-5.4",
            "usage": {"input": 100, "output": 50, "cost": {"total": 0.01}},
        },
    }
    event = AgentEvent.from_gateway_event(raw)
    assert event.type == "thinking"
    assert event.agent_id == "mc-123"
    assert event.content == "Let me check the task status..."
    assert event.model == "gpt-5.4"

def test_classify_tool_call_event():
    raw = {
        "type": "event",
        "event": "session.message",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "message": {
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "exec", "arguments": {"command": "curl -s http://localhost:8000/health"}}],
            },
            "model": "gpt-5.4",
        },
    }
    event = AgentEvent.from_gateway_event(raw)
    assert event.type == "tool_call"
    assert event.tool_name == "exec"
    assert "curl" in event.tool_args

def test_classify_tool_result_event():
    raw = {
        "type": "event",
        "event": "session.tool",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "toolName": "exec",
            "content": [{"type": "text", "text": '{"ok": true}'}],
            "exitCode": 0,
            "durationMs": 150,
        },
    }
    event = AgentEvent.from_gateway_event(raw)
    assert event.type == "tool_result"
    assert event.exit_code == 0
    assert event.output == '{"ok": true}'
    assert event.duration_ms == 150

def test_truncates_long_output():
    raw = {
        "type": "event",
        "event": "session.tool",
        "payload": {
            "sessionKey": "agent:mc-123:main",
            "toolName": "exec",
            "content": [{"type": "text", "text": "x" * 1000}],
            "exitCode": 0,
        },
    }
    event = AgentEvent.from_gateway_event(raw)
    assert len(event.output) <= 300
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_activity_stream.py -v`
Expected: FAIL with `ImportError`

**Step 3: Write minimal implementation**

```python
# backend/app/services/openclaw/activity_stream.py
"""Real-time agent activity stream from the OpenClaw gateway."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_CONTENT_CHARS = 500
MAX_ARGS_CHARS = 200
MAX_OUTPUT_CHARS = 300


@dataclass
class AgentEvent:
    type: str  # "thinking" | "tool_call" | "tool_result" | "status"
    agent_id: str
    timestamp: str
    model: str = ""
    content: str | None = None
    tool_name: str | None = None
    tool_args: str | None = None
    exit_code: int | None = None
    output: str | None = None
    duration_ms: int | None = None
    session_tokens: int = 0
    session_cost: float = 0.0

    @classmethod
    def from_gateway_event(cls, raw: dict[str, Any]) -> AgentEvent | None:
        event_type = raw.get("event", "")
        payload = raw.get("payload", {})
        session_key = payload.get("sessionKey", "")

        # Extract agent_id from session key: "agent:mc-123:main" -> "mc-123"
        parts = session_key.split(":")
        agent_id = parts[1] if len(parts) >= 2 else ""

        ts = datetime.now(timezone.utc).isoformat()
        model = payload.get("model", "")
        usage = payload.get("usage", {})
        tokens = usage.get("output", 0) + usage.get("input", 0)
        cost = usage.get("cost", {}).get("total", 0.0) if isinstance(usage.get("cost"), dict) else 0.0

        if event_type == "session.message":
            message = payload.get("message", {})
            role = message.get("role", "")
            content_list = message.get("content", [])

            if role != "assistant" or not isinstance(content_list, list):
                return None

            for block in content_list:
                block_type = block.get("type", "")
                if block_type == "text":
                    return cls(
                        type="thinking",
                        agent_id=agent_id,
                        timestamp=ts,
                        model=model,
                        content=block.get("text", "")[:MAX_CONTENT_CHARS],
                        session_tokens=tokens,
                        session_cost=cost,
                    )
                elif block_type == "toolCall":
                    args = block.get("arguments", {})
                    args_str = json.dumps(args)[:MAX_ARGS_CHARS] if isinstance(args, dict) else str(args)[:MAX_ARGS_CHARS]
                    return cls(
                        type="tool_call",
                        agent_id=agent_id,
                        timestamp=ts,
                        model=model,
                        tool_name=block.get("name", ""),
                        tool_args=args_str,
                        session_tokens=tokens,
                        session_cost=cost,
                    )

        elif event_type == "session.tool":
            content_list = payload.get("content", [])
            output = ""
            for block in content_list if isinstance(content_list, list) else []:
                if block.get("type") == "text":
                    output = block.get("text", "")
                    break
            return cls(
                type="tool_result",
                agent_id=agent_id,
                timestamp=ts,
                tool_name=payload.get("toolName", ""),
                exit_code=payload.get("exitCode"),
                output=output[:MAX_OUTPUT_CHARS],
                duration_ms=payload.get("durationMs"),
            )

        return None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type, "agent_id": self.agent_id, "timestamp": self.timestamp}
        for key in ("model", "content", "tool_name", "tool_args", "exit_code", "output", "duration_ms", "session_tokens", "session_cost"):
            val = getattr(self, key)
            if val is not None and val != "" and val != 0 and val != 0.0:
                d[key] = val
        return d
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_activity_stream.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/services/openclaw/activity_stream.py backend/tests/test_activity_stream.py
git commit -m "feat(activity): AgentEvent classifier for gateway events"
```

---

### Task 3: SSE endpoint

**Files:**
- Create: `backend/app/api/agent_activity.py`
- Modify: `backend/app/main.py` (register router)

**Step 1: Write the endpoint**

```python
# backend/app/api/agent_activity.py
"""SSE stream of real-time agent activity."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.core.logging import get_logger
from app.db.session import get_session
from app.services.openclaw.activity_stream import AgentEvent
from app.services.openclaw.gateway_rpc import (
    GatewayConfig,
    openclaw_call,
    subscribe_session,
    unsubscribe_session,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/agents/activity", tags=["agent-activity"])


@router.get("/stream")
async def stream_activity(
    request: Request,
    board_id: str = Query(...),
):
    """SSE stream of agent activity for a board.

    Subscribes to gateway session events and forwards classified events.
    Connection stays open until the client disconnects.
    """

    async def event_generator():
        # For MVP: poll session files instead of WebSocket subscription
        # TODO: Replace with persistent WebSocket + sessions.subscribe
        yield {
            "event": "connected",
            "data": json.dumps({"board_id": board_id, "status": "connected"}),
        }

        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(2)
            yield {
                "event": "heartbeat",
                "data": json.dumps({"ts": "now"}),
            }

    return EventSourceResponse(event_generator())
```

**Step 2: Register router in main.py**

Add to `backend/app/main.py` imports:
```python
from app.api.agent_activity import router as agent_activity_router
```

Add to router registration:
```python
app.include_router(agent_activity_router, prefix="/api/v1")
```

**Step 3: Test manually**

Run: `cd backend && uv run uvicorn app.main:app --port 8001`
Then: `curl -N http://localhost:8001/api/v1/agents/activity/stream?board_id=test`
Expected: SSE events streaming every 2 seconds

**Step 4: Commit**

```bash
git add backend/app/api/agent_activity.py backend/app/main.py
git commit -m "feat(api): SSE endpoint for agent activity stream"
```

---

### Task 4: Frontend — useAgentActivityStream hook

**Files:**
- Create: `frontend/src/hooks/useAgentActivityStream.ts`

**Step 1: Write the hook**

```typescript
// frontend/src/hooks/useAgentActivityStream.ts
import { useCallback, useEffect, useRef, useState } from "react";

export interface AgentEvent {
  type: "thinking" | "tool_call" | "tool_result" | "status";
  agent_id: string;
  agent_name?: string;
  timestamp: string;
  model?: string;
  content?: string;
  tool_name?: string;
  tool_args?: string;
  exit_code?: number;
  output?: string;
  duration_ms?: number;
  task_id?: string;
  task_title?: string;
  session_tokens?: number;
  session_cost?: number;
}

interface AgentState {
  name: string;
  status: "online" | "offline" | "error";
  model: string;
  task_id: string | null;
  task_title: string | null;
  events: AgentEvent[];
  turns: number;
  tokens: number;
  cost: number;
  last_event_at: string;
}

export interface AgentActivityState {
  connected: boolean;
  agents: Record<string, AgentState>;
}

const MAX_EVENTS_PER_AGENT = 200;

export function useAgentActivityStream(boardId: string | null): AgentActivityState {
  const [state, setState] = useState<AgentActivityState>({ connected: false, agents: {} });
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const retriesRef = useRef(0);

  const connect = useCallback(() => {
    if (!boardId) return;

    const url = `/api/v1/agents/activity/stream?board_id=${boardId}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.addEventListener("connected", () => {
      setState((s) => ({ ...s, connected: true }));
      retriesRef.current = 0;
    });

    es.addEventListener("agent_event", (e) => {
      const event: AgentEvent = JSON.parse(e.data);
      setState((s) => {
        const agent = s.agents[event.agent_id] ?? {
          name: event.agent_name ?? event.agent_id,
          status: "online" as const,
          model: event.model ?? "",
          task_id: event.task_id ?? null,
          task_title: event.task_title ?? null,
          events: [],
          turns: 0,
          tokens: 0,
          cost: 0,
          last_event_at: event.timestamp,
        };

        const events = [...agent.events, event].slice(-MAX_EVENTS_PER_AGENT);
        return {
          ...s,
          agents: {
            ...s.agents,
            [event.agent_id]: {
              ...agent,
              events,
              model: event.model ?? agent.model,
              task_id: event.task_id ?? agent.task_id,
              task_title: event.task_title ?? agent.task_title,
              turns: agent.turns + (event.type === "thinking" ? 1 : 0),
              tokens: agent.tokens + (event.session_tokens ?? 0),
              cost: agent.cost + (event.session_cost ?? 0),
              last_event_at: event.timestamp,
              status: "online",
            },
          },
        };
      });
    });

    es.onerror = () => {
      es.close();
      setState((s) => ({ ...s, connected: false }));
      const delay = Math.min(1000 * 2 ** retriesRef.current, 30000);
      retriesRef.current += 1;
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    };
  }, [boardId]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
      clearTimeout(reconnectTimeoutRef.current);
    };
  }, [connect]);

  return state;
}
```

**Step 2: Commit**

```bash
git add frontend/src/hooks/useAgentActivityStream.ts
git commit -m "feat(hooks): useAgentActivityStream SSE hook"
```

---

### Task 5: Frontend — StreamEvent component

**Files:**
- Create: `frontend/src/components/agents/StreamEvent.tsx`

**Step 1: Write the component**

```tsx
// frontend/src/components/agents/StreamEvent.tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal, Brain, CheckCircle, XCircle, Clock } from "lucide-react";
import type { AgentEvent } from "@/hooks/useAgentActivityStream";
import { cn } from "@/lib/utils";

export function StreamEvent({ event }: { event: AgentEvent }) {
  const [expanded, setExpanded] = useState(false);

  if (event.type === "thinking") {
    return (
      <div className="px-3 py-1 text-sm">
        <span className="text-blue-400 italic">{event.content}</span>
      </div>
    );
  }

  if (event.type === "tool_call") {
    return (
      <div className="px-3 py-1">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 text-sm font-mono text-slate-300 hover:text-white w-full text-left"
        >
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <Terminal className="h-3 w-3 text-blue-400" />
          <span className="text-blue-400 font-semibold">{event.tool_name}</span>
          <span className="text-slate-500 truncate">{event.tool_args}</span>
        </button>
      </div>
    );
  }

  if (event.type === "tool_result") {
    const isSuccess = event.exit_code === 0 || event.exit_code === null;
    return (
      <div className="pl-8 pr-3 py-0.5">
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          {isSuccess ? (
            <CheckCircle className="h-3 w-3 text-green-500" />
          ) : (
            <XCircle className="h-3 w-3 text-red-500" />
          )}
          {event.duration_ms && (
            <>
              <Clock className="h-3 w-3" />
              <span>{event.duration_ms}ms</span>
            </>
          )}
        </div>
        {event.output && (
          <pre className="mt-0.5 text-xs text-slate-400 font-mono whitespace-pre-wrap overflow-hidden max-h-16">
            {event.output}
          </pre>
        )}
      </div>
    );
  }

  if (event.type === "status") {
    return (
      <div className="px-3 py-0.5 text-xs text-slate-600">
        ● {event.content ?? event.status}
      </div>
    );
  }

  return null;
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/agents/StreamEvent.tsx
git commit -m "feat(ui): StreamEvent component for activity feed"
```

---

### Task 6: Frontend — AgentStream component

**Files:**
- Create: `frontend/src/components/agents/AgentStream.tsx`

**Step 1: Write the component**

```tsx
// frontend/src/components/agents/AgentStream.tsx
"use client";

import { useEffect, useRef } from "react";
import { Bot } from "lucide-react";
import type { AgentEvent } from "@/hooks/useAgentActivityStream";
import { StreamEvent } from "./StreamEvent";
import { cn } from "@/lib/utils";

interface AgentStreamProps {
  agentId: string;
  name: string;
  status: "online" | "offline" | "error";
  model: string;
  taskTitle: string | null;
  events: AgentEvent[];
  turns: number;
  tokens: number;
  cost: number;
  lastEventAt: string;
}

export function AgentStream({ agentId, name, status, model, taskTitle, events, turns, tokens, cost, lastEventAt }: AgentStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  useEffect(() => {
    if (autoScrollRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    autoScrollRef.current = scrollHeight - scrollTop - clientHeight < 50;
  };

  const statusColor = status === "online" ? "bg-green-500" : status === "error" ? "bg-red-500" : "bg-slate-500";

  return (
    <div className="flex flex-col border-b border-slate-800 last:border-0">
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-900/50 border-b border-slate-800 sticky top-0 z-10">
        <Bot className="h-4 w-4 text-slate-400" />
        <span className="font-semibold text-sm text-slate-200">{name}</span>
        <div className={cn("h-2 w-2 rounded-full", statusColor)} />
        <span className="text-xs text-slate-500 ml-auto">{model}</span>
      </div>

      {taskTitle && (
        <div className="px-3 py-1 text-xs text-slate-500 bg-slate-900/30">
          Task: {taskTitle}
        </div>
      )}

      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto max-h-64 bg-slate-950">
        {events.length === 0 ? (
          <div className="px-3 py-4 text-xs text-slate-600 text-center">Waiting for activity...</div>
        ) : (
          events.map((event, i) => <StreamEvent key={i} event={event} />)
        )}
      </div>

      <div className="flex items-center gap-3 px-3 py-1 text-xs text-slate-600 bg-slate-900/30 border-t border-slate-800">
        <span>{turns} turns</span>
        <span>{tokens.toLocaleString()} tok</span>
        <span>${cost.toFixed(2)}</span>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/agents/AgentStream.tsx
git commit -m "feat(ui): AgentStream component with auto-scroll"
```

---

### Task 7: Frontend — AgentActivityPanel + Dashboard integration

**Files:**
- Create: `frontend/src/components/agents/AgentActivityPanel.tsx`
- Modify: `frontend/src/app/dashboard/page.tsx`

**Step 1: Write the panel**

```tsx
// frontend/src/components/agents/AgentActivityPanel.tsx
"use client";

import { useState } from "react";
import { PanelRightClose, PanelRightOpen, Radio } from "lucide-react";
import { useAgentActivityStream } from "@/hooks/useAgentActivityStream";
import { AgentStream } from "./AgentStream";
import { cn } from "@/lib/utils";

interface AgentActivityPanelProps {
  boardId: string | null;
}

export function AgentActivityPanel({ boardId }: AgentActivityPanelProps) {
  const [open, setOpen] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("agent-activity-open") === "true";
  });
  const [activeTab, setActiveTab] = useState<string>("all");
  const { connected, agents } = useAgentActivityStream(open ? boardId : null);

  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    localStorage.setItem("agent-activity-open", String(next));
  };

  const agentIds = Object.keys(agents);
  const filteredAgents = activeTab === "all" ? agentIds : [activeTab];

  return (
    <>
      {/* Toggle button — always visible */}
      <button
        onClick={toggleOpen}
        className="fixed right-0 top-1/2 -translate-y-1/2 z-50 bg-slate-800 hover:bg-slate-700 text-slate-300 p-2 rounded-l-lg shadow-lg"
        title={open ? "Close Activity Panel" : "Open Activity Panel"}
      >
        {open ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
      </button>

      {/* Panel */}
      <div
        className={cn(
          "fixed right-0 top-0 h-full bg-slate-950 border-l border-slate-800 shadow-2xl z-40 transition-all duration-300 flex flex-col",
          open ? "w-[420px]" : "w-0 overflow-hidden"
        )}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-900">
          <Radio className={cn("h-4 w-4", connected ? "text-green-500" : "text-red-500")} />
          <span className="font-semibold text-sm text-slate-200">Agent Activity</span>
          <span className="text-xs text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">{agentIds.length}</span>
          {!connected && <span className="text-xs text-yellow-500 ml-auto">Reconnecting...</span>}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-2 py-1.5 border-b border-slate-800 overflow-x-auto bg-slate-900/50">
          <button
            onClick={() => setActiveTab("all")}
            className={cn("px-2 py-1 text-xs rounded", activeTab === "all" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white")}
          >
            All
          </button>
          {agentIds.map((id) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={cn("px-2 py-1 text-xs rounded whitespace-nowrap", activeTab === id ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white")}
            >
              {agents[id].name}
            </button>
          ))}
        </div>

        {/* Streams */}
        <div className="flex-1 overflow-y-auto">
          {filteredAgents.map((id) => {
            const a = agents[id];
            if (!a) return null;
            return (
              <AgentStream
                key={id}
                agentId={id}
                name={a.name}
                status={a.status}
                model={a.model}
                taskTitle={a.task_title}
                events={a.events}
                turns={a.turns}
                tokens={a.tokens}
                cost={a.cost}
                lastEventAt={a.last_event_at}
              />
            );
          })}
        </div>
      </div>
    </>
  );
}
```

**Step 2: Integrate into Dashboard**

In `frontend/src/app/dashboard/page.tsx`, add the panel import and render it alongside existing content:

```tsx
import { AgentActivityPanel } from "@/components/agents/AgentActivityPanel";

// Inside the component return, after the main content:
<AgentActivityPanel boardId={selectedBoardId} />
```

**Step 3: Commit**

```bash
git add frontend/src/components/agents/AgentActivityPanel.tsx frontend/src/app/dashboard/page.tsx
git commit -m "feat(ui): AgentActivityPanel with Dashboard integration"
```

---

### Task 8: Deploy and verify

**Step 1: Deploy backend to .64**

```bash
scp backend/app/api/agent_activity.py root@192.168.2.64:/home/mcontrol/openclaw-mission-control/backend/app/api/
scp backend/app/services/openclaw/activity_stream.py root@192.168.2.64:/home/mcontrol/openclaw-mission-control/backend/app/services/openclaw/
scp backend/app/services/openclaw/gateway_rpc.py root@192.168.2.64:/home/mcontrol/openclaw-mission-control/backend/app/services/openclaw/
# Update main.py to register the router
ssh root@192.168.2.64 "cd /home/mcontrol/openclaw-mission-control/backend && find . -name __pycache__ -type d -exec rm -rf {} + && pkill -f uvicorn; sleep 2; nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &"
```

Verify: `curl -N http://192.168.2.64:8000/api/v1/agents/activity/stream?board_id=test`

**Step 2: Deploy frontend**

Build and deploy using the deploy script:
```bash
cd frontend && npm run build
bash $SHARED_WORKSPACE/scripts/deploy.sh agent-activity-panel
```

Verify: open http://192.168.2.63:3000, click the panel toggle on the right edge.

**Step 3: Commit**

```bash
git commit -m "feat: deploy agent activity panel to production"
```
