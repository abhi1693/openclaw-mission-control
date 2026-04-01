# Board Chat Implementation Plan (v4 — final)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a real-time chat panel to the TaskFlow board UI so users can send/receive messages to agents without WhatsApp — messages enter NanoClaw's agent pipeline the same way channel messages do.

**Architecture:** The TaskFlow API (`main.py`) gets chat endpoints backed by a `board_chat` table in `taskflow.db`. To inject messages into the agent pipeline, the API writes directly to `store/messages.db` (a SEPARATE database from `taskflow.db`) via a second SQLite connection. The NanoClaw polling loop picks them up via `getNewMessages()`. Agent responses route to `board_chat` (not WhatsApp) when `missedMessages` contains a `web:` sender prefix. The React dashboard gets a `BoardChat.tsx` using the existing WebSocket for real-time delivery.

**Tech Stack:** FastAPI (Python), SQLite (better-sqlite3), React 19, TypeScript, Tailwind CSS, WebSocket (existing)

**Key file locations:**
- NanoClaw source: `root@192.168.2.160:~/nanoclaw/`
- NanoClaw data: `~/nanoclaw/data/` — IPC: `data/ipc/{group}/messages/`, TaskFlow DB: `data/taskflow/taskflow.db`
- NanoClaw messages DB: `~/nanoclaw/store/messages.db` (SEPARATE from taskflow.db)
- TaskFlow API: deployed 192.168.2.63:8100, source on gateway
- TaskFlow Dashboard: deployed 192.168.2.63:3000, source in PF workspace on gateway

**Review history:**
- v1: Initial plan
- v2: Codex review — fixed IPC watcher, trigger bypass, DB path, WebSocket reuse
- v3: Claude Code agent review — fixed cross-DB write (messages.db ≠ taskflow.db), prompt type (string not array), missing RegisteredGroup field, env vars, frontend API patterns
- v4: Codex final review — removed contradictory IPC file code, fixed timestamp format mismatch, fixed unsafe output routing closure, added messages.db WAL mode, fixed hardcoded sender name

---

### Task 1: SQLite Schema — board_chat table in taskflow.db

**Files:**
- Modify: `src/taskflow-db.ts` (add table to schema)

**Step 1: Add board_chat table**

In `src/taskflow-db.ts`, add to the schema string:

```sql
CREATE TABLE IF NOT EXISTS board_chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board_id TEXT NOT NULL REFERENCES boards(id),
  sender_name TEXT NOT NULL,
  sender_type TEXT NOT NULL DEFAULT 'user',
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_board_chat_board_ts ON board_chat(board_id, created_at);
```

**Step 2: Run migration on live DB**

```bash
ssh root@192.168.2.160 "sqlite3 ~/nanoclaw/data/taskflow/taskflow.db 'CREATE TABLE IF NOT EXISTS board_chat (id INTEGER PRIMARY KEY AUTOINCREMENT, board_id TEXT NOT NULL REFERENCES boards(id), sender_name TEXT NOT NULL, sender_type TEXT NOT NULL DEFAULT \"user\", content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime(\"now\"))); CREATE INDEX IF NOT EXISTS idx_board_chat_board_ts ON board_chat(board_id, created_at);'"
```

**Step 3: Rebuild**

```bash
ssh root@192.168.2.160 "cd ~/nanoclaw && npm run build"
```

**Step 4: Commit**

```bash
git add src/taskflow-db.ts
git commit -m "feat(taskflow): add board_chat SQLite table"
```

---

### Task 2: TaskFlow API — chat endpoints + IPC bridge

**Files:**
- Modify: `taskflow-api/main.py`

**Step 1: Add chat model and endpoints**

Add before the `@app.websocket("/ws")` line:

