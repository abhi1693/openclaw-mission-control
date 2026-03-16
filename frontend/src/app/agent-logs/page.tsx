"use client";

export const dynamic = "force-dynamic";

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import {
  ScrollText,
  Bot,
  ChevronDown,
  ChevronUp,
  Search,
  Filter,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type listAgentsApiV1AgentsGetResponse,
  useListAgentsApiV1AgentsGet,
  getListAgentsApiV1AgentsGetQueryKey,
} from "@/api/generated/agents/agents";
import {
  type listActivityApiV1ActivityGetResponse,
  useListActivityApiV1ActivityGet,
  getListActivityApiV1ActivityGetQueryKey,
} from "@/api/generated/activity/activity";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { getBoardSnapshotApiV1BoardsBoardIdSnapshotGet } from "@/api/generated/boards/boards";
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
import { useSSE, type SSEStatus } from "@/lib/use-sse";

// ─── Constants ───────────────────────────────────────────────────────

const REFETCH_INTERVAL_MS = 15_000;
const REFETCH_INTERVAL_SSE_MS = 60_000; // Slower polling when SSE active
const ACTIVITY_LIMIT = 200;

const TIME_RANGES = [
  { label: "Last 1h", value: "1h", ms: 60 * 60 * 1000 },
  { label: "Last 6h", value: "6h", ms: 6 * 60 * 60 * 1000 },
  { label: "Last 24h", value: "24h", ms: 24 * 60 * 60 * 1000 },
  { label: "Last 7d", value: "7d", ms: 7 * 24 * 60 * 60 * 1000 },
  { label: "All time", value: "all", ms: 0 },
] as const;

const STATUS_OPTIONS = [
  { label: "All", value: "all" },
  { label: "Online", value: "online" },
  { label: "Offline", value: "offline" },
] as const;

// ─── Helpers ─────────────────────────────────────────────────────────

type AgentWithContext = AgentRead & {
  boardName: string | null;
  currentTask: TaskCardRead | null;
  events: ActivityEventRead[];
  activityState: "working" | "idle" | "waiting" | "offline";
  lastActivityAt: Date | null;
};

const agentStatusOrder = (status?: string | null): number => {
  const s = (status ?? "").toLowerCase();
  if (s === "online") return 0;
  if (s === "provisioning") return 1;
  return 2;
};

