"use client";

import { useEffect, useMemo, useRef } from "react";
import { Monitor } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListAgentsApiV1AgentsGet } from "@/api/generated/agents/agents";

// Pixel art colors
const PALETTE = {
  floor: "#e8dcc8",
  floorTile: "#ddd0b8",
  wall: "#c4b5a0",
  wallTop: "#8b7d6b",
  desk: "#8B6914",
  deskTop: "#a07d1a",
  monitor: "#1e293b",
  monitorScreen: "#22d3ee",
  monitorScreenOff: "#475569",
  chair: "#374151",
  plant: "#16a34a",
  plantPot: "#92400e",
  agentBody: "#6366f1",
  agentHead: "#fbbf24",
  agentActive: "#22c55e",
  agentInactive: "#94a3b8",
};

type AgentDesk = {
  name: string;
  status: string;
  x: number;
  y: number;
};

function drawPixelRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  color: string,
) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.floor(x), Math.floor(y), Math.floor(w), Math.floor(h));
}

function drawDesk(ctx: CanvasRenderingContext2D, x: number, y: number, scale: number) {
  const s = scale;
  // Desk body
  drawPixelRect(ctx, x, y + 8 * s, 32 * s, 4 * s, PALETTE.deskTop);
  drawPixelRect(ctx, x + 2 * s, y + 12 * s, 28 * s, 10 * s, PALETTE.desk);
  // Desk legs
  drawPixelRect(ctx, x + 4 * s, y + 22 * s, 3 * s, 6 * s, PALETTE.desk);
  drawPixelRect(ctx, x + 25 * s, y + 22 * s, 3 * s, 6 * s, PALETTE.desk);
}

function drawMonitor(ctx: CanvasRenderingContext2D, x: number, y: number, scale: number, isOn: boolean) {
  const s = scale;
  // Monitor body
  drawPixelRect(ctx, x + 8 * s, y - 2 * s, 16 * s, 12 * s, PALETTE.monitor);
  // Screen
  drawPixelRect(ctx, x + 9 * s, y - 1 * s, 14 * s, 10 * s, isOn ? PALETTE.monitorScreen : PALETTE.monitorScreenOff);
  // Stand
  drawPixelRect(ctx, x + 14 * s, y + 10 * s, 4 * s, 3 * s, PALETTE.monitor);
  drawPixelRect(ctx, x + 12 * s, y + 13 * s, 8 * s, 2 * s, PALETTE.monitor);

  // Glow effect when on
  if (isOn) {
    ctx.fillStyle = "rgba(34, 211, 238, 0.15)";
    ctx.fillRect(x + 4 * s, y - 6 * s, 24 * s, 20 * s);
  }
}

function drawAgent(ctx: CanvasRenderingContext2D, x: number, y: number, scale: number, isActive: boolean, name: string) {
  const s = scale;
  // Chair
  drawPixelRect(ctx, x + 10 * s, y + 16 * s, 12 * s, 3 * s, PALETTE.chair);
  drawPixelRect(ctx, x + 11 * s, y + 19 * s, 10 * s, 8 * s, PALETTE.chair);
  drawPixelRect(ctx, x + 12 * s, y + 27 * s, 3 * s, 3 * s, PALETTE.chair);
  drawPixelRect(ctx, x + 17 * s, y + 27 * s, 3 * s, 3 * s, PALETTE.chair);

  if (isActive) {
    // Body
    drawPixelRect(ctx, x + 12 * s, y + 10 * s, 8 * s, 8 * s, PALETTE.agentBody);
    // Head
    drawPixelRect(ctx, x + 13 * s, y + 4 * s, 6 * s, 6 * s, PALETTE.agentHead);
    // Status dot
    drawPixelRect(ctx, x + 20 * s, y + 3 * s, 3 * s, 3 * s, PALETTE.agentActive);
  }

  // Name label
  ctx.fillStyle = isActive ? "#1e293b" : "#94a3b8";
  ctx.font = `${Math.max(9, 10 * s)}px monospace`;
  ctx.textAlign = "center";
  const displayName = name.length > 8 ? name.slice(0, 7) + "…" : name;
  ctx.fillText(displayName, x + 16 * s, y + 36 * s);
}

