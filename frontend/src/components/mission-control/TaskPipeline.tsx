import { Plus } from "lucide-react";

import { cn } from "@/lib/utils";
import type { PipelineCard, PipelineColumn } from "./mockTeam";

const TAG_TONES: Record<PipelineCard["tagTone"], string> = {
  blue: "bg-blue-50 text-blue-700",
  violet: "bg-violet-50 text-violet-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  rose: "bg-rose-50 text-rose-700",
  slate: "bg-slate-100 text-slate-600",
};

export type TaskPipelineProps = {
  columns: PipelineColumn[];
};

export function TaskPipeline({ columns }: TaskPipelineProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Task Pipeline</h3>
          <p className="text-xs text-slate-500">
            Work flowing across the Simple Pro AI team this week.
          </p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
        >
          <Plus className="h-3.5 w-3.5" />
          New task
        </button>
      </header>
      <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-4">
        {columns.map((column) => (
          <div
            key={column.id}
            className="flex min-h-[260px] flex-col rounded-xl border border-slate-100 bg-slate-50/60 p-3"
          >
            <div className="mb-3 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", column.accent)} />
                <h4 className="text-sm font-semibold text-slate-800">
                  {column.title}
                </h4>
              </div>
              <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-500 shadow-sm">
                {column.cards.length}
              </span>
            </div>
            <div className="flex-1 space-y-2">
              {column.cards.map((card) => (
                <article
                  key={card.id}
                  className="group cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium leading-snug text-slate-800">
                      {card.title}
                    </p>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2 text-xs">
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 font-medium",
                        TAG_TONES[card.tagTone],
                      )}
                    >
                      {card.tag}
                    </span>
                    <span className="text-slate-500">{card.meta}</span>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <span
                      className={cn(
                        "grid h-6 w-6 place-items-center rounded-full bg-gradient-to-br text-[10px] font-semibold text-white",
                        card.ownerAccent,
                      )}
                    >
                      {card.owner
                        .split(" ")
                        .slice(0, 2)
                        .map((part) => part[0])
                        .join("")
                        .toUpperCase()}
                    </span>
                    <span className="truncate text-xs text-slate-600">{card.owner}</span>
                  </div>
                </article>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