```python
class ChatMessageInput(BaseModel):
    content: str
    sender_name: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be empty")
        return stripped

@app.get("/boards/{board_id}/chat", dependencies=[Depends(require_auth)])
def list_chat(
    board_id: str,
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    with db_connection() as conn:
        ensure_board_exists(conn, board_id)
        query = "SELECT id, board_id, sender_name, sender_type, content, created_at FROM board_chat WHERE board_id = ?"
        params: list[Any] = [board_id]
        if since:
            query += " AND created_at > ?"
            params.append(since)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

@app.post("/boards/{board_id}/chat", dependencies=[Depends(require_auth)], status_code=201)
def post_chat(board_id: str, payload: ChatMessageInput) -> dict[str, Any]:
    with db_connection(read_only=False) as conn:
        ensure_board_exists(conn, board_id)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Write to board_chat (same DB — taskflow.db)
        conn.execute(
            "INSERT INTO board_chat (board_id, sender_name, sender_type, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (board_id, payload.sender_name, payload.content, now),
        )
        conn.commit()

        # 2. Write to store/messages.db (SEPARATE DB) so NanoClaw's polling loop picks it up.
        board_row = conn.execute("SELECT group_jid FROM boards WHERE id = ?", (board_id,)).fetchone()
        if board_row:
            _inject_message_for_agent(
                chat_jid=board_row["group_jid"],
                sender_name=payload.sender_name,
                content=payload.content,
            )

        row = conn.execute(
            "SELECT id, board_id, sender_name, sender_type, content, created_at FROM board_chat WHERE board_id = ? ORDER BY id DESC LIMIT 1",
            (board_id,),
        ).fetchone()
        return dict(row)
```

**Step 2: Add messages.db writer**

The TaskFlow API writes to `store/messages.db` (separate from `taskflow.db`) so NanoClaw's polling loop picks up web chat messages via `getNewMessages()`.

**Note:** `messages.db` uses `journal_mode=delete` by default. The writer sets WAL mode and busy_timeout to handle concurrent access with NanoClaw's Node process.

```python
import os
def _get_messages_db_path() -> str:
    """Resolve NanoClaw messages.db path from TASKFLOW_DB_PATH."""
    db_path = get_db_path()
    if db_path:
        # data/taskflow/taskflow.db → store/messages.db
        nanoclaw_root = os.path.dirname(os.path.dirname(os.path.dirname(db_path)))
        return os.path.join(nanoclaw_root, "store", "messages.db")
    return os.getenv("NANOCLAW_MESSAGES_DB", "")

def _inject_message_for_agent(chat_jid: str, sender_name: str, content: str) -> None:
    """Write directly to NanoClaw's messages.db so the polling loop picks it up."""
    messages_db = _get_messages_db_path()
    if not messages_db or not os.path.exists(messages_db):
        return
    msg_id = f"web-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    # Use ISO format WITHOUT timezone suffix — matches NanoClaw's timestamp format
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    conn = sqlite3.connect(messages_db, timeout=10)
    try:
        # Enable WAL for safe concurrent access with NanoClaw's Node process
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            "INSERT OR REPLACE INTO messages (id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message) VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
            (msg_id, chat_jid, f"web:{sender_name}", f"web:{sender_name}", content, now),
        )
        conn.commit()
    finally:
        conn.close()
```

Then in `post_chat`, replace the IPC file write with:

```python
if board_row:
    _inject_message_for_agent(
        chat_jid=board_row["group_jid"],
        sender_name=payload.sender_name,
        content=payload.content,
    )
```

Add env var `NANOCLAW_MESSAGES_DB` to the TaskFlow API's `.env` as a fallback:
```
NANOCLAW_MESSAGES_DB=/home/nanoclaw/nanoclaw/store/messages.db
```

**Step 3: Extend WebSocket for chat events**

In `websocket_endpoint`, add chat tracking. Initialize after accept:

```python
last_chat_id = 0
with db_connection() as conn:
    row = conn.execute("SELECT MAX(id) as last_id FROM board_chat").fetchone()
    last_chat_id = row["last_id"] or 0 if row else 0
```

In the while loop, after the `taskflow:updated` block:

```python
with db_connection() as conn:
    row = conn.execute("SELECT MAX(id) as last_id FROM board_chat").fetchone()
    current_chat_id = row["last_id"] or 0 if row else 0

if current_chat_id > last_chat_id:
    with db_connection() as conn:
        new_msgs = conn.execute(
            "SELECT id, board_id, sender_name, sender_type, content, created_at FROM board_chat WHERE id > ? ORDER BY id ASC",
            (last_chat_id,),
        ).fetchall()
        if new_msgs:
            await websocket.send_json({
                "event": "chat:new",
                "data": [dict(m) for m in new_msgs],
            })
    last_chat_id = current_chat_id
```

Note: This broadcasts ALL boards' chat to all clients. The frontend filters by `boardId`. Acceptable for now.

