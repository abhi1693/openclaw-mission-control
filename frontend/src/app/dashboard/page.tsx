"use client";

export const dynamic = "force-dynamic";

import { useMemo } from "react";

import { SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, Clock, PenSquare, Timer, Users } from "lucide-react";

import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import MetricSparkline from "@/components/charts/metric-sparkline";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { ApiError } from "@/api/mutator";
import {
  type dashboardMetricsApiV1MetricsDashboardGetResponse,
  useDashboardMetricsApiV1MetricsDashboardGet,
} from "@/api/generated/metrics/metrics";
import { parseApiDatetime } from "@/lib/datetime";

type RangeKey = "24h" | "7d";
type BucketKey = "hour" | "day";

type SeriesPoint = {
  period: string;
  value: number;
};

type WipPoint = {
  period: string;
  inbox: number;
  in_progress: number;
  review: number;
};

type RangeSeries = {
  range: RangeKey;
  bucket: BucketKey;
  points: SeriesPoint[];
};

type WipRangeSeries = {
  range: RangeKey;
  bucket: BucketKey;
  points: WipPoint[];
};

const hourFormatter = new Intl.DateTimeFormat("en-US", { hour: "numeric" });
const dayFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});
const updatedFormatter = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});

const formatPeriod = (value: string, bucket: BucketKey) => {
  const date = parseApiDatetime(value);
  if (!date) return "";
  return bucket === "hour"
    ? hourFormatter.format(date)
    : dayFormatter.format(date);
};

const formatNumber = (value: number) => value.toLocaleString("en-US");
const formatPercent = (value: number) => `${value.toFixed(1)}%`;
const formatHours = (value: number | null) =>
  value === null || !Number.isFinite(value) ? "--" : `${value.toFixed(1)}h`;
const calcProgress = (values?: number[]) => {
  if (!values || values.length === 0) return 0;
  const max = Math.max(...values);
  if (!Number.isFinite(max) || max <= 0) return 0;
  const latest = values[values.length - 1] ?? 0;
  return Math.max(0, Math.min(100, Math.round((latest / max) * 100)));
};

function buildSeries(series: RangeSeries) {
  return series.points.map((point) => ({
    period: formatPeriod(point.period, series.bucket),
    value: Number(point.value ?? 0),
  }));
}

function buildWipSeries(series: WipRangeSeries) {
  return series.points.map((point) => ({
    period: formatPeriod(point.period, series.bucket),
    inbox: Number(point.inbox ?? 0),
    in_progress: Number(point.in_progress ?? 0),
    review: Number(point.review ?? 0),
  }));
}

function buildSparkline(series: RangeSeries) {
  return {
    values: series.points.map((point) => Number(point.value ?? 0)),
    labels: series.points.map((point) =>
      formatPeriod(point.period, series.bucket),
    ),
  };
}

function buildWipSparkline(series: WipRangeSeries, key: keyof WipPoint) {
  return {
    values: series.points.map((point) => Number(point[key] ?? 0)),
    labels: series.points.map((point) =>
      formatPeriod(point.period, series.bucket),
    ),
  };
}

type TooltipProps = {
  active?: boolean;
  payload?: Array<{ value?: number; name?: string; color?: string }>;
  label?: string;
  formatter?: (value: number, name?: string) => string;
};

