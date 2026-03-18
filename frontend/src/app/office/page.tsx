"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Bot, Clock, Monitor, Zap } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListAgentsApiV1AgentsGet } from "@/api/generated/agents/agents";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { useListTasksApiV1BoardsBoardIdTasksGet } from "@/api/generated/tasks/tasks";
import { cn } from "@/lib/utils";

// Pixel art palette
const P = {
  floor: "#e8dcc8", floorTile: "#ddd0b8",
  wall: "#c4b5a0", wallTop: "#8b7d6b",
  desk: "#8B6914", deskTop: "#a07d1a",
  monitor: "#1e293b", screenOn: "#22d3ee", screenOff: "#475569",
  chair: "#374151", plant: "#16a34a", pot: "#92400e",
  body: "#6366f1", head: "#fbbf24",
  dotOn: "#22c55e", dotOff: "#94a3b8",
};

function rect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, c: string) {
  ctx.fillStyle = c;
  ctx.fillRect(Math.floor(x), Math.floor(y), Math.floor(w), Math.floor(h));
}

function drawDesk(ctx: CanvasRenderingContext2D, x: number, y: number, s: number) {
  rect(ctx, x, y + 8 * s, 32 * s, 4 * s, P.deskTop);
  rect(ctx, x + 2 * s, y + 12 * s, 28 * s, 10 * s, P.desk);
  rect(ctx, x + 4 * s, y + 22 * s, 3 * s, 6 * s, P.desk);
  rect(ctx, x + 25 * s, y + 22 * s, 3 * s, 6 * s, P.desk);
}

function drawMonitor(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, on: boolean) {
  rect(ctx, x + 8 * s, y - 2 * s, 16 * s, 12 * s, P.monitor);
  rect(ctx, x + 9 * s, y - 1 * s, 14 * s, 10 * s, on ? P.screenOn : P.screenOff);
  rect(ctx, x + 14 * s, y + 10 * s, 4 * s, 3 * s, P.monitor);
  rect(ctx, x + 12 * s, y + 13 * s, 8 * s, 2 * s, P.monitor);
  if (on) { ctx.fillStyle = "rgba(34,211,238,0.12)"; ctx.fillRect(x + 4 * s, y - 6 * s, 24 * s, 20 * s); }
}

function drawAgent(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, on: boolean, name: string) {
  rect(ctx, x + 10 * s, y + 16 * s, 12 * s, 3 * s, P.chair);
  rect(ctx, x + 11 * s, y + 19 * s, 10 * s, 8 * s, P.chair);
  rect(ctx, x + 12 * s, y + 27 * s, 3 * s, 3 * s, P.chair);
  rect(ctx, x + 17 * s, y + 27 * s, 3 * s, 3 * s, P.chair);
  if (on) {
    rect(ctx, x + 12 * s, y + 10 * s, 8 * s, 8 * s, P.body);
    rect(ctx, x + 13 * s, y + 4 * s, 6 * s, 6 * s, P.head);
    rect(ctx, x + 20 * s, y + 3 * s, 3 * s, 3 * s, P.dotOn);
  }
  ctx.fillStyle = on ? "#1e293b" : "#94a3b8";
  ctx.font = `${Math.max(9, 10 * s)}px monospace`;
  ctx.textAlign = "center";
  ctx.fillText(name.length > 8 ? name.slice(0, 7) + "…" : name, x + 16 * s, y + 36 * s);
}

function drawPlant(ctx: CanvasRenderingContext2D, x: number, y: number, s: number) {
  rect(ctx, x, y + 6 * s, 6 * s, 6 * s, P.pot);
  rect(ctx, x + 1 * s, y, 4 * s, 6 * s, P.plant);
  rect(ctx, x - 1 * s, y + 2 * s, 2 * s, 3 * s, P.plant);
  rect(ctx, x + 5 * s, y + 1 * s, 2 * s, 3 * s, P.plant);
}

type AgentInfo = {
  id: string;
  name: string;
  status: string;
  boardId: string | null;
  boardName: string;
  isLead: boolean;
  lastSeen: string | null;
  currentTask: string | null;
};