**Step 4: Commit**

```bash
git add taskflow-api/main.py
git commit -m "feat(taskflow): board chat API + messages.db injection for agent pipeline"
```

---

### Task 3: NanoClaw — trigger bypass + agent output routing

**Files:**
- Modify: `src/index.ts` (trigger bypass + output routing)

**Step 1: Bypass trigger for web chat messages**

In `processGroupMessages` (~line 464), BEFORE the trigger check, add:

```typescript
// Bypass trigger for web chat messages (sender starts with "web:")
const hasWebChatMessage = missedMessages.some(
  (m) => m.sender.startsWith('web:')
);
```

Then modify the trigger check (~line 465-467):

```typescript
// Original:
if (!isMainGroup && group.requiresTrigger !== false) {
  if (!hasTriggerMessage(missedMessages, chatJid, group)) return true;
}

// Changed:
if (!isMainGroup && group.requiresTrigger !== false && !hasWebChatMessage) {
  if (!hasTriggerMessage(missedMessages, chatJid, group)) return true;
}
```

**Also** add the same bypass in the polling loop (~line 750-758 in `startMessageLoop`):

```typescript
// Before the existing trigger check in the polling loop:
const hasWebChat = groupMessages.some(
  (m) => m.sender.startsWith('web:')
);

const needsTrigger = !isMainGroup && group.requiresTrigger !== false;
if (needsTrigger && !hasWebChat) {
  if (!hasTriggerMessage(groupMessages, chatJid, group)) continue;
}
```

**Step 2: Route agent output to board_chat for web-originated conversations**

In `processGroupMessages`, the output callback is at ~line 514 inside `runAgent()`. The closure has access to `missedMessages` (the `NewMessage[]` array — NOT `prompt` which is a string).

Replace the output sending block:

```typescript
// Original:
if (text) {
  await channel.sendMessage(chatJid, text, groupSender);
  outputSentToUser = true;
}

// Changed:
if (text) {
  // Resolve web-chat origin ONCE before runAgent and capture in closure.
  // NOTE: This const must be declared BEFORE the runAgent call, outside the callback,
  // so it captures the initial message set. Piped follow-up messages from different
  // sources won't change the routing mid-session — acceptable trade-off.
  //
  // *** ADD THIS LINE before the `await runAgent(...)` call, NOT inside the callback: ***
  // const isWebOrigin = missedMessages.some((m) => m.sender.startsWith('web:'));
  // const webChatBoardId = isWebOrigin
  //   ? resolveTaskflowBoardId(group.folder, group.taskflowManaged === true)
  //   : undefined;

  // Then inside the callback:
  if (isWebOrigin && webChatBoardId) {
    // Write to board_chat table instead of WhatsApp
    const tfDb = getTaskflowDb(DATA_DIR);
    if (tfDb) {
      try {
        tfDb.prepare(
          `INSERT INTO board_chat (board_id, sender_name, sender_type, content, created_at)
           VALUES (?, ?, 'agent', ?, strftime('%Y-%m-%d %H:%M:%S', 'now'))`
        ).run(webChatBoardId, groupSender, text);
        logger.info({ group: group.name, boardId: webChatBoardId }, 'Web chat reply → board_chat');
        outputSentToUser = true;
      } catch (err) {
        logger.error({ err }, 'Failed to write web chat reply to board_chat');
        // Fallback: send to WhatsApp so the message isn't lost
        await channel.sendMessage(chatJid, text, groupSender);
        outputSentToUser = true;
      }
    } else {
      // taskflow.db not available — fallback to WhatsApp
      await channel.sendMessage(chatJid, text, groupSender);
      outputSentToUser = true;
    }
  } else {
    await channel.sendMessage(chatJid, text, groupSender);
    outputSentToUser = true;
  }
}
```

**Key:** `isWebOrigin` and `webChatBoardId` must be resolved BEFORE `runAgent()` is called and captured in the closure. This avoids the stale-closure problem where piped follow-up messages could change the source mix mid-run. The trade-off is that a session started by WhatsApp won't route to board_chat even if a web message arrives mid-session — acceptable.

Add import at top of `src/index.ts`:

```typescript
import { resolveTaskflowBoardId } from './taskflow-db.js';
```

**Step 3: Rebuild and test**

```bash
ssh root@192.168.2.160 "cd ~/nanoclaw && npm run build"
```