function TooltipCard({ active, payload, label, formatter }: TooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg bg-slate-900/95 px-3 py-2 text-xs text-slate-200 shadow-lg">
      <div className="text-slate-400">{label}</div>
      <div className="mt-1 space-y-1">
        {payload.map((entry) => (
          <div
            key={entry.name}
            className="flex items-center justify-between gap-3"
          >
            <span className="flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              {entry.name}
            </span>
            <span className="font-semibold text-slate-900">
              {formatter
                ? formatter(Number(entry.value ?? 0), entry.name)
                : entry.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sublabel,
  icon,
  progress = 0,
}: {
  label: string;
  value: string;
  sublabel?: string;
  icon: React.ReactNode;
  progress?: number;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {label}
        </p>
        <div className="rounded-lg bg-blue-50 p-2 text-blue-600">{icon}</div>
      </div>
      <div className="flex items-end gap-2">
        <h3 className="font-heading text-4xl font-bold text-slate-900">
          {value}
        </h3>
      </div>
      {sublabel ? (
        <p className="mt-2 text-xs text-slate-500">{sublabel}</p>
      ) : null}
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-600"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
  sparkline,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  sparkline?: { values: number[]; labels: string[] };
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h3 className="font-heading text-base font-semibold text-slate-900">
            {title}
          </h3>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-500">
          24h
        </span>
      </div>
      <div className="h-56">{children}</div>
      {sparkline ? (
        <div className="mt-4 border-t border-slate-100 pt-4">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="h-2 w-2 rounded-full bg-blue-500" />
            7d trend
          </div>
          <MetricSparkline
            values={sparkline.values}
            labels={sparkline.labels}
            bucket="week"
            className="mt-2"
          />
        </div>
      ) : null}
    </div>
  );
}

export default function DashboardPage() {
  const { isSignedIn } = useAuth();
  const metricsQuery = useDashboardMetricsApiV1MetricsDashboardGet<
    dashboardMetricsApiV1MetricsDashboardGetResponse,
    ApiError
  >(
    { range_key: "24h" },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchInterval: 15_000,
        refetchOnMount: "always",
      },
    },
  );

  const metrics =
    metricsQuery.data?.status === 200 ? metricsQuery.data.data : null;

  const throughputSeries = useMemo(
    () => (metrics ? buildSeries(metrics.throughput.primary) : []),
    [metrics],
  );
  const cycleSeries = useMemo(
    () => (metrics ? buildSeries(metrics.cycle_time.primary) : []),
    [metrics],
  );
  const errorSeries = useMemo(
    () => (metrics ? buildSeries(metrics.error_rate.primary) : []),
    [metrics],
  );
  const wipSeries = useMemo(
    () => (metrics ? buildWipSeries(metrics.wip.primary) : []),
    [metrics],
  );

  const throughputSpark = useMemo(
    () => (metrics ? buildSparkline(metrics.throughput.comparison) : null),
    [metrics],
  );
  const cycleSpark = useMemo(
    () => (metrics ? buildSparkline(metrics.cycle_time.comparison) : null),
    [metrics],
  );
  const errorSpark = useMemo(
    () => (metrics ? buildSparkline(metrics.error_rate.comparison) : null),
    [metrics],
  );
  const wipSpark = useMemo(
    () =>
      metrics ? buildWipSparkline(metrics.wip.comparison, "in_progress") : null,
    [metrics],
  );

  const activeProgress = useMemo(
    () => (metrics ? Math.min(100, metrics.kpis.active_agents * 12.5) : 0),
    [metrics],
  );
  const wipProgress = useMemo(() => calcProgress(wipSpark?.values), [wipSpark]);
  const errorProgress = useMemo(
    () => calcProgress(errorSpark?.values),
    [errorSpark],
  );
  const cycleProgress = useMemo(
    () => calcProgress(cycleSpark?.values),
    [cycleSpark],
  );

  const updatedAtLabel = useMemo(() => {
    if (!metrics?.generated_at) return null;
    const date = parseApiDatetime(metrics.generated_at);
    if (!date) return null;
    return updatedFormatter.format(date);
  }, [metrics]);

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access the dashboard."
          forceRedirectUrl="/onboarding"
          signUpForceRedirectUrl="/onboarding"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          <div className="border-b border-slate-200 bg-white px-8 py-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-heading text-2xl font-semibold text-slate-900 tracking-tight">
                  Dashboard
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Monitor your mission control operations
                </p>
              </div>
              {updatedAtLabel ? (
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <Clock className="h-4 w-4" />
                  Updated {updatedAtLabel}
                </div>
              ) : null}
            </div>
          </div>
          <div className="p-8">
            {metricsQuery.error ? (
              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600 shadow-sm">
                {metricsQuery.error.message}
              </div>
            ) : null}

            {metricsQuery.isLoading && !metrics ? (
              <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
                Loading dashboard metrics…
              </div>
            ) : null}

            {metrics ? (
              <>
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
                  <KpiCard
                    label="Active agents"
                    value={formatNumber(metrics.kpis.active_agents)}
                    sublabel="Last 10 minutes"
                    icon={<Users className="h-4 w-4" />}
                    progress={activeProgress}
                  />
                  <KpiCard
                    label="Tasks in progress"
                    value={formatNumber(metrics.kpis.tasks_in_progress)}
                    sublabel="Current WIP"
                    icon={<PenSquare className="h-4 w-4" />}
                    progress={wipProgress}
                  />
                  <KpiCard
                    label="Error rate"
                    value={formatPercent(metrics.kpis.error_rate_pct)}
                    sublabel="24h average"
                    icon={<Activity className="h-4 w-4" />}
                    progress={errorProgress}
                  />
                  <KpiCard
                    label="Median cycle time"
                    value={formatHours(metrics.kpis.median_cycle_time_hours_7d)}
                    sublabel="7d median"
                    icon={<Timer className="h-4 w-4" />}
                    progress={cycleProgress}
                  />
                </div>

                <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
                  <ChartCard
                    title="Completed Tasks"
                    subtitle="Throughput"
                    sparkline={throughputSpark ?? undefined}
                  >
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={throughputSeries}
                        margin={{ left: 4, right: 12 }}
                      >
                        <CartesianGrid vertical={false} stroke="#e2e8f0" />
                        <XAxis
                          dataKey="period"
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                        />
                        <YAxis
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                          width={40}
                        />
                        <Tooltip
                          content={
                            <TooltipCard formatter={(v) => formatNumber(v)} />
                          }
                        />
                        <Bar
                          dataKey="value"
                          name="Completed"
                          fill="#2563eb"
                          radius={[6, 6, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartCard>

                  <ChartCard
                    title="Avg Hours to Review"
                    subtitle="Cycle time"
                    sparkline={cycleSpark ?? undefined}
                  >
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={cycleSeries}
                        margin={{ left: 4, right: 12 }}
                      >
                        <CartesianGrid vertical={false} stroke="#e2e8f0" />
                        <XAxis
                          dataKey="period"
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                        />
                        <YAxis
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                          width={40}
                        />
                        <Tooltip
                          content={
                            <TooltipCard
                              formatter={(v) => `${v.toFixed(1)}h`}
                            />
                          }
                        />
                        <Line
                          type="monotone"
                          dataKey="value"
                          name="Hours"
                          stroke="#1d4ed8"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </ChartCard>

                  <ChartCard
                    title="Failed Events"
                    subtitle="Error rate"
                    sparkline={errorSpark ?? undefined}
                  >
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={errorSeries}
                        margin={{ left: 4, right: 12 }}
                      >
                        <CartesianGrid vertical={false} stroke="#e2e8f0" />
                        <XAxis
                          dataKey="period"
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                        />
                        <YAxis
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                          width={40}
                        />
                        <Tooltip
                          content={
                            <TooltipCard formatter={(v) => formatPercent(v)} />
                          }
                        />
                        <Line
                          type="monotone"
                          dataKey="value"
                          name="Error rate"
                          stroke="#1e40af"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </ChartCard>

                  <ChartCard
                    title="Status Distribution"
                    subtitle="Work in progress"
                    sparkline={wipSpark ?? undefined}
                  >
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={wipSeries}
                        margin={{ left: 4, right: 12 }}
                      >
                        <CartesianGrid vertical={false} stroke="#e2e8f0" />
                        <XAxis
                          dataKey="period"
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                        />
                        <YAxis
                          tickLine={false}
                          axisLine={false}
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                          width={40}
                        />
                        <Tooltip
                          content={
                            <TooltipCard formatter={(v) => formatNumber(v)} />
                          }
                        />
                        <Area
                          type="monotone"
                          dataKey="inbox"
                          name="Inbox"
                          stackId="wip"
                          fill="#dbeafe"
                          stroke="#93c5fd"
                          fillOpacity={0.8}
                        />
                        <Area
                          type="monotone"
                          dataKey="in_progress"
                          name="In progress"
                          stackId="wip"
                          fill="#93c5fd"
                          stroke="#2563eb"
                          fillOpacity={0.8}
                        />
                        <Area
                          type="monotone"
                          dataKey="review"
                          name="Review"
                          stackId="wip"
                          fill="#60a5fa"
                          stroke="#1d4ed8"
                          fillOpacity={0.85}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </ChartCard>
                </div>
              </>
            ) : null}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
