// Standalone smoke test for mc-bootstrap-context handler. No pytest /
// vitest harness — runs as `node handler.test.mjs` from the plugin dir
// or any cwd. Covers the pure logic (agent-id inference, role split,
// markdown rendering, per-agent token reading) and exercises the
// handler's side-effect contract against a stub gateway-event payload.
//
// Per project memory feedback_tdd_discipline: this test file expresses
// the contract the handler MUST satisfy. The handler is allowed to
// change so long as these assertions still pass.

import handler from "./handler.js";
import http from "node:http";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

let passed = 0;
let failed = 0;

function expect(label, actual, predicate) {
  const ok = typeof predicate === "function" ? predicate(actual) : actual === predicate;
  if (ok) {
    passed++;
    return;
  }
  failed++;
  console.error(`FAIL: ${label}\n  got: ${JSON.stringify(actual)?.slice(0, 200)}`);
}

// Build a synthetic agent:bootstrap event matching the gateway contract.
// `cfg` is the gateway config snapshot the handler walks for env.
function makeBootstrapEvent({ agentId, sessionKey, env, workspaceDir }) {
  return {
    type: "agent",
    action: "bootstrap",
    sessionKey: sessionKey ?? `agent:${agentId}:session`,
    timestamp: Date.now(),
    messages: [],
    context: {
      sessionKey: sessionKey ?? `agent:${agentId}:session`,
      workspaceDir: workspaceDir ?? `/root/.openclaw/agents/${agentId}`,
      bootstrapFiles: [],
      cfg: {
        hooks: {
          internal: {
            entries: {
              "mc-bootstrap-context": { enabled: true, env },
            },
          },
        },
      },
    },
  };
}

// Spin a temp dir with a workspace-<openclawAgentId>/TOOLS.md file
// holding the AUTH_TOKEN and AGENT_ID lines the handler expects. The
// `mcAgentId` is the MC `agents.id` UUID (no `mc-`/`lead-` prefix) —
// it differs from the OpenClaw agent ID for both lead and worker
// agents. Returns the WORKSPACE_ROOT path.
async function makeTempWorkspaceWithToolsMd(openclawAgentId, token, mcAgentId) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "mc-bootstrap-test-"));
  const wsDir = path.join(root, `workspace-${openclawAgentId}`);
  await fs.mkdir(wsDir, { recursive: true });
  const toolsContent = [
    "# TOOLS.md",
    "",
    "- `BASE_URL=http://test:8000`",
    `- \`AUTH_TOKEN=${token}\``,
    `- \`AGENT_ID=${mcAgentId ?? openclawAgentId}\``,
    "",
  ].join("\n");
  await fs.writeFile(path.join(wsDir, "TOOLS.md"), toolsContent);
  return root;
}

// HTTP stub that captures request headers/url and returns a configured body/status.
async function withStubServer(handlerFn, body, status = 200) {
  return await new Promise((resolve, reject) => {
    const captured = { headers: null, url: null, method: null };
    const server = http.createServer((req, res) => {
      captured.headers = req.headers;
      captured.url = req.url;
      captured.method = req.method;
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(typeof body === "string" ? body : JSON.stringify(body));
    });
    server.listen(0, "127.0.0.1", async () => {
      const addr = server.address();
      try {
        const result = await handlerFn(`http://127.0.0.1:${addr.port}`, captured);
        server.close(() => resolve(result));
      } catch (err) {
        server.close(() => reject(err));
      }
    });
  });
}

const TOK = "test-agent-token-abc123";

// --- 1. ignores non-bootstrap events
{
  const ev = makeBootstrapEvent({
    agentId: "lead-x",
    env: { MC_BASE_URL: "http://x", BOARD_ID: "b" },
  });
  ev.type = "command";
  ev.action = "new";
  await handler(ev);
  expect("non-bootstrap event leaves bootstrapFiles untouched", ev.context.bootstrapFiles.length, 0);
}

// --- 2. ignores non-MC agents
{
  for (const id of ["main", "repro-test-agent", "eval-lead-050", "mc-gateway-3821a85a"]) {
    const ev = makeBootstrapEvent({
      agentId: id,
      env: { MC_BASE_URL: "http://x", BOARD_ID: "b" },
    });
    await handler(ev);
    expect(`non-MC agent ${id} leaves bootstrapFiles empty`, ev.context.bootstrapFiles.length, 0);
  }
}