**Step 4: Commit**

```bash
git add src/index.ts
git commit -m "feat(taskflow): web chat trigger bypass + route agent output to board_chat"
```

---

### Task 4: MCP tool — send_board_chat

**Files:**
- Modify: `container/agent-runner/src/ipc-mcp-stdio.ts`

**Step 1: Register send_board_chat tool**

Inside the `if (process.env.NANOCLAW_IS_TASKFLOW_MANAGED === '1')` block (~line 582), after `boardId` is defined, add:

```typescript
server.tool(
  'send_board_chat',
  'Send a reply to the board web chat UI (visible in TaskFlow dashboard, not WhatsApp)',
  {
    content: { type: 'string', description: 'Message content to send to board chat' },
  },
  async (args) => {
    if (!args.content || !boardId) {
      return { content: [{ type: 'text', text: 'Error: content and boardId required' }] };
    }
    // The container has RW access to /workspace/taskflow/taskflow.db
    const chatDb = new Database(dbPath);
    try {
      chatDb.prepare(
        `INSERT INTO board_chat (board_id, sender_name, sender_type, content, created_at)
         VALUES (?, ?, 'agent', ?, strftime('%Y-%m-%d %H:%M:%S', 'now'))`
      ).run(boardId, process.env.NANOCLAW_ASSISTANT_NAME || 'Agent', String(args.content));
      return { content: [{ type: 'text', text: 'Chat reply sent to board UI.' }] };
    } finally {
      chatDb.close();
    }
  }
);
```

Note: `NANOCLAW_TASKFLOW_BOARD_ID` is set by `runtime-config.ts:55` and `boardId` is already read at line 585. `NANOCLAW_ASSISTANT_NAME` does NOT exist — use `containerInput.assistantName` from the stdin JSON input, or pass it as a new env var in `runtime-config.ts`.

**Step 2: Add assistant name to container env (if needed)**

In `container/agent-runner/src/runtime-config.ts`, add inside `buildNanoclawMcpEnv`:

```typescript
if (containerInput.assistantName) {
  env.NANOCLAW_ASSISTANT_NAME = containerInput.assistantName;
}
```

**Step 3: Rebuild**

```bash
ssh root@192.168.2.160 "cd ~/nanoclaw && npm run build"
```

**Step 4: Commit**

```bash
git add container/agent-runner/src/ipc-mcp-stdio.ts container/agent-runner/src/runtime-config.ts
git commit -m "feat(taskflow): send_board_chat MCP tool + NANOCLAW_ASSISTANT_NAME env"
```

---

### Task 5: TaskFlow Dashboard — BoardChat component

**Files:**
- Create: `taskflow-dashboard/src/components/BoardChat.tsx`
- Modify: `taskflow-dashboard/src/lib/api.ts` (add chat methods — NOTE: uses `request<T>()`, not `get<T>()`)
- Modify: `taskflow-dashboard/src/types/index.ts` (add ChatMessage, extend WsEvent as discriminated union)
- Modify: `taskflow-dashboard/src/hooks/useTaskFlowWebSocket.ts` (handle `chat:new` events)
- Modify: board view page (add chat panel toggle — NO existing chat icon, must create one)

**Step 1: Add types**

In `src/types/index.ts` (note: `types/index.ts`, not `types.ts`):

```typescript
export interface ChatMessage {
  id: number;
  board_id: string;
  sender_name: string;
  sender_type: "user" | "agent";
  content: string;
  created_at: string;
}

// Change WsEvent from interface to discriminated union:
export type WsEvent =
  | { event: "taskflow:snapshot"; data: Stats }
  | { event: "taskflow:updated"; data: Stats }
  | { event: "chat:new"; data: ChatMessage[] };
```

**Step 2: Add API methods**

In `src/lib/api.ts`, add to `taskflowApi`:

```typescript
listChat: (boardId: string, since?: string) => {
  const query = since ? `?since=${encodeURIComponent(since)}` : "";
  return request<ChatMessage[]>(`/boards/${encodeURIComponent(boardId)}/chat${query}`);
},
sendChat: (boardId: string, content: string, senderName: string) =>
  request<ChatMessage>(
    `/boards/${encodeURIComponent(boardId)}/chat`,
    {
      method: "POST",
      body: JSON.stringify({ content, sender_name: senderName }),
    },
  ),
```