export default function OfficePage() {
  const { isSignedIn } = useAuth();
  useOrganizationMembership(isSignedIn);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const agentsQuery = useListAgentsApiV1AgentsGet(
    {},
    { query: { enabled: Boolean(isSignedIn), refetchInterval: 10_000 } },
  );
  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });

  const agents = agentsQuery.data?.data?.items ?? [];
  const boards = boardsQuery.data?.data?.items ?? [];
  const boardMap = new Map(boards.map((b: any) => [b.id, b]));

  // Fetch in-progress tasks for boards with active agents
  const activeBoardIds = [...new Set(agents.filter((a: any) => a.board_id).map((a: any) => a.board_id as string))].slice(0, 8);
  const taskQueries = activeBoardIds.map((boardId) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useListTasksApiV1BoardsBoardIdTasksGet(boardId, { status_filter: "in_progress" }, {
      query: { enabled: Boolean(isSignedIn) && Boolean(boardId) },
    }),
  );

  // Map agent_id -> current task title
  const agentTaskMap = useMemo(() => {
    const map = new Map<string, string>();
    taskQueries.forEach((q) => {
      const items = q.data?.data?.items ?? [];
      items.forEach((t: any) => {
        if (t.assigned_agent_id) map.set(t.assigned_agent_id, t.title);
      });
    });
    return map;
  }, [taskQueries.map((q) => q.dataUpdatedAt).join(",")]);

  const agentInfos: AgentInfo[] = useMemo(() => {
    return agents.map((a: any) => {
      const board = a.board_id ? boardMap.get(a.board_id) : null;
      return {
        id: a.id,
        name: a.name ?? "Agent",
        status: a.status ?? "retired",
        boardId: a.board_id ?? null,
        boardName: board ? (board as any).name : "Unassigned",
        isLead: a.is_board_lead ?? false,
        lastSeen: a.last_seen_at ?? null,
        currentTask: agentTaskMap.get(a.id) ?? null,
      };
    });
  }, [agents, boardMap, agentTaskMap]);

  // Canvas rendering
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const cols = 4;
    const rows = Math.max(1, Math.ceil(agentInfos.length / cols));
    const width = 560;
    const height = Math.max(300, rows * 130 + 80);
    const dpr = 2;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = P.floor;
    ctx.fillRect(0, 0, width, height);
    for (let tx = 0; tx < width; tx += 40)
      for (let ty = 0; ty < height; ty += 40)
        if ((tx / 40 + ty / 40) % 2 === 0) { ctx.fillStyle = P.floorTile; ctx.fillRect(tx, ty, 40, 40); }

    rect(ctx, 0, 0, width, 30, P.wall);
    rect(ctx, 0, 0, width, 8, P.wallTop);

    const s = 2;
    agentInfos.forEach((a, i) => {
      const x = (i % cols) * 130 + 30;
      const y = Math.floor(i / cols) * 130 + 50;
      const on = a.status === "active";
      drawDesk(ctx, x, y, s);
      drawMonitor(ctx, x, y, s, on);
      drawAgent(ctx, x, y, s, on, a.name);
    });

    if (agentInfos.length > 0) {
      drawPlant(ctx, 10, height - 28, s);
      drawPlant(ctx, width - 24, height - 28, s);
    }

    ctx.fillStyle = "#64748b";
    ctx.font = "bold 11px monospace";
    ctx.textAlign = "center";
    ctx.fillText("OPENCLAW HQ", width / 2, 20);
  }, [agentInfos]);

  const activeCount = agentInfos.filter((a) => a.status === "active").length;

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view the office.", forceRedirectUrl: "/office" }}
      title="Office"
      description="Visual agent monitor — see who's active and what they're working on."
      headerActions={
        <div className="flex items-center gap-3 text-sm">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-slate-600">{activeCount} active</span>
          </span>
          <span className="text-slate-300">|</span>
          <span className="text-slate-500">{agentInfos.length} total</span>
        </div>
      }
    >
      {/* Pixel art canvas */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        {agentInfos.length > 0 ? (
          <div className="flex justify-center">
            <canvas ref={canvasRef} className="rounded-lg border border-slate-100" style={{ imageRendering: "pixelated" }} />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20">
            <Monitor className="h-10 w-10 text-slate-300" />
            <p className="mt-3 text-sm font-medium text-slate-500">Office is empty</p>
            <p className="mt-1 text-xs text-slate-400">Create agents and they will appear at their desks.</p>
          </div>
        )}
      </div>

      {/* Agent detail cards — show what each agent is working on */}
      {agentInfos.length > 0 ? (
        <div className="mt-6">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Agent Status</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {agentInfos.map((a) => {
              const isActive = a.status === "active";
              return (
                <div key={a.id} className={cn(
                  "rounded-xl border p-4 transition",
                  isActive ? "border-emerald-200 bg-emerald-50/30" : "border-slate-200 bg-white",
                )}>
                  <div className="flex items-start gap-3">
                    <div className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold",
                      isActive ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400",
                    )}>
                      {a.name[0]?.toUpperCase() ?? "?"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-900 text-sm truncate">{a.name}</span>
                        {a.isLead ? <span className="text-[10px] font-semibold text-amber-600 bg-amber-50 px-1.5 rounded">LEAD</span> : null}
                        <span className={cn(
                          "h-2 w-2 rounded-full shrink-0",
                          isActive ? "bg-emerald-500" : "bg-slate-300",
                        )} />
                      </div>
                      <p className="text-xs text-slate-500 truncate mt-0.5">
                        {a.boardId ? (
                          <Link href={`/boards/${a.boardId}`} className="hover:text-blue-600 transition">
                            {a.boardName}
                          </Link>
                        ) : "Unassigned"}
                      </p>
                    </div>
                  </div>

                  {/* Current work */}
                  {isActive && a.currentTask ? (
                    <div className="mt-3 flex items-start gap-2 rounded-lg bg-white border border-emerald-100 px-3 py-2">
                      <Zap className="h-3.5 w-3.5 text-emerald-500 mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600">Working on</p>
                        <p className="text-xs text-slate-700 truncate">{a.currentTask}</p>
                      </div>
                    </div>
                  ) : isActive ? (
                    <div className="mt-3 flex items-center gap-2 text-xs text-emerald-600">
                      <Zap className="h-3.5 w-3.5" /> Active — awaiting tasks
                    </div>
                  ) : a.lastSeen ? (
                    <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
                      <Clock className="h-3.5 w-3.5" />
                      Last seen {new Date(a.lastSeen).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Legend */}
      <div className="mt-4 flex flex-wrap items-center gap-6 rounded-lg border border-slate-100 bg-white px-5 py-3">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Legend</span>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: P.screenOn }} /> Active (screen on)
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: P.screenOff }} /> Inactive (screen off)
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: P.dotOn }} /> Online indicator
        </div>
      </div>
    </DashboardPageLayout>
  );
}
