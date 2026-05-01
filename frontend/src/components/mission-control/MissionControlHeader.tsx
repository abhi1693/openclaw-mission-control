import { Bell, ChevronDown, Sparkles, Activity } from "lucide-react";

export type MissionControlHeaderProps = {
  workspace?: string;
  notificationCount?: number;
  belleStatus?: "online" | "degraded" | "offline";
  belleLatencyMs?: number;
  belleActiveSessions?: number;
};

export function MissionControlHeader({
  workspace = "Simple Pro · Production",
  notificationCount = 5,
  belleStatus = "online",
  belleLatencyMs = 312,
  belleActiveSessions = 14,
}: MissionControlHeaderProps) {
  const statusColor =
    belleStatus === "online"
      ? "bg-emerald-500"
      : belleStatus === "degraded"
        ? "bg-amber-500"
        : "bg-rose-500";
  const statusLabel =
    belleStatus === "online"
      ? "Online"
      : belleStatus === "degraded"
        ? "Degraded"
        : "Offline";

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">
          <Activity className="h-3.5 w-3.5" />
          Mission Control
        </div>
        <h1 className="mt-1 font-heading text-2xl font-bold text-slate-900 md:text-3xl">
          Simple Pro Mission Control
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Belle, agents, and the production stack — one calm command center for the AI team
          building Simple Pro.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
        >
          <span className="grid h-6 w-6 place-items-center rounded-md bg-gradient-to-br from-indigo-500 to-blue-600 text-[10px] font-semibold text-white">
            SP
          </span>
          <span className="max-w-[180px] truncate">{workspace}</span>
          <ChevronDown className="h-4 w-4 text-slate-400" />
        </button>

        <button
          type="button"
          className="relative inline-flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          {notificationCount > 0 ? (
            <span className="absolute -right-1 -top-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold text-white">
              {notificationCount}
            </span>
          ) : null}
        </button>

        <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-gradient-to-br from-fuchsia-50 via-white to-violet-50 px-4 py-2 shadow-sm">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-fuchsia-500 to-purple-600 text-white shadow-sm">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-purple-700">
              <span className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
              Belle Orchestrator · {statusLabel}
            </div>
            <div className="text-xs text-slate-600">
              {belleActiveSessions} sessions · {belleLatencyMs}ms p50
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
