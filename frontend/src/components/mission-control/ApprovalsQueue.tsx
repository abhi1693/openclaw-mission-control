import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ApprovalItem } from "./mockTeam";

const RISK_TONE: Record<ApprovalItem["risk"], string> = {
  low: "bg-emerald-50 text-emerald-700",
  medium: "bg-amber-50 text-amber-700",
  high: "bg-rose-50 text-rose-700",
};

const RISK_LABEL: Record<ApprovalItem["risk"], string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
};

export type ApprovalsQueueProps = {
  items: ApprovalItem[];
};

export function ApprovalsQueue({ items }: ApprovalsQueueProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Approvals Queue</h3>
          <p className="text-xs text-slate-500">
            Decisions waiting on a human before agents can proceed.
          </p>
        </div>
        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-700">
          {items.length} pending
        </span>
      </header>
      <ul className="divide-y divide-slate-100">
        {items.map((item) => (
          <li key={item.id} className="px-5 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">{item.title}</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {item.agent} · {item.scope} · {item.raised}
                </p>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                  RISK_TONE[item.risk],
                )}
              >
                {RISK_LABEL[item.risk]}
              </span>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-emerald-700"
              >
                <Check className="h-3 w-3" />
                Approve
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
              >
                <X className="h-3 w-3" />
                Reject
              </button>
              <button
                type="button"
                className="ml-auto text-xs font-medium text-slate-500 transition hover:text-slate-700"
              >
                View context
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
