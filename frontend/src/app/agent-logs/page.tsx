"use client";

export const dynamic = "force-dynamic";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import { ScrollText, Bot, ChevronDown, ChevronUp } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type listAgentsApiV1AgentsGetResponse,
  useListAgentsApiV1AgentsGet,
} from "@/api/generated/agents/agents";
import {
  type listActivityApiV1ActivityGetResponse,
  useListActivityApiV1ActivityGet,
} from "@/api/generated/activity/activity";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  getBoardSnapshotApiV1BoardsBoardIdSnapshotGet,
} from "@/api/generated/boards/boards";
import type {
  ActivityEventRead,
  AgentRead,
  BoardRead,
  TaskCardRead,
} from "@/api/generated/model";

import { Markdown } from "@/components/atoms/Markdown";
import { StatusPill } from "@/components/atoms/StatusPill";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import {
  formatRelativeTimestamp as formatRelative,
  formatTimestamp,
} from "@/lib/formatters";
import { cn } from "@/lib/utils";

const REFETCH_INTERVAL_MS = 15_000;
const ACTIVITY_LIMIT = 200;

type AgentWithContext = AgentRead & {
  boardName: string | null;
  currentTask: TaskCardRead | null;
  events: ActivityEventRead[];
};

const agentStatusOrder = (status?: string | null): number => {
  const s = (status ?? "").toLowerCase();
  if (s === "online") return 0;
  if (s === "provisioning") return 1;
  return 2;
};

const roleFromAgent = (agent: AgentRead): string | null => {
  const profile = agent.identity_profile;
  if (!profile || typeof profile !== "object") return null;
  const role = (profile as Record<string, unknown>).role;
  if (typeof role !== "string") return null;
  const trimmed = role.trim();
  return trimmed || null;
};

const formatShortTimestamp = (value?: string | null): string => {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const eventTypeLabel = (eventType: string): string => {
  if (eventType === "task.comment") return "Comment";
  if (eventType === "task.created") return "Created";
  if (eventType === "task.status_changed") return "Status";
  if (eventType === "task.updated") return "Updated";
  if (eventType === "board.chat") return "Chat";
  return eventType.replace(/[._]/g, " ");
};

const eventTypePillClass = (eventType: string): string => {
  if (eventType === "task.comment")
    return "border-blue-200 bg-blue-50 text-blue-700";
  if (eventType === "task.created")
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (eventType === "task.status_changed")
    return "border-amber-200 bg-amber-50 text-amber-700";
  if (eventType === "board.chat")
    return "border-teal-200 bg-teal-50 text-teal-700";
  return "border-slate-200 bg-slate-100 text-slate-700";
};

// ─── Agent Log Entry ─────────────────────────────────────────────────

const AgentLogEntry = memo(function AgentLogEntry({
  event,
}: {
  event: ActivityEventRead;
}) {
  const message = (event.message ?? "").trim();

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 transition hover:border-slate-300">
      <div className="flex items-center gap-2 text-[11px] text-slate-500">
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            eventTypePillClass(event.event_type),
          )}
        >
          {eventTypeLabel(event.event_type)}
        </span>
        <span className="text-slate-400">
          {formatShortTimestamp(event.created_at)}
        </span>
      </div>
      {message ? (
        <div className="mt-2 select-text cursor-text text-sm leading-relaxed text-slate-900 break-words">
          <Markdown content={message} variant="basic" />
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-500">—</p>
      )}
    </div>
  );
});

AgentLogEntry.displayName = "AgentLogEntry";

// ─── Agent Card ──────────────────────────────────────────────────────

const COLLAPSED_LOG_COUNT = 3;