// --- 3. missing config → no-op
{
  const ev = makeBootstrapEvent({
    agentId: "lead-x",
    env: undefined,
  });
  ev.context.cfg = { hooks: { internal: { entries: {} } } };
  await handler(ev);
  expect("missing config is a clean no-op", ev.context.bootstrapFiles.length, 0);
}

// --- 4. lead bootstrap with token from TOOLS.md → injects MC_RUNTIME_BRIEF.md
{
  const agentId = "lead-test1234";
  const mcAgentId = "11111111-2222-3333-4444-555555555555";
  const wsRoot = await makeTempWorkspaceWithToolsMd(agentId, TOK, mcAgentId);
  await withStubServer(
    async (baseUrl, captured) => {
      const ev = makeBootstrapEvent({
        agentId,
        env: { MC_BASE_URL: baseUrl, BOARD_ID: "b", WORKSPACE_ROOT: wsRoot, TIMEOUT_MS: "1500" },
      });
      await handler(ev);
      const f = ev.context.bootstrapFiles[0];
      expect("lead injection produces one file", ev.context.bootstrapFiles.length, 1);
      expect("lead file is MC_RUNTIME_BRIEF.md", f?.name, "MC_RUNTIME_BRIEF.md");
      expect("lead file content is markdown lead brief", f?.content, (s) => typeof s === "string" && s.startsWith("# MC Runtime Brief — Lead"));
      expect("lead file content surfaces action", f?.content, (s) => s.includes("inspect_review_gates"));

      // ── New T5/T6 contracts ──
      expect("request used X-Agent-Token header (not Bearer)", captured.headers, (h) => h?.["x-agent-token"] === TOK);
      expect("request URL hit /api/v1/agent/boards/.../lead/next-action", captured.url, (u) => typeof u === "string" && u.includes("/api/v1/agent/boards/b/lead/next-action"));
    },
    {
      action: "inspect_review_gates",
      reason_code: "approved_review_needs_done_gate",
      action_required: true,
      task_id: "c611f081",
      task_title: "Bug: agents.update RPC wipes",
    },
  );
  await fs.rm(wsRoot, { recursive: true, force: true });
}

// --- 5. worker bootstrap with token from TOOLS.md → injects task table
//
// MC's /agent/boards/.../tasks?assigned_agent_id=<uuid> endpoint
// validates the query param as a UUID. The OpenClaw agent ID
// (`mc-<uuid>`) carries a prefix and is rejected (HTTP 422). The
// MC `agents.id` UUID lives in TOOLS.md as `AGENT_ID=<bare-uuid>`
// alongside the AUTH_TOKEN, and that's what the URL must use.
{
  const openclawAgentId = "mc-test1234abcd";
  const mcAgentId = "abcd1234-5678-9012-3456-7890abcdefab";
  const wsRoot = await makeTempWorkspaceWithToolsMd(openclawAgentId, TOK, mcAgentId);
  await withStubServer(
    async (baseUrl, captured) => {
      const ev = makeBootstrapEvent({
        agentId: openclawAgentId,
        env: { MC_BASE_URL: baseUrl, BOARD_ID: "b", WORKSPACE_ROOT: wsRoot, TIMEOUT_MS: "1500" },
      });
      await handler(ev);
      const f = ev.context.bootstrapFiles[0];
      expect("worker injection produces one file", ev.context.bootstrapFiles.length, 1);
      expect("worker file content has worker brief header", f?.content, (s) => typeof s === "string" && s.startsWith("# MC Runtime Brief — Worker"));
      expect("worker file content lists task title", f?.content, (s) => s.includes("Implement nav active state"));
      expect("worker file content shows task count", f?.content, (s) => s.includes("**2** task(s)"));

      // X-Agent-Token + URL uses MC UUID (not OpenClaw agent ID).
      expect("worker request used X-Agent-Token", captured.headers, (h) => h?.["x-agent-token"] === TOK);
      expect("worker URL uses MC UUID from TOOLS.md, not OpenClaw agent id", captured.url, (u) => typeof u === "string" && u.includes(`/api/v1/agent/boards/b/tasks?assigned_agent_id=${mcAgentId}`));
      expect("worker URL does NOT contain mc- prefix", captured.url, (u) => typeof u === "string" && !u.includes("assigned_agent_id=mc-"));
    },
    {
      items: [
        { id: "abc12345-aaaa-bbbb-cccc-dddddddddddd", title: "Implement nav active state", status: "in_progress", priority: "high" },
        { id: "def67890-aaaa-bbbb-cccc-dddddddddddd", title: "Fix locale gap", status: "review", priority: "medium" },
      ],
      total: 2,
    },
  );
  await fs.rm(wsRoot, { recursive: true, force: true });
}

