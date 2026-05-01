import {
  Code2,
  Phone,
  Rocket,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { ActivityItem } from "./mockTeam";

const KIND_ICON: Record<ActivityItem["kind"], React.ElementType> = {
  deploy: Rocket,
  approval: ShieldCheck,
  code: Code2,
  voice: Phone,
  alert: TriangleAlert,
};

const KIND_TONE: Record<ActivityItem["kind"], string> = {
  deploy: "bg-blue-50 text-blue-600",
  approval: "bg-emerald-50 text-emerald-600",
  code: "bg-violet-50 text-violet-600",
  voice: "bg-fuchsia-50 text-fuchsia-600",
  alert: "bg-amber-50 text-amber-600",
};

export type RecentActivityProps = {
  items: ActivityItem[];
};

export function RecentActivity({ items }: RecentActivityProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Recent Activity</h3>
          <p className="text-xs text-slate-500">
            Pulse from agents, Belle, and the production stack.
          </p>
        </div>
      </header>
      <ul className="divide-y divide-slate-100">
        {items.map((item) => {
          const Icon = KIND_ICON[item.kind];
          return (
            <li key={item.id} className="flex items-start gap-3 px-5 py-3">
              <span
                className={cn(
                  "mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                  KIND_TONE[item.kind],
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-slate-800">
                  <span
                    className={cn(
                      "mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full bg-gradient-to-br text-[10px] font-semibold text-white",
                      item.agentAccent,
                    )}
                  >
                    {item.agent
                      .split(" ")
                      .slice(0, 2)
                      .map((part) => part[0])
                      .join("")
                      .toUpperCase()}
                  </span>
                  <span className="font-medium text-slate-900">{item.agent}</span>{" "}
                  <span className="text-slate-700">{item.message}</span>
                </p>
                <p className="mt-0.5 text-[11px] text-slate-500">{item.time}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
