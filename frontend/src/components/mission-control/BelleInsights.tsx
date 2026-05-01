import { Sparkles, AlertTriangle, TrendingUp, Info } from "lucide-react";

import { cn } from "@/lib/utils";
import type { BelleInsight } from "./mockTeam";

const TONE_STYLES: Record<BelleInsight["tone"], { icon: React.ElementType; chip: string; ring: string }> = {
  info: { icon: Info, chip: "bg-blue-50 text-blue-700", ring: "ring-blue-100" },
  warning: { icon: AlertTriangle, chip: "bg-amber-50 text-amber-700", ring: "ring-amber-100" },
  success: { icon: TrendingUp, chip: "bg-emerald-50 text-emerald-700", ring: "ring-emerald-100" },
};

export type BelleInsightsProps = {
  insights: BelleInsight[];
};

export function BelleInsights({ insights }: BelleInsightsProps) {
  return (
    <section className="flex h-full flex-col rounded-2xl border border-slate-200 bg-gradient-to-br from-fuchsia-50/60 via-white to-violet-50/40 shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-fuchsia-500 to-purple-600 text-white shadow-sm">
            <Sparkles className="h-4 w-4" />
          </span>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Belle Insights</h3>
            <p className="text-xs text-slate-500">
              What Belle is learning from the field this week.
            </p>
          </div>
        </div>
        <span className="rounded-full bg-purple-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-purple-700">
          Live
        </span>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {insights.map((insight) => {
          const tone = TONE_STYLES[insight.tone];
          const Icon = tone.icon;
          return (
            <article
              key={insight.id}
              className={cn(
                "rounded-xl border border-slate-200 bg-white/80 p-3 shadow-sm ring-1 backdrop-blur",
                tone.ring,
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                    tone.chip,
                  )}
                >
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900">{insight.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-slate-600">
                    {insight.detail}
                  </p>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      <footer className="border-t border-slate-100 px-5 py-3">
        <button
          type="button"
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800"
        >
          Ask Belle a question
        </button>
      </footer>
    </section>
  );
}