const AgentCard = memo(function AgentCard({
  agent,
}: {
  agent: AgentWithContext;
}) {
  const [expanded, setExpanded] = useState(false);
  const status = (agent.status ?? "offline").toLowerCase();
  const role = roleFromAgent(agent);
  const events = agent.events;
  const hasMore = events.length > COLLAPSED_LOG_COUNT;
  const visibleEvents = expanded ? events : events.slice(0, COLLAPSED_LOG_COUNT);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:shadow-md">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
        <div
          className={cn(
            "flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full text-sm font-bold",
            status === "online"
              ? "bg-emerald-100 text-emerald-700"
              : status === "provisioning"
                ? "bg-amber-100 text-amber-700"
                : "bg-slate-100 text-slate-500",
          )}
        >
          {agent.name[0]?.toUpperCase() ?? "?"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link
              href={`/agents/${agent.id}`}
              className="text-sm font-semibold text-slate-900 hover:underline"
            >
              {agent.name}
            </Link>
            <StatusPill status={status} />
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
            {role ? <span>{role}</span> : null}
            {role && agent.boardName ? (
              <span className="text-slate-300">·</span>
            ) : null}
            {agent.boardName ? (
              <span className="font-medium text-slate-600">
                {agent.boardName}
              </span>
            ) : null}
            <span className="text-slate-300">·</span>
            <span>Last seen {formatRelative(agent.last_seen_at)}</span>
          </div>
        </div>
      </div>

      {/* Current Task */}
      {agent.currentTask ? (
        <div className="border-b border-slate-100 px-5 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Current Task
          </p>
          <p className="mt-1 text-sm font-medium text-slate-800">
            {agent.currentTask.title}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <StatusPill status={agent.currentTask.status ?? "inbox"} />
            {agent.currentTask.priority ? (
              <span className="capitalize">{agent.currentTask.priority}</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Activity Log */}
      <div className="px-5 py-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Recent Activity
          </p>
          <p className="text-[10px] text-slate-400">
            {events.length} event{events.length !== 1 ? "s" : ""}
          </p>
        </div>
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-sm text-slate-500">
            No activity yet.
          </div>
        ) : (
          <div className="space-y-2">
            {visibleEvents.map((event) => (
              <AgentLogEntry key={event.id} event={event} />
            ))}
          </div>
        )}
        {hasMore ? (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="mt-3 flex w-full items-center justify-center gap-1 rounded-lg border border-slate-200 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                Show all {events.length} events
              </>
            )}
          </button>
        ) : null}
      </div>
    </div>
  );
});

AgentCard.displayName = "AgentCard";

// ─── Page ────────────────────────────────────────────────────────────

