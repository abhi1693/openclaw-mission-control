"use client";

import { GitBranch, PauseCircle, PlayCircle, ShieldAlert, UserRound } from "lucide-react";

import type { WorkflowRunSummary } from "@/api/generated/model";
import { cn } from "@/lib/utils";

const statusTone = (status: WorkflowRunSummary["status"]) => {
  switch (status) {
    case "running":
      return "border-violet-200 bg-violet-50 text-violet-700";
    case "waiting_human":
      return "border-amber-200 bg-amber-50 text-amber-700";
    case "waiting_approval":
      return "border-cyan-200 bg-cyan-50 text-cyan-700";
    case "blocked":
      return "border-rose-200 bg-rose-50 text-rose-700";
    case "completed":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
    case "failed":
      return "border-rose-200 bg-rose-50 text-rose-700";
    case "canceled":
      return "border-slate-300 bg-slate-100 text-slate-700";
    default:
      return "border-slate-200 bg-slate-100 text-slate-700";
  }
};

const statusLabel = (status: WorkflowRunSummary["status"]) =>
  status.replace(/_/g, " ");

type WorkflowRunsPanelProps = {
  runs: WorkflowRunSummary[];
};

export function WorkflowRunsPanel({ runs }: WorkflowRunsPanelProps) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-900">Workflow runs</p>
            <p className="text-xs text-slate-500">
              First-class workflow state for this board.
            </p>
          </div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
            {runs.length} total
          </div>
        </div>
      </div>

      {runs.length === 0 ? (
        <div className="px-5 py-8 text-sm text-slate-500">
          No workflow runs yet.
        </div>
      ) : (
        <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
          {runs.map((run) => (
            <article
              key={run.id}
              className="rounded-xl border border-slate-200 bg-slate-50/50 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-900">
                    {run.title}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Current step: {run.current_step_key ?? "—"}
                  </p>
                </div>
                <span
                  className={cn(
                    "rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                    statusTone(run.status),
                  )}
                >
                  {statusLabel(run.status)}
                </span>
              </div>

              <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-600">
                <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
                  <PauseCircle className="h-3.5 w-3.5" />
                  Waiting {run.waiting_step_count ?? 0}
                </span>
                <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  Approvals {run.approval_step_count ?? 0}
                </span>
                <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
                  <UserRound className="h-3.5 w-3.5" />
                  Human {run.human_step_count ?? 0}
                </span>
              </div>

              <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
                <span className="inline-flex items-center gap-1">
                  <GitBranch className="h-3.5 w-3.5" />
                  {run.source_task_id ? "Linked to task" : "No task link"}
                </span>
                <span className="inline-flex items-center gap-1">
                  <PlayCircle className="h-3.5 w-3.5" />
                  Updated {new Date(run.updated_at).toLocaleDateString()}
                </span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