Note: Uses `request<T>()` — NOT `get<T>()` which doesn't exist.

**Step 3: Extend WebSocket hook**

In `src/hooks/useTaskFlowWebSocket.ts`:

```typescript
const handleSocketEvent = useEffectEvent((event: WsEvent) => {
  if (event.event === "taskflow:updated") {
    window.dispatchEvent(new CustomEvent("taskflow:updated", { detail: event.data }));
    startTransition(() => {
      queryClient.invalidateQueries({
        predicate: (query) => query.queryKey[0] === "taskflow",
      });
    });
    const now = Date.now();
    if (now - lastToastRef.current > 10_000) {
      toast.info("Board updated");
      lastToastRef.current = now;
    }
  }

  // NEW: dispatch chat events
  if (event.event === "chat:new") {
    window.dispatchEvent(new CustomEvent("chat:new", { detail: event.data }));
  }
});
```

**Step 4: Create BoardChat component**

Create `src/components/BoardChat.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle, X, Send } from "lucide-react";
import type { ChatMessage } from "../types";
import { taskflowApi } from "../lib/api";

interface BoardChatProps {
  boardId: string;
  senderName: string;
  onClose: () => void;
}

export default function BoardChat({ boardId, senderName, onClose }: BoardChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    taskflowApi.listChat(boardId).then(setMessages).catch(console.error);
  }, [boardId]);

  useEffect(() => {
    const handler = (e: Event) => {
      const newMsgs = (e as CustomEvent).detail as ChatMessage[];
      const boardMsgs = newMsgs.filter((m) => m.board_id === boardId);
      if (boardMsgs.length > 0) {
        setMessages((prev) => {
          const ids = new Set(prev.map((m) => m.id));
          return [...prev, ...boardMsgs.filter((m) => !ids.has(m.id))];
        });
      }
    };
    window.addEventListener("chat:new", handler);
    return () => window.removeEventListener("chat:new", handler);
  }, [boardId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const msg = await taskflowApi.sendChat(boardId, text, senderName);
      setMessages((prev) => [...prev, msg]);
      setInput("");
    } catch (err) {
      console.error("Failed to send:", err);
    } finally {
      setSending(false);
    }
  }, [boardId, input, senderName, sending]);

  return (
    <div className="flex flex-col h-full border-l border-slate-200 bg-white w-80 shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <MessageCircle className="h-4 w-4 text-blue-500" />
          <h3 className="text-sm font-semibold text-slate-700">Board Chat</h3>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
        {messages.length === 0 && (
          <p className="text-xs text-slate-400 text-center py-8">No messages yet</p>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`flex flex-col ${msg.sender_type === "user" ? "items-end" : "items-start"}`}>
            <span className="text-xs text-slate-400 mb-0.5">{msg.sender_name}</span>
            <div className={`rounded-lg px-3 py-2 text-sm max-w-[85%] ${
              msg.sender_type === "user" ? "bg-blue-500 text-white" : "bg-slate-100 text-slate-800"
            }`}>
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-slate-200 px-4 py-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder="Type a message..."
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={sending}
          />
          <button
            onClick={send}
            disabled={sending || !input.trim()}
            className="rounded-lg bg-blue-500 px-3 py-2 text-white hover:bg-blue-600 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
```

**Step 5: Wire into board view**

Add a `MessageCircle` button to the board toolbar and render `BoardChat` alongside the kanban. The exact file is the board view in PF's workspace. Add:

```tsx
import { MessageCircle } from "lucide-react";
import BoardChat from "../components/BoardChat";

// State:
const [chatOpen, setChatOpen] = useState(false);

// New toolbar button:
<button
  onClick={() => setChatOpen(!chatOpen)}
  className={`rounded-lg p-2 transition ${chatOpen ? "bg-blue-100 text-blue-600" : "text-slate-400 hover:text-slate-600"}`}
  title="Board Chat"
>
  <MessageCircle className="h-5 w-5" />
</button>

// Chat panel alongside kanban:
<div className="flex min-h-0 flex-1">
  {/* existing kanban content */}
  {chatOpen && (
    {/* senderName should come from auth context or board owner. For now, read from board.people[0] (owner) */}
    <BoardChat boardId={boardId} senderName={board?.people?.[0]?.name ?? "User"} onClose={() => setChatOpen(false)} />
  )}
</div>
```