const activityStateOrder = (state: string): number => {
  if (state === "working") return 0;
  if (state === "waiting") return 1;
  if (state === "idle") return 2;
  return 3;
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

const parseDate = (value?: string | null): Date | null => {
  if (!value) return null;
  const d = new Date(value.endsWith("Z") ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
};

const minutesAgo = (date: Date | null): number => {
  if (!date) return Infinity;
  return (Date.now() - date.getTime()) / 60_000;
};

const deriveActivityState = (
  agent: AgentRead,
  hasTask: boolean,
  lastActivity: Date | null,
): AgentWithContext["activityState"] => {
  const status = (agent.status ?? "").toLowerCase();
  if (status !== "online") return "offline";

  const mins = minutesAgo(lastActivity);
  if (hasTask && mins < 5) return "working";
  if (hasTask && mins >= 15) return "waiting";
  if (mins >= 5) return "idle";
  return "working";
};

// ─── SSE Connection Indicator ────────────────────────────────────────

const SSEIndicator = memo(function SSEIndicator({
  status,
}: {
  status: SSEStatus;
}) {
  if (status === "connected") {
    return (
      <div className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
        <Wifi className="h-3 w-3" />
        Live
      </div>
    );
  }
  if (status === "connecting") {
    return (
      <div className="flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700">
        <Wifi className="h-3 w-3 animate-pulse" />
        Connecting…
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-500">
      <WifiOff className="h-3 w-3" />
      Polling
    </div>
  );
});

SSEIndicator.displayName = "SSEIndicator";

// ─── Activity State Dot ──────────────────────────────────────────────

const ActivityStateDot = memo(function ActivityStateDot({
  state,
  className,
}: {
  state: AgentWithContext["activityState"];
  className?: string;
}) {
  if (state === "working") {
    return (
      <span className={cn("relative flex h-3 w-3", className)}>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-500" />
      </span>
    );
  }
  if (state === "idle") {
    return (
      <span
        className={cn("inline-flex h-3 w-3 rounded-full bg-amber-400", className)}
      />
    );
  }
  if (state === "waiting") {
    return (
      <span className={cn("relative flex h-3 w-3", className)}>
        <span className="absolute inline-flex h-full w-full animate-pulse rounded-full bg-orange-300 opacity-60" />
        <span className="relative inline-flex h-3 w-3 rounded-full bg-orange-400" />
      </span>
    );
  }
  return (
    <span
      className={cn("inline-flex h-3 w-3 rounded-full bg-slate-300", className)}
    />
  );
});

ActivityStateDot.displayName = "ActivityStateDot";

const activityStateLabel = (state: AgentWithContext["activityState"]): string => {
  if (state === "working") return "Working";
  if (state === "idle") return "Idle";
  if (state === "waiting") return "Waiting";
  return "Offline";
};

// ─── Filter Bar ──────────────────────────────────────────────────────

interface FilterBarProps {
  search: string;
  onSearchChange: (v: string) => void;
  boardFilter: string;
  onBoardFilterChange: (v: string) => void;
  statusFilter: string;
  onStatusFilterChange: (v: string) => void;
  timeRange: string;
  onTimeRangeChange: (v: string) => void;
  boards: BoardRead[];
}

const FilterBar = memo(function FilterBar({
  search,
  onSearchChange,
  boardFilter,
  onBoardFilterChange,
  statusFilter,
  onStatusFilterChange,
  timeRange,
  onTimeRangeChange,
  boards,
}: FilterBarProps) {
  const hasFilters =
    search !== "" ||
    boardFilter !== "all" ||
    statusFilter !== "all" ||
    timeRange !== "all";

  return (
    <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        <Filter className="h-4 w-4 text-slate-400" />
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Filters
        </span>
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              onSearchChange("");
              onBoardFilterChange("all");
              onStatusFilterChange("all");
              onTimeRangeChange("all");
            }}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 transition"
          >
            <X className="h-3 w-3" />
            Clear all
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search agents…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:outline-none focus:ring-1 focus:ring-slate-300 transition"
          />
        </div>

        {/* Board filter */}
        <select
          value={boardFilter}
          onChange={(e) => onBoardFilterChange(e.target.value)}
          className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-slate-300 focus:outline-none focus:ring-1 focus:ring-slate-300 transition"
        >
          <option value="all">All boards</option>
          {boards.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => onStatusFilterChange(e.target.value)}
          className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-slate-300 focus:outline-none focus:ring-1 focus:ring-slate-300 transition"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        {/* Time range */}
        <select
          value={timeRange}
          onChange={(e) => onTimeRangeChange(e.target.value)}
          className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-slate-300 focus:outline-none focus:ring-1 focus:ring-slate-300 transition"
        >
          {TIME_RANGES.map((tr) => (
            <option key={tr.value} value={tr.value}>
              {tr.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
});

FilterBar.displayName = "FilterBar";

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
  const visibleEvents = expanded
    ? events
    : events.slice(0, COLLAPSED_LOG_COUNT);

  const lastActivityText = agent.lastActivityAt
    ? formatRelative(agent.lastActivityAt.toISOString())
    : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:shadow-md">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
        <div className="relative flex-shrink-0">
          <div
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold",
              status === "online"
                ? "bg-emerald-100 text-emerald-700"
                : status === "provisioning"
                  ? "bg-amber-100 text-amber-700"
                  : "bg-slate-100 text-slate-500",
            )}
          >
            {agent.name[0]?.toUpperCase() ?? "?"}
          </div>
          <div className="absolute -bottom-0.5 -right-0.5">
            <ActivityStateDot state={agent.activityState} />
          </div>
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
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                agent.activityState === "working"
                  ? "bg-emerald-50 text-emerald-700"
                  : agent.activityState === "idle"
                    ? "bg-amber-50 text-amber-700"
                    : agent.activityState === "waiting"
                      ? "bg-orange-50 text-orange-700"
                      : "bg-slate-50 text-slate-500",
              )}
            >
              {activityStateLabel(agent.activityState)}
            </span>
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
            {lastActivityText && (
              <>
                <span className="text-slate-300">·</span>
                <span>
                  Active {lastActivityText}
                </span>
              </>
            )}
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
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();

  // ── Filter state (URL-persisted) ──────────────────────────────────

  const search = searchParams.get("q") ?? "";
  const boardFilter = searchParams.get("board") ?? "all";
  const statusFilter = searchParams.get("status") ?? "all";
  const timeRange = searchParams.get("range") ?? "all";

  const updateParam = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value === "" || value === "all") {
        params.delete(key);
      } else {
        params.set(key, value);
      }
      const qs = params.toString();
      router.replace(`/agent-logs${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [searchParams, router],
  );

  // ── SSE real-time updates ─────────────────────────────────────────

  const sseEnabled = Boolean(isSignedIn && isAdmin);

  const handleAgentSSE = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as AgentRead;
        // Merge into React Query cache
        queryClient.setQueryData(
          getListAgentsApiV1AgentsGetQueryKey(),
          (old: listAgentsApiV1AgentsGetResponse | undefined) => {
            if (!old || old.status !== 200) return old;
            const items = [...(old.data.items ?? [])];
            const idx = items.findIndex((a) => a.id === data.id);
            if (idx >= 0) {
              items[idx] = { ...items[idx], ...data };
            } else {
              items.push(data);
            }
            return {
              ...old,
              data: { ...old.data, items },
            };
          },
        );
      } catch {
        // ignore parse errors
      }
    },
    [queryClient],
  );

  const handleActivitySSE = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as ActivityEventRead;
        queryClient.setQueryData(
          getListActivityApiV1ActivityGetQueryKey({ limit: ACTIVITY_LIMIT }),
          (old: listActivityApiV1ActivityGetResponse | undefined) => {
            if (!old || old.status !== 200) return old;
            const items = [data, ...(old.data.items ?? [])];
            // Cap to limit
            if (items.length > ACTIVITY_LIMIT) items.length = ACTIVITY_LIMIT;
            return {
              ...old,
              data: { ...old.data, items, total: (old.data.total ?? 0) + 1 },
            };
          },
        );
      } catch {
        // ignore
      }
    },
    [queryClient],
  );

  const { status: agentSSEStatus } = useSSE({
    path: "/api/v1/agents/stream",
    onMessage: handleAgentSSE,
    enabled: sseEnabled,
  });

  const { status: activitySSEStatus } = useSSE({
    path: "/api/v1/activity/task-comments/stream",
    onMessage: handleActivitySSE,
    enabled: sseEnabled,
  });

  const sseConnected =
    agentSSEStatus === "connected" || activitySSEStatus === "connected";
  const sseStatus: SSEStatus =
    agentSSEStatus === "connected" || activitySSEStatus === "connected"
      ? "connected"
      : agentSSEStatus === "connecting" || activitySSEStatus === "connecting"
        ? "connecting"
        : agentSSEStatus === "error" || activitySSEStatus === "error"
          ? "error"
          : "disconnected";

  const pollingInterval = sseConnected
    ? REFETCH_INTERVAL_SSE_MS
    : REFETCH_INTERVAL_MS;

  // ── Data queries ──────────────────────────────────────────────────

  const agentsQuery = useListAgentsApiV1AgentsGet<
    listAgentsApiV1AgentsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: pollingInterval,
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
        refetchInterval: pollingInterval,
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
            if (!existing || task.status === "in_progress") {
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
    const now = Date.now();
    const timeRangeDef = TIME_RANGES.find((t) => t.value === timeRange);
    const timeRangeMs = timeRangeDef?.ms ?? 0;

    // Group events by agent
    const eventsByAgent = new Map<string, ActivityEventRead[]>();
    for (const event of events) {
      if (!event.agent_id) continue;
      // Apply time range filter to events
      if (timeRangeMs > 0) {
        const eventDate = parseDate(event.created_at);
        if (eventDate && now - eventDate.getTime() > timeRangeMs) continue;
      }
      const list = eventsByAgent.get(event.agent_id) ?? [];
      list.push(event);
      eventsByAgent.set(event.agent_id, list);
    }

    return agents
      .filter((a) => !a.is_gateway_main)
      .map((agent) => {
        const agentEvents = eventsByAgent.get(agent.id) ?? [];
        const hasTask = tasksByAgent.has(agent.id);

        // Find most recent activity timestamp
        let lastActivityAt: Date | null = null;
        for (const ev of agentEvents) {
          const d = parseDate(ev.created_at);
          if (d && (!lastActivityAt || d > lastActivityAt)) {
            lastActivityAt = d;
          }
        }
        // Also consider last_seen_at
        const lastSeen = parseDate(agent.last_seen_at);
        if (lastSeen && (!lastActivityAt || lastSeen > lastActivityAt)) {
          lastActivityAt = lastSeen;
        }

        return {
          ...agent,
          boardName: agent.board_id
            ? (boardsById.get(agent.board_id)?.name ?? null)
            : null,
          currentTask: tasksByAgent.get(agent.id) ?? null,
          events: agentEvents,
          activityState: deriveActivityState(agent, hasTask, lastActivityAt),
          lastActivityAt,
        };
      })
      .sort((a, b) => {
        // Sort by activity state first, then status, then name
        const actDiff =
          activityStateOrder(a.activityState) -
          activityStateOrder(b.activityState);
        if (actDiff !== 0) return actDiff;
        const statusDiff =
          agentStatusOrder(a.status) - agentStatusOrder(b.status);
        if (statusDiff !== 0) return statusDiff;
        return a.name.localeCompare(b.name);
      });
  }, [agents, events, boardsById, tasksByAgent, timeRange]);

  // ── Apply filters ─────────────────────────────────────────────────

  const filteredAgents = useMemo<AgentWithContext[]>(() => {
    let result = agentsWithContext;

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          (roleFromAgent(a) ?? "").toLowerCase().includes(q),
      );
    }

    if (boardFilter !== "all") {
      result = result.filter((a) => a.board_id === boardFilter);
    }

    if (statusFilter !== "all") {
      result = result.filter(
        (a) => (a.status ?? "offline").toLowerCase() === statusFilter,
      );
    }

    return result;
  }, [agentsWithContext, search, boardFilter, statusFilter]);

  const onlineCount = useMemo(
    () =>
      agentsWithContext.filter(
        (a) => (a.status ?? "").toLowerCase() === "online",
      ).length,
    [agentsWithContext],
  );

  const workingCount = useMemo(
    () => agentsWithContext.filter((a) => a.activityState === "working").length,
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
                  <SSEIndicator status={sseStatus} />
                  {workingCount > 0 && (
                    <div className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
                      <ActivityStateDot state="working" />
                      {workingCount} working
                    </div>
                  )}
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
                    {filteredAgents.length}
                    {filteredAgents.length !== agentsWithContext.length
                      ? ` / ${agentsWithContext.length}`
                      : ""}{" "}
                    agent{agentsWithContext.length !== 1 ? "s" : ""}
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
            ) : (
              <>
                <FilterBar
                  search={search}
                  onSearchChange={(v) => updateParam("q", v)}
                  boardFilter={boardFilter}
                  onBoardFilterChange={(v) => updateParam("board", v)}
                  statusFilter={statusFilter}
                  onStatusFilterChange={(v) => updateParam("status", v)}
                  timeRange={timeRange}
                  onTimeRangeChange={(v) => updateParam("range", v)}
                  boards={boards}
                />

                {filteredAgents.length === 0 ? (
                  <div className="rounded-xl border border-slate-200 bg-white p-10 text-center shadow-sm">
                    <Bot className="mx-auto h-10 w-10 text-slate-300" />
                    <p className="mt-3 text-sm font-medium text-slate-900">
                      {agentsWithContext.length === 0
                        ? "No agents found"
                        : "No agents match filters"}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {agentsWithContext.length === 0
                        ? "Agents will appear here once they are registered and connected."
                        : "Try adjusting your search or filter criteria."}
                    </p>
                  </div>
                ) : (
                  <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
                    {filteredAgents.map((agent) => (
                      <AgentCard key={agent.id} agent={agent} />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
