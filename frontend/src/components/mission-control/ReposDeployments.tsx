import { GitBranch, ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";
import type { RepoDeployment } from "./mockTeam";

const STATUS_STYLES: Record<RepoDeployment["status"], string> = {
  deployed: "bg-emerald-50 text-emerald-700",
  deploying: "bg-blue-50 text-blue-700 animate-pulse",
  failed: "bg-rose-50 text-rose-700",
  queued: "bg-slate-100 text-slate-600",
};

const STATUS_LABEL: Record<RepoDeployment["status"], string> = {
  deployed: "Deployed",
  deploying: "Deploying",
  failed: "Failed",
  queued: "Queued",
};

export type ReposDeploymentsProps = {
  items: RepoDeployment[];
};

export function ReposDeployments({ items }: ReposDeploymentsProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Repos &amp; Deployments</h3>
          <p className="text-xs text-slate-500">Latest pushes across the Simple Pro stack.</p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 transition hover:text-slate-700"
        >
          View all
          <ArrowUpRight className="h-3.5 w-3.5" />
        </button>
      </header>
      <ul className="divide-y divide-slate-100">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex items-center justify-between gap-3 px-5 py-3 transition hover:bg-slate-50"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-900">{item.repo}</p>
              <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                <GitBranch className="h-3 w-3" />
                <span className="truncate">{item.branch}</span>
                <span>·</span>
                <span>{item.env}</span>
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <div className="text-right">
                <span
                  className={cn(
                    "inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium",
                    STATUS_STYLES[item.status],
                  )}
                >
                  {STATUS_LABEL[item.status]}
                </span>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  {item.lastDeploy} · {item.by}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