**Step 6: Build and deploy**

```bash
cd taskflow-dashboard && npm run build
```

**Step 7: Commit**

```bash
git add src/components/BoardChat.tsx src/lib/api.ts src/types/index.ts src/hooks/useTaskFlowWebSocket.ts
git commit -m "feat(taskflow): board chat UI with WebSocket real-time updates"
```

---

### Task 6: Agent prompt — document web chat tools

**Files:**
- Modify: Group CLAUDE.md template in the TaskFlow skill

**Step 1: Add documentation**

```markdown
## Board Web Chat

Messages from the TaskFlow board UI arrive with sender prefix `web:` (e.g., `web:Miguel`).

- Reply using `send_board_chat` tool — sends to the board UI chat panel
- Do NOT use `send_message` for web chat replies — that sends to WhatsApp
- Auto-routing also works: if the conversation started from web chat, your normal output goes to board_chat automatically
```

**Step 2: Commit**

```bash
git commit -m "docs(taskflow): document send_board_chat tool and web: sender prefix"
```

---

### Task 7: Integration test — E2E round-trip

**Step 1:** Post chat via API:
```bash
curl -X POST http://192.168.2.63:8100/boards/board-sec-taskflow/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "What tasks are in progress?", "sender_name": "Miguel"}'
```

**Step 2:** Verify in messages.db (agent pipeline):
```bash
ssh root@192.168.2.160 "sqlite3 ~/nanoclaw/store/messages.db \"SELECT id, sender_name, content FROM messages WHERE sender_name LIKE 'web:%' ORDER BY timestamp DESC LIMIT 3;\""
```

**Step 3:** Verify agent responds to board_chat:
```bash
ssh root@192.168.2.160 "sqlite3 ~/nanoclaw/data/taskflow/taskflow.db 'SELECT * FROM board_chat ORDER BY id DESC LIMIT 5;'"
```

**Step 4:** Open browser, verify chat panel shows response via WebSocket.

---

## Deployment Sequence

1. Task 1: Schema migration (safe, additive)
2. Task 2: API endpoints (restart TaskFlow API)
3. Task 3: NanoClaw trigger bypass + output routing (rebuild + restart)
4. Task 4: MCP tool (rebuild container image)
5. Task 5: Frontend (build + deploy)
6. Task 6: Agent docs
7. Task 7: E2E test

## Key Design Decisions

- **Direct messages.db write** (not IPC files) — IPC `messages/` dir is for OUTBOUND (agent→channel), not inbound. Writing to `messages.db` directly lets the polling loop pick up web chat messages the same way it picks up WhatsApp messages.
- **WAL mode on messages.db** — NanoClaw opens `messages.db` without WAL; the Python writer sets `PRAGMA journal_mode=WAL` and `busy_timeout=10000` for safe concurrent access.
- **Source marker `web:` prefix** on `sender` and `sender_name` — distinguishes web chat from WhatsApp. Agent output routing checks `missedMessages` (the `NewMessage[]` array, NOT `prompt` which is a string).
- **Output routing resolved before `runAgent()`** — `isWebOrigin` and `webChatBoardId` are computed once from the initial `missedMessages` and captured in the closure. This avoids stale-closure issues when piped follow-up messages arrive mid-session. Fallback to WhatsApp if board_chat write fails.
- **Trigger bypass** for `web:` messages in BOTH `processGroupMessages` (~line 465) and `startMessageLoop` (~line 751) — ensures agents always process web chat.
- **`resolveTaskflowBoardId(group.folder, true)`** for board ID lookup — uses existing function from `taskflow-db.ts`.
- **Consistent timestamps** — all `board_chat` writes use `strftime('%Y-%m-%d %H:%M:%S')` (SQLite) or `strftime('%Y-%m-%d %H:%M:%S')` (Python). No ISO timezone suffixes.
- **WebSocket** reuses existing pattern — `chat:new` events via discriminated union type. Broadcasts all boards to all clients (frontend filters by `boardId`). Acceptable for single-user deployment; add board_id subscription for multi-user.
- **Sender name from auth context** — uses board owner name from `board.people[0]`, not hardcoded.
- **No NanoClaw core schema changes** — `board_chat` is in `taskflow.db`, messages injection uses existing `messages.db` schema.
