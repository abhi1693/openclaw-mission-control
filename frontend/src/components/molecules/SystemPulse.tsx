"use client";

import { Activity, Bot, CircleAlert, Database, Server } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type getSystemStatusApiV1SystemStatusGetResponse,
  useGetSystemStatusApiV1SystemStatusGet,
} from "@/api/generated/system/system";
import type { SystemStatusResponse } from "@/api/generated/model/systemStatusResponse";
import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "danger" | "neutral";

type Metric = {
  label: string;
  value: string;
  hint: string;
  tone: Tone;
  icon: React.ReactNode;
};

const TONE_CARD_CLASS: Record<Tone, string> = {
  ok: "border-emerald-200 bg-emerald-50",
  warn: "border-amber-200 bg-amber-50",
  danger: "border-rose-200 bg-rose-50",
  neutral: "border-slate-200 bg-white",
};

const TONE_ICON_CLASS: Record<Tone, string> = {
  ok: "bg-emerald-100 text-emerald-700",
  warn: "bg-amber-100 text-amber-700",
  danger: "bg-rose-100 text-rose-700",
  neutral: "bg-slate-100 text-slate-600",
};

const TONE_VALUE_CLASS: Record<Tone, string> = {
  ok: "text-emerald-800",
  warn: "text-amber-800",
  danger: "text-rose-800",
  neutral: "text-slate-800",
};

// A queue this long suggests workers can't keep up. Tunable; chosen to flag
// real backups without firing on the brief spikes that happen during a normal
// burst of agent activity.
const QUEUE_WARN_THRESHOLD = 25;

const worstTone = (tones: Tone[]): Tone => {
  if (tones.includes("danger")) return "danger";
  if (tones.includes("warn")) return "warn";
  if (tones.includes("ok")) return "ok";
  return "neutral";
};

const buildMetrics = (status: SystemStatusResponse): Metric[] => {
  const queueTotal = status.queue.depth + status.queue.scheduled_depth;
  const queueTone: Tone = queueTotal >= QUEUE_WARN_THRESHOLD ? "warn" : "ok";

  const agentTone: Tone =
    status.agents.total === 0
      ? "neutral"
      : status.agents.online === 0
        ? "danger"
        : status.agents.offline > 0
          ? "warn"
          : "ok";

  const gatewayTone: Tone = status.gateways.total === 0 ? "neutral" : "ok";

  return [
    {
      label: "Queue",
      value: queueTotal.toString(),
      hint:
        status.queue.scheduled_depth > 0
          ? `${status.queue.depth} ready · ${status.queue.scheduled_depth} scheduled`
          : `${status.queue.depth} ready`,
      tone: queueTone,
      icon: <Database className="h-4 w-4" />,
    },
    {
      label: "Agents",
      value: `${status.agents.online}/${status.agents.total}`,
      hint:
        status.agents.total === 0
          ? "No agents registered"
          : `${status.agents.offline} offline`,
      tone: agentTone,
      icon: <Bot className="h-4 w-4" />,
    },
    {
      label: "Gateways",
      value: status.gateways.total.toString(),
      hint: status.gateways.total === 1 ? "1 registered" : `${status.gateways.total} registered`,
      tone: gatewayTone,
      icon: <Server className="h-4 w-4" />,
    },
  ];
};

interface SystemPulseProps {
  /** Whether to issue the underlying request. Mirrors the dashboard's signed-in gate. */
  enabled?: boolean;
  className?: string;
}

export function SystemPulse({ enabled = true, className }: SystemPulseProps) {
  const query = useGetSystemStatusApiV1SystemStatusGet<
    getSystemStatusApiV1SystemStatusGetResponse,
    ApiError
  >({
    query: {
      enabled,
      refetchInterval: 15_000,
      refetchOnMount: "always",
    },
  });

  const status = query.data?.status === 200 ? query.data.data : null;

  if (query.isLoading && !status) {
    return (
      <section
        aria-label="System pulse loading"
        className={cn(
          "rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-500 shadow-sm",
          className,
        )}
      >
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 animate-pulse text-slate-400" />
          Checking system pulse…
        </div>
      </section>
    );
  }

  if (!status) {
    return (
      <section
        aria-label="System pulse unavailable"
        className={cn(
          "rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 shadow-sm",
          className,
        )}
      >
        <div className="flex items-center gap-2">
          <CircleAlert className="h-4 w-4" />
          System pulse temporarily unavailable.
        </div>
      </section>
    );
  }

  const metrics = buildMetrics(status);
  const overall = worstTone(metrics.map((m) => m.tone));

  const overallLabel =
    overall === "danger"
      ? "Attention required"
      : overall === "warn"
        ? "Degraded"
        : overall === "ok"
          ? "Healthy"
          : "Idle";

  return (
    <section
      aria-label="System pulse"
      className={cn(
        "rounded-xl border p-3 md:p-4 shadow-sm transition",
        TONE_CARD_CLASS[overall],
        className,
      )}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <span className={cn("rounded-lg p-1.5", TONE_ICON_CLASS[overall])}>
            <Activity className="h-4 w-4" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              System pulse
            </p>
            <p className={cn("text-sm font-medium", TONE_VALUE_CLASS[overall])}>
              {overallLabel}
            </p>
          </div>
        </div>
        <dl className="grid grid-cols-3 gap-2 md:gap-4">
          {metrics.map((metric) => (
            <div
              key={metric.label}
              className="flex items-center gap-2 rounded-lg border border-white/60 bg-white/70 px-3 py-2"
            >
              <span className={cn("rounded-md p-1.5", TONE_ICON_CLASS[metric.tone])}>
                {metric.icon}
              </span>
              <div className="min-w-0">
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  {metric.label}
                </dt>
                <dd className="flex items-baseline gap-2">
                  <span
                    className={cn(
                      "text-base font-semibold tabular-nums",
                      TONE_VALUE_CLASS[metric.tone],
                    )}
                  >
                    {metric.value}
                  </span>
                  <span className="truncate text-[11px] text-slate-500">
                    {metric.hint}
                  </span>
                </dd>
              </div>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
