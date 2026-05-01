"use client";

export const dynamic = "force-dynamic";

import { useMemo } from "react";

import { SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import {
  Bot,
  CheckCircle2,
  LayoutGrid,
  Rocket,
} from "lucide-react";

import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { ApiError } from "@/api/mutator";
import {
  type dashboardMetricsApiV1MetricsDashboardGetResponse,
  useDashboardMetricsApiV1MetricsDashboardGet,
} from "@/api/generated/metrics/metrics";
import {
  type listAgentsApiV1AgentsGetResponse,
  useListAgentsApiV1AgentsGet,
} from "@/api/generated/agents/agents";

import { MissionControlHeader } from "@/components/mission-control/MissionControlHeader";
import { StatCard } from "@/components/mission-control/StatCard";
import { AgentTable } from "@/components/mission-control/AgentTable";
import { TaskPipeline } from "@/components/mission-control/TaskPipeline";
import { BelleInsights } from "@/components/mission-control/BelleInsights";
import { ReposDeployments } from "@/components/mission-control/ReposDeployments";
import { RecentActivity } from "@/components/mission-control/RecentActivity";
import { ApprovalsQueue } from "@/components/mission-control/ApprovalsQueue";
import { QuickActions } from "@/components/mission-control/QuickActions";
import {
  APPROVAL_QUEUE,
  BELLE_INSIGHTS,
  RECENT_ACTIVITY,
  REPOS_DEPLOYMENTS,
  SIMPLE_PRO_AGENTS,
  TASK_PIPELINE,
} from "@/components/mission-control/mockTeam";

const DASHBOARD_RANGE = "7d";

const numberFormatter = new Intl.NumberFormat("en-US");
const formatCount = (value: number) =>
  Number.isFinite(value) ? numberFormatter.format(Math.max(0, Math.round(value))) : "0";

export default function DashboardPage() {
  const { isSignedIn } = useAuth();

  const agentsQuery = useListAgentsApiV1AgentsGet<listAgentsApiV1AgentsGetResponse, ApiError>(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchInterval: 15_000,
        refetchOnMount: "always",
      },
    },
  );

  const metricsQuery = useDashboardMetricsApiV1MetricsDashboardGet<
    dashboardMetricsApiV1MetricsDashboardGetResponse,
    ApiError
  >(
    { range_key: DASHBOARD_RANGE },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchInterval: 15_000,
        refetchOnMount: "always",
        retry: 3,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 5000),
      },
    },
  );

  const realAgents = useMemo(
    () =>
      agentsQuery.data?.status === 200
        ? agentsQuery.data.data.items ?? []
        : [],
    [agentsQuery.data],
  );

  const metrics = metricsQuery.data?.status === 200 ? metricsQuery.data.data : null;

  const onlineAgents = useMemo(
    () => realAgents.filter((agent) => (agent.status ?? "").toLowerCase() === "online").length,
    [realAgents],
  );

  const tasksInProgress =
    metrics?.kpis.tasks_in_progress ?? metrics?.kpis.in_progress_tasks ?? 0;
  const pendingApprovals =
    metrics?.pending_approvals.total ?? APPROVAL_QUEUE.length;
  const doneTasks = metrics?.kpis.done_tasks ?? 0;

  const successfulDeploys = REPOS_DEPLOYMENTS.filter(
    (entry) => entry.status === "deployed",
  ).length;

  const activeAgentsValue = onlineAgents > 0 ? onlineAgents : SIMPLE_PRO_AGENTS.filter(
    (agent) => agent.status === "active",
  ).length;
  const totalAgentsValue = realAgents.length > 0 ? realAgents.length : SIMPLE_PRO_AGENTS.length;
  const tasksInProgressValue =
    tasksInProgress > 0
      ? tasksInProgress
      : TASK_PIPELINE.find((column) => column.id === "in-progress")?.cards.length ?? 0;
  const completedTodayValue = doneTasks > 0 ? doneTasks : 12;

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access Simple Pro Mission Control."
          forceRedirectUrl="/onboarding"
          signUpForceRedirectUrl="/onboarding"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          <div className="mx-auto max-w-[1600px] space-y-5 p-4 md:p-8">
            <MissionControlHeader
              workspace="Simple Pro · Production"
              notificationCount={pendingApprovals}
              belleStatus="online"
              belleLatencyMs={312}
              belleActiveSessions={14}
            />

            {metricsQuery.error ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                Live metrics temporarily unavailable: {metricsQuery.error.message}
              </div>
            ) : null}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                title="Active agents"
                value={formatCount(activeAgentsValue)}
                subtitle={`${formatCount(totalAgentsValue)} on the AI team`}
                icon={<Bot className="h-4 w-4" />}
                trend="+2 this week"
                trendDirection="up"
                accent="blue"
              />
              <StatCard
                title="Tasks in progress"
                value={formatCount(tasksInProgressValue)}
                subtitle={`${formatCount(completedTodayValue)} completed today`}
                icon={<LayoutGrid className="h-4 w-4" />}
                trend="+18% throughput"
                trendDirection="up"
                accent="violet"
              />
              <StatCard
                title="Pending approvals"
                value={formatCount(pendingApprovals)}
                subtitle="Decisions waiting on a human"
                icon={<CheckCircle2 className="h-4 w-4" />}
                trend="2 high risk"
                trendDirection="flat"
                accent="amber"
              />
              <StatCard
                title="Successful deploys"
                value={formatCount(successfulDeploys)}
                subtitle="Last 7 days · 0 rollbacks"
                icon={<Rocket className="h-4 w-4" />}
                trend="+24% vs prior"
                trendDirection="up"
                accent="emerald"
              />
            </div>

            <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
              <div className="space-y-5 xl:col-span-2">
                <AgentTable agents={SIMPLE_PRO_AGENTS} />
                <TaskPipeline columns={TASK_PIPELINE} />
              </div>
              <div className="xl:sticky xl:top-4">
                <BelleInsights insights={BELLE_INSIGHTS} />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 xl:grid-cols-4">
              <div className="xl:col-span-2">
                <ReposDeployments items={REPOS_DEPLOYMENTS} />
              </div>
              <RecentActivity items={RECENT_ACTIVITY} />
              <ApprovalsQueue items={APPROVAL_QUEUE} />
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
              <QuickActions />
              <section className="rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6 text-slate-100 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-300">
                  Belle daily briefing
                </p>
                <h3 className="mt-2 font-heading text-xl font-semibold">
                  Service Pro accounts grew 6.2% this week
                </h3>
                <p className="mt-2 text-sm text-slate-300">
                  Belle handled 1,284 inbound calls, booked 412 jobs, sent 387 estimates,
                  and recovered $12,480 in late invoices. Roofing and HVAC verticals are
                  driving most of the growth — Belle suggests staffing extra capacity on the
                  estimate-follow-up cadence next week.
                </p>
                <div className="mt-4 flex flex-wrap gap-3 text-xs">
                  <span className="rounded-full bg-white/10 px-3 py-1">1,284 calls</span>
                  <span className="rounded-full bg-white/10 px-3 py-1">412 jobs booked</span>
                  <span className="rounded-full bg-white/10 px-3 py-1">387 estimates</span>
                  <span className="rounded-full bg-white/10 px-3 py-1">$12.48k recovered</span>
                </div>
              </section>
            </div>
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
