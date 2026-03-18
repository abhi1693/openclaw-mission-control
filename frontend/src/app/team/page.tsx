"use client";

import { Bot, Crown, Edit3, Shield, Users, Zap } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListAgentsApiV1AgentsGet } from "@/api/generated/agents/agents";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { cn } from "@/lib/utils";

const ROLE_ICONS: Record<string, typeof Bot> = {
  lead: Crown,
  worker: Zap,
  default: Bot,
};

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700 border-emerald-200",
  provisioning: "bg-blue-100 text-blue-700 border-blue-200",
  paused: "bg-amber-100 text-amber-700 border-amber-200",
  retired: "bg-slate-100 text-slate-500 border-slate-200",
};

export default function TeamPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const agentsQuery = useListAgentsApiV1AgentsGet(
    {},
    { query: { enabled: Boolean(isSignedIn), refetchInterval: 15_000 } },
  );

  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });

  const agents = agentsQuery.data?.data?.items ?? [];
  const boards = boardsQuery.data?.data?.items ?? [];

  const boardMap = new Map(boards.map((b: any) => [b.id, b]));

  const leadAgents = agents.filter((a: any) => a.is_board_lead);
  const workerAgents = agents.filter((a: any) => !a.is_board_lead);

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view your team.", forceRedirectUrl: "/team" }}
      title="Team"
      description="Your AI organization structure, sub-agents, and mission."
    >
      {/* Mission Statement */}
      <div className="mb-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-violet-600">
              <Shield className="h-5 w-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Mission Statement</h2>
              <p className="text-xs text-slate-500">The core directive for your AI organization</p>
            </div>
          </div>
          <button className="rounded-lg p-2 text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition">
            <Edit3 className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-4 rounded-lg border border-slate-100 bg-slate-50 p-4">
          <p className="text-sm text-slate-700 italic leading-relaxed">
            Autonomously assist in research, development, and operations. Maintain clear communication,
            proactively identify opportunities, and complete tasks with minimal supervision while
            upholding quality standards.
          </p>
        </div>
      </div>

      {/* Org chart */}
      <div className="mb-6 flex items-center gap-2">
        <Users className="h-5 w-5 text-slate-400" />
        <h2 className="text-base font-semibold text-slate-900">
          Organization ({agents.length} agent{agents.length !== 1 ? "s" : ""})
        </h2>
      </div>

      {/* You (Human) */}
      <div className="mb-6">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-1">
          Human Operator
        </p>
        <div className="rounded-xl border-2 border-blue-200 bg-blue-50/50 p-5">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-lg font-bold text-white">
              You
            </div>
            <div>
              <p className="font-semibold text-slate-900">You</p>
              <p className="text-xs text-slate-500">Owner & operator — reviews approvals, sets direction</p>
            </div>
          </div>
        </div>
      </div>

      {/* Lead agents */}
      {leadAgents.length > 0 ? (
        <div className="mb-6">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-1">
            Lead Agents
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {leadAgents.map((agent: any) => {
              const board = agent.board_id ? boardMap.get(agent.board_id) : null;
              const statusStyle = STATUS_STYLES[agent.status] ?? STATUS_STYLES.retired;
              return (
                <div key={agent.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 text-lg">
                      {agent.name?.[0]?.toUpperCase() ?? "?"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-semibold text-slate-900 truncate">{agent.name}</p>
                        <Crown className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                      </div>
                      <p className="text-xs text-slate-500 truncate">
                        {board ? `Lead of ${(board as any).name}` : "Unassigned lead"}
                      </p>
                    </div>
                    <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold", statusStyle)}>
                      {agent.status}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Worker agents */}
      {workerAgents.length > 0 ? (
        <div className="mb-6">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-1">
            Worker Agents
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {workerAgents.map((agent: any) => {
              const board = agent.board_id ? boardMap.get(agent.board_id) : null;
              const statusStyle = STATUS_STYLES[agent.status] ?? STATUS_STYLES.retired;
              return (
                <div key={agent.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg">
                      {agent.name?.[0]?.toUpperCase() ?? "?"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-slate-900 truncate">{agent.name}</p>
                      <p className="text-xs text-slate-500 truncate">
                        {board ? `Working on ${(board as any).name}` : "Unassigned"}
                      </p>
                    </div>
                    <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold", statusStyle)}>
                      {agent.status}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {agents.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-16">
          <Bot className="h-10 w-10 text-slate-300" />
          <p className="mt-3 text-sm font-medium text-slate-500">No agents yet</p>
          <p className="mt-1 text-xs text-slate-400">
            Connect a gateway and create agents to build your team.
          </p>
        </div>
      ) : null}
    </DashboardPageLayout>
  );
}
