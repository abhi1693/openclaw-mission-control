import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Accent = "blue" | "emerald" | "violet" | "amber";

const ACCENT_STYLES: Record<Accent, { icon: string; trend: string }> = {
  blue: {
    icon: "bg-blue-50 text-blue-600",
    trend: "text-blue-600",
  },
  emerald: {
    icon: "bg-emerald-50 text-emerald-600",
    trend: "text-emerald-600",
  },
  violet: {
    icon: "bg-violet-50 text-violet-600",
    trend: "text-violet-600",
  },
  amber: {
    icon: "bg-amber-50 text-amber-600",
    trend: "text-amber-600",
  },
};

export type StatCardProps = {
  title: string;
  value: string;
  trend?: string;
  trendDirection?: "up" | "down" | "flat";
  subtitle?: string;
  icon: ReactNode;
  accent?: Accent;
};

export function StatCard({
  title,
  value,
  trend,
  trendDirection = "up",
  subtitle,
  icon,
  accent = "blue",
}: StatCardProps) {
  const tone = ACCENT_STYLES[accent];

  return (
    <section className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            {title}
          </p>
          <p className="mt-2 font-heading text-3xl font-bold text-slate-900">
            {value}
          </p>
          {subtitle ? (
            <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
          ) : null}
        </div>
        <div
          className={cn(
            "grid h-10 w-10 shrink-0 place-items-center rounded-xl",
            tone.icon,
          )}
        >
          {icon}
        </div>
      </div>
      {trend ? (
        <div className="mt-4 flex items-center gap-2 text-xs">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium",
              trendDirection === "up" && "bg-emerald-50 text-emerald-700",
              trendDirection === "down" && "bg-rose-50 text-rose-700",
              trendDirection === "flat" && "bg-slate-100 text-slate-600",
            )}
          >
            {trendDirection === "up" ? "▲" : trendDirection === "down" ? "▼" : "▬"}
            {trend}
          </span>
          <span className="text-slate-500">vs last 7 days</span>
        </div>
      ) : null}
    </section>
  );
}