export default function AgentLogsPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  // ── Data queries ──────────────────────────────────────────────────

  const agentsQuery = useListAgentsApiV1AgentsGet<
    listAgentsApiV1AgentsGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: REFETCH_INTERVAL_MS,
      refetchOnMount: "always",
      retry: false,
    },
  });

  const activityQuery = useListActivityApiV1ActivityGet<
    listActivityApiV1ActivityGetResponse,
    ApiError
  >(
    { limit: ACTIVITY_LIMIT },
    {
      query: {
        enabled: Boolean(isSignedIn && isAdmin),
        refetchInterval: REFETCH_INTERVAL_MS,
        retry: false,
      },
    },
  );

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: 60_000,
      refetchOnMount: "always",
      retry: false,
    },
  });

  // ── Snapshot state for task assignments ────────────────────────────

  const [tasksByAgent, setTasksByAgent] = useState<
    Map<string, TaskCardRead>
  >(new Map());

  const boards = useMemo<BoardRead[]>(() => {
    if (boardsQuery.data?.status !== 200) return [];
    return boardsQuery.data.data.items ?? [];
  }, [boardsQuery.data]);

  const boardsById = useMemo(
    () => new Map(boards.map((b) => [b.id, b])),
    [boards],
  );

  // Fetch snapshots for all boards to get task assignments
  useEffect(() => {
    if (boards.length === 0) return;
    let cancelled = false;

    const fetchSnapshots = async () => {
      const taskMap = new Map<string, TaskCardRead>();
      const results = await Promise.allSettled(
        boards.map((board) =>
          getBoardSnapshotApiV1BoardsBoardIdSnapshotGet(board.id),
        ),
      );
      if (cancelled) return;
      results.forEach((result) => {
        if (result.status !== "fulfilled") return;
        if (result.value.status !== 200) return;
        const snapshot = result.value.data;
        (snapshot.tasks ?? []).forEach((task) => {
          if (
            task.assigned_agent_id &&
            (task.status === "in_progress" || task.status === "review")
          ) {
            const existing = taskMap.get(task.assigned_agent_id);
            if (
              !existing ||
              task.status === "in_progress"
            ) {
              taskMap.set(task.assigned_agent_id, task);
            }
          }
        });
      });
      if (!cancelled) {
        setTasksByAgent(taskMap);
      }
    };

    void fetchSnapshots();
    return () => {
      cancelled = true;
    };
  }, [boards]);

  // ── Build agent context ───────────────────────────────────────────

  const agents = useMemo<AgentRead[]>(() => {
    if (agentsQuery.data?.status !== 200) return [];
    return agentsQuery.data.data.items ?? [];
  }, [agentsQuery.data]);

  const events = useMemo<ActivityEventRead[]>(() => {
    if (activityQuery.data?.status !== 200) return [];
    return activityQuery.data.data.items ?? [];
  }, [activityQuery.data]);

  const agentsWithContext = useMemo<AgentWithContext[]>(() => {
    // Group events by agent
    const eventsByAgent = new Map<string, ActivityEventRead[]>();
    for (const event of events) {
      if (!event.agent_id) continue;
      const list = eventsByAgent.get(event.agent_id) ?? [];
      list.push(event);
      eventsByAgent.set(event.agent_id, list);
    }

    return agents
      .filter((a) => !a.is_gateway_main)
      .map((agent) => ({
        ...agent,
        boardName: agent.board_id
          ? (boardsById.get(agent.board_id)?.name ?? null)
          : null,
        currentTask: tasksByAgent.get(agent.id) ?? null,
        events: eventsByAgent.get(agent.id) ?? [],
      }))
      .sort((a, b) => {
        const statusDiff = agentStatusOrder(a.status) - agentStatusOrder(b.status);
        if (statusDiff !== 0) return statusDiff;
        return a.name.localeCompare(b.name);
      });
  }, [agents, events, boardsById, tasksByAgent]);

  const onlineCount = useMemo(
    () =>
      agentsWithContext.filter(
        (a) => (a.status ?? "").toLowerCase() === "online",
      ).length,
    [agentsWithContext],
  );

  const isLoading =
    agentsQuery.isLoading || activityQuery.isLoading || boardsQuery.isLoading;
  const error =
    agentsQuery.error?.message ??
    activityQuery.error?.message ??
    boardsQuery.error?.message ??
    null;

  // ── Render ────────────────────────────────────────────────────────

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to view agent logs."
          forceRedirectUrl="/agent-logs"
          signUpForceRedirectUrl="/agent-logs"
          mode="redirect"
          buttonTestId="agent-logs-signin"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          {/* Header */}
          <div className="sticky top-0 z-30 border-b border-slate-200 bg-white">
            <div className="px-4 py-4 md:px-8 md:py-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <ScrollText className="h-5 w-5 text-slate-600" />
                    <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                      Agent Logs
                    </h1>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    Live activity logs for each AI agent — tasks, outputs, and
                    inter-agent communications.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600">
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full",
                        onlineCount > 0 ? "bg-emerald-500" : "bg-slate-300",
                      )}
                    />
                    {onlineCount} online
                  </div>
                  <div className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600">
                    {agentsWithContext.length} agent
                    {agentsWithContext.length !== 1 ? "s" : ""}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="p-4 md:p-8">
            {!isAdmin ? (
              <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
                Only organization owners and admins can view agent logs.
              </div>
            ) : error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {error}
              </div>
            ) : isLoading && agentsWithContext.length === 0 ? (
              <div className="flex items-center justify-center py-20 text-sm text-slate-500">
                Loading agent data…
              </div>
            ) : agentsWithContext.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white p-10 text-center shadow-sm">
                <Bot className="mx-auto h-10 w-10 text-slate-300" />
                <p className="mt-3 text-sm font-medium text-slate-900">
                  No agents found
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  Agents will appear here once they are registered and connected.
                </p>
              </div>
            ) : (
              <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
                {agentsWithContext.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} />
                ))}
              </div>
            )}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