function drawPlant(ctx: CanvasRenderingContext2D, x: number, y: number, scale: number) {
  const s = scale;
  // Pot
  drawPixelRect(ctx, x, y + 6 * s, 6 * s, 6 * s, PALETTE.plantPot);
  // Plant
  drawPixelRect(ctx, x + 1 * s, y, 4 * s, 6 * s, PALETTE.plant);
  drawPixelRect(ctx, x - 1 * s, y + 2 * s, 2 * s, 3 * s, PALETTE.plant);
  drawPixelRect(ctx, x + 5 * s, y + 1 * s, 2 * s, 3 * s, PALETTE.plant);
}

export default function OfficePage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const agentsQuery = useListAgentsApiV1AgentsGet(
    {},
    { query: { enabled: Boolean(isSignedIn), refetchInterval: 10_000 } },
  );

  const agents = agentsQuery.data?.data?.items ?? [];

  const agentDesks: AgentDesk[] = useMemo(() => {
    return agents.map((agent: any, i: number) => ({
      name: agent.name ?? `Agent ${i + 1}`,
      status: agent.status ?? "retired",
      x: (i % 4) * 120 + 40,
      y: Math.floor(i / 4) * 130 + 60,
    }));
  }, [agents]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rows = Math.max(1, Math.ceil(agents.length / 4));
    const width = 560;
    const height = Math.max(300, rows * 130 + 100);
    const scale = 2;

    canvas.width = width * scale;
    canvas.height = height * scale;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(scale, scale);

    // Clear
    ctx.fillStyle = PALETTE.floor;
    ctx.fillRect(0, 0, width, height);

    // Floor tiles
    for (let tx = 0; tx < width; tx += 40) {
      for (let ty = 0; ty < height; ty += 40) {
        if ((tx / 40 + ty / 40) % 2 === 0) {
          ctx.fillStyle = PALETTE.floorTile;
          ctx.fillRect(tx, ty, 40, 40);
        }
      }
    }

    // Wall
    drawPixelRect(ctx, 0, 0, width, 30, PALETTE.wall);
    drawPixelRect(ctx, 0, 0, width, 8, PALETTE.wallTop);

    const s = 2;

    // Draw desks and agents
    agentDesks.forEach((desk) => {
      const isActive = desk.status === "active";
      drawDesk(ctx, desk.x, desk.y, s);
      drawMonitor(ctx, desk.x, desk.y, s, isActive);
      drawAgent(ctx, desk.x, desk.y, s, isActive, desk.name);
    });

    // Decorative plants
    if (agentDesks.length > 0) {
      drawPlant(ctx, 16, height - 30, s);
      drawPlant(ctx, width - 28, height - 30, s);
    }

    // Title text
    ctx.fillStyle = "#64748b";
    ctx.font = "bold 11px monospace";
    ctx.textAlign = "center";
    ctx.fillText("OPENCLAW HQ", width / 2, 20);

  }, [agentDesks, agents.length]);

  const activeCount = agents.filter((a: any) => a.status === "active").length;

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view the office.", forceRedirectUrl: "/office" }}
      title="Office"
      description="A visual overview of your agents at work."
      headerActions={
        <div className="flex items-center gap-3 text-sm">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span className="text-slate-600">{activeCount} active</span>
          </span>
          <span className="text-slate-300">|</span>
          <span className="text-slate-500">{agents.length} total</span>
        </div>
      }
    >
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        {agents.length > 0 ? (
          <div className="flex justify-center">
            <canvas
              ref={canvasRef}
              className="rounded-lg border border-slate-100"
              style={{ imageRendering: "pixelated" }}
            />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20">
            <Monitor className="h-10 w-10 text-slate-300" />
            <p className="mt-3 text-sm font-medium text-slate-500">Office is empty</p>
            <p className="mt-1 text-xs text-slate-400">
              Create agents and they will appear at their desks here.
            </p>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="mt-4 flex flex-wrap items-center gap-6 rounded-lg border border-slate-100 bg-white px-5 py-3">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Legend</span>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: PALETTE.monitorScreen }} />
          Active (screen on)
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: PALETTE.monitorScreenOff }} />
          Inactive (screen off)
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: PALETTE.agentActive }} />
          Online indicator
        </div>
      </div>
    </DashboardPageLayout>
  );
}
