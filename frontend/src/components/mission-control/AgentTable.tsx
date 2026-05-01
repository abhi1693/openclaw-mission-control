import { MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AgentStatus, SimpleProAgent } from "./mockTeam";

const STATUS_STYLES: Record<AgentStatus, { dot: string; chip: string; label: string }> = {
  active: {
    dot: "bg-emerald-500",
    chip: "bg-emerald-50 text-emerald-700",
    label: "Active",
  },
  idle: {
    dot: "bg-slate-400",
    chip: "bg-slate-100 text-slate-600",
    label: "Idle",
  },
  review: {
    dot: "bg-violet-500",
    chip: "bg-violet-50 text-violet-700",
    label: "In review",
  },
  blocked: {
    dot: "bg-rose-500",
    chip: "bg-rose-50 text-rose-700",
    label: "Blocked",
  },
  offline: {
    dot: "bg-slate-300",
    chip: "bg-slate-100 text-slate-500",
    label: "Offline",
  },
};

export type AgentTableProps = {
  agents: SimpleProAgent[];
};

export function AgentTable({ agents }: AgentTableProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">AI Agents</h3>
          <p className="text-xs text-slate-500">
            Live roster of the Simple Pro AI team and what they&apos;re working on.
          </p>
        </div>
        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
          {agents.length} agents
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              <th className="px-5 py-3">Agent</th>
              <th className="px-3 py-3">Platform</th>
              <th className="px-3 py-3">Current task</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3 w-44">Progress</th>
              <th className="px-3 py-3">Last activity</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {agents.map((agent) => {
              const status = STATUS_STYLES[agent.status];
              return (
                <tr key={agent.id} className="transition hover:bg-slate-50">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div
                        className={cn(
                          "grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-xs font-semibold text-white shadow-sm",
                          agent.accent,
                        )}
                      >
                        {agent.initials}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-900">
                          {agent.name}
                        </p>
                        <p className="truncate text-xs text-slate-500">{agent.role}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="font-medium text-slate-800">{agent.platform}</p>
                    <p className="text-xs text-slate-500">{agent.model}</p>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="max-w-[280px] truncate text-slate-700" title={agent.currentTask}>
                      {agent.currentTask}
                    </p>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
                        status.chip,
                      )}
                    >
                      <span className={cn("h-1.5 w-1.5 rounded-full", status.dot)} />
                      {status.label}
                    </span>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-full max-w-[120px] rounded-full bg-slate-100">
                        <div
                          className={cn(
                            "h-1.5 rounded-full bg-gradient-to-r",
                            agent.accent,
                          )}
                          style={{ width: `${Math.max(4, Math.min(100, agent.progress))}%` }}
                        />
                      </div>
                      <span className="w-9 text-right text-xs font-medium text-slate-600">
                        {agent.progress}%
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-3 align-top text-xs text-slate-500">
                    {agent.lastActivity}
                  </td>
                  <td className="px-5 py-3 text-right align-top">
                    <button
                      type="button"
                      className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                      aria-label={`Actions for ${agent.name}`}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