// --- 5b. worker without AGENT_ID in TOOLS.md → no-op (can't build a
// valid query without the MC UUID)
{
  const openclawAgentId = "mc-noagentid12";
  const wsRoot = await fs.mkdtemp(path.join(os.tmpdir(), "mc-bootstrap-test-"));
  const wsDir = path.join(wsRoot, `workspace-${openclawAgentId}`);
  await fs.mkdir(wsDir, { recursive: true });
  await fs.writeFile(
    path.join(wsDir, "TOOLS.md"),
    `# TOOLS.md\n\n- \`AUTH_TOKEN=${TOK}\`\n`,
  );
  const ev = makeBootstrapEvent({
    agentId: openclawAgentId,
    env: { MC_BASE_URL: "http://unreachable.invalid", BOARD_ID: "b", WORKSPACE_ROOT: wsRoot },
  });
  await handler(ev);
  expect("worker without AGENT_ID is a clean no-op", ev.context.bootstrapFiles.length, 0);
  await fs.rm(wsRoot, { recursive: true, force: true });
}

// --- 6. HTTP error → no injection, no throw
{
  const agentId = "lead-err1234";
  const wsRoot = await makeTempWorkspaceWithToolsMd(agentId, TOK);
  await withStubServer(
    async (baseUrl) => {
      const ev = makeBootstrapEvent({
        agentId,
        env: { MC_BASE_URL: baseUrl, BOARD_ID: "b", WORKSPACE_ROOT: wsRoot, TIMEOUT_MS: "1500" },
      });
      await handler(ev);
      expect("HTTP 500 does not inject", ev.context.bootstrapFiles.length, 0);
    },
    "internal error",
    500,
  );
  await fs.rm(wsRoot, { recursive: true, force: true });
}

// --- 7. missing TOOLS.md → no-op (no throw, no injection)
{
  const agentId = "lead-notools999";
  const wsRoot = await fs.mkdtemp(path.join(os.tmpdir(), "mc-bootstrap-test-"));
  // intentionally no workspace-<id>/TOOLS.md created
  const ev = makeBootstrapEvent({
    agentId,
    env: { MC_BASE_URL: "http://unreachable.invalid", BOARD_ID: "b", WORKSPACE_ROOT: wsRoot },
  });
  await handler(ev);
  expect("missing TOOLS.md is a clean no-op", ev.context.bootstrapFiles.length, 0);
  await fs.rm(wsRoot, { recursive: true, force: true });
}

// --- 8. TOOLS.md without AUTH_TOKEN line → no-op
{
  const agentId = "lead-notoken888";
  const wsRoot = await fs.mkdtemp(path.join(os.tmpdir(), "mc-bootstrap-test-"));
  const wsDir = path.join(wsRoot, `workspace-${agentId}`);
  await fs.mkdir(wsDir, { recursive: true });
  await fs.writeFile(path.join(wsDir, "TOOLS.md"), "# TOOLS.md\n\n- `BASE_URL=http://x`\n");
  const ev = makeBootstrapEvent({
    agentId,
    env: { MC_BASE_URL: "http://unreachable.invalid", BOARD_ID: "b", WORKSPACE_ROOT: wsRoot },
  });
  await handler(ev);
  expect("TOOLS.md without AUTH_TOKEN is a clean no-op", ev.context.bootstrapFiles.length, 0);
  await fs.rm(wsRoot, { recursive: true, force: true });
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
