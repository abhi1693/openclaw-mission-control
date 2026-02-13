"use client";

export const dynamic = "force-dynamic";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";

import { SignInButton, SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import {
  Activity,
  ArrowUpRight,
  MessageSquare,
  Pause,
  Plus,
  Pencil,
  Play,
  RefreshCcw,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";

import { Markdown } from "@/components/atoms/Markdown";
import { StatusDot } from "@/components/atoms/StatusDot";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { TaskBoard } from "@/components/organisms/TaskBoard";
import {
  DependencyBanner,
  type DependencyBannerDependency,
} from "@/components/molecules/DependencyBanner";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { BoardChatComposer } from "@/components/BoardChatComposer";
import { TaskCustomFieldsEditor } from "./TaskCustomFieldsEditor";
import { buildUrlWithTaskId } from "./task-detail-query";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import DropdownSelect, {
  type DropdownSelectOption,
} from "@/components/ui/dropdown-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/api/mutator";
import { streamAgentsApiV1AgentsStreamGet } from "@/api/generated/agents/agents";
import {
  streamApprovalsApiV1BoardsBoardIdApprovalsStreamGet,
  updateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch,
} from "@/api/generated/approvals/approvals";
import { listActivityApiV1ActivityGet } from "@/api/generated/activity/activity";
import {
  getBoardGroupSnapshotApiV1BoardsBoardIdGroupSnapshotGet,
  getBoardSnapshotApiV1BoardsBoardIdSnapshotGet,
} from "@/api/generated/boards/boards";
import {
  createBoardMemoryApiV1BoardsBoardIdMemoryPost,
  streamBoardMemoryApiV1BoardsBoardIdMemoryStreamGet,
} from "@/api/generated/board-memory/board-memory";
import {
  type getMyMembershipApiV1OrganizationsMeMemberGetResponse,
  useGetMyMembershipApiV1OrganizationsMeMemberGet,
} from "@/api/generated/organizations/organizations";
import {
  createTaskApiV1BoardsBoardIdTasksPost,
  createTaskCommentApiV1BoardsBoardIdTasksTaskIdCommentsPost,
  deleteTaskApiV1BoardsBoardIdTasksTaskIdDelete,
  listTaskCommentsApiV1BoardsBoardIdTasksTaskIdCommentsGet,
  streamTasksApiV1BoardsBoardIdTasksStreamGet,
  updateTaskApiV1BoardsBoardIdTasksTaskIdPatch,
} from "@/api/generated/tasks/tasks";
import {
  type listTagsApiV1TagsGetResponse,
  useListTagsApiV1TagsGet,
} from "@/api/generated/tags/tags";
import {
  type listOrgCustomFieldsApiV1OrganizationsMeCustomFieldsGetResponse,
  useListOrgCustomFieldsApiV1OrganizationsMeCustomFieldsGet,
} from "@/api/generated/org-custom-fields/org-custom-fields";
import type {
  AgentRead,
  ApprovalRead,
  BoardGroupSnapshot,
  BoardMemoryRead,
  BoardRead,
  ActivityEventRead,
  OrganizationMemberRead,
  TaskCardRead,
  TaskCommentRead,
  TaskCustomFieldDefinitionRead,
  TagRead,
  TaskRead,
} from "@/api/generated/model";
import { createExponentialBackoff } from "@/lib/backoff";
import {
  apiDatetimeToMs,
  localDateInputToUtcIso,
  parseApiDatetime,
  toLocalDateInput,
} from "@/lib/datetime";
import {
  DEFAULT_HUMAN_LABEL,
  resolveHumanActorName,
  resolveMemberDisplayName,
} from "@/lib/display-name";
import { cn } from "@/lib/utils";
import { usePageActive } from "@/hooks/usePageActive";
import {
  boardCustomFieldValues,
  canonicalizeCustomFieldValues,
  customFieldPayload,
  customFieldPatchPayload,
  firstMissingRequiredCustomField,
  formatCustomFieldDetailValue,
  isCustomFieldVisible,
  type TaskCustomFieldValues,
} from "./custom-field-utils";

type Board = BoardRead;

type TaskStatus = Exclude<TaskCardRead["status"], undefined>;

type TaskCustomFieldPayload = {
  custom_field_values?: TaskCustomFieldValues;
};

type Task = Omit<
  TaskCardRead,
  "status" | "priority" | "approvals_count" | "approvals_pending_count"
> & {
  status: TaskStatus;
  priority: string;
  approvals_count: number;
  approvals_pending_count: number;
  custom_field_values?: TaskCustomFieldValues | null;
};

type Agent = AgentRead & { status: string };

type TaskComment = TaskCommentRead;

type Approval = ApprovalRead & { status: string };

type BoardChatMessage = BoardMemoryRead;

type LiveFeedEventType =
  | "task.comment"
  | "task.created"
  | "task.updated"
  | "task.status_changed"
  | "board.chat"
  | "board.command"
  | "agent.created"
  | "agent.online"
  | "agent.offline"
  | "agent.updated"
  | "approval.created"
  | "approval.updated"
  | "approval.approved"
  | "approval.rejected";

type LiveFeedItem = {
  id: string;
  created_at: string;
  message: string | null;
  agent_id: string | null;
  actor_name?: string | null;
  task_id: string | null;
  title?: string | null;
  event_type: LiveFeedEventType;
};

const LIVE_FEED_EVENT_TYPES = new Set<LiveFeedEventType>([
  "task.comment",
  "task.created",
  "task.updated",
  "task.status_changed",
  "board.chat",
  "board.command",
  "agent.created",
  "agent.online",
  "agent.offline",
  "agent.updated",
  "approval.created",
  "approval.updated",
  "approval.approved",
  "approval.rejected",
]);

const isLiveFeedEventType = (value: string): value is LiveFeedEventType =>
  LIVE_FEED_EVENT_TYPES.has(value as LiveFeedEventType);

type BoardTaskCreatePayload = Parameters<
  typeof createTaskApiV1BoardsBoardIdTasksPost
>[1] &
  TaskCustomFieldPayload;
type BoardTaskUpdatePayload = Parameters<
  typeof updateTaskApiV1BoardsBoardIdTasksTaskIdPatch
>[2] &
  TaskCustomFieldPayload;

const toLiveFeedFromActivity = (
  event: ActivityEventRead,
): LiveFeedItem | null => {
  if (!isLiveFeedEventType(event.event_type)) {
    return null;
  }
  return {
    id: event.id,
    created_at: event.created_at,
    message: event.message ?? null,
    agent_id: event.agent_id ?? null,
    task_id: event.task_id ?? null,
    title: null,
    event_type: event.event_type,
  };
};

const toLiveFeedFromComment = (comment: TaskCommentRead): LiveFeedItem => ({
  id: comment.id,
  created_at: comment.created_at,
  message: comment.message ?? null,
  agent_id: comment.agent_id ?? null,
  actor_name: null,
  task_id: comment.task_id ?? null,
  title: null,
  event_type: "task.comment",
});

const toLiveFeedFromBoardChat = (memory: BoardChatMessage): LiveFeedItem => {
  const content = (memory.content ?? "").trim();
  const actorName = resolveHumanActorName(memory.source, DEFAULT_HUMAN_LABEL);
  const isCommand = content.startsWith("/");
  return {
    id: `chat:${memory.id}`,
    created_at: memory.created_at,
    message: content || null,
    agent_id: null,
    actor_name: actorName,
    task_id: null,
    title: isCommand ? "Board command" : "Board chat",
    event_type: isCommand ? "board.command" : "board.chat",
  };
};

const normalizeAgentStatus = (value?: string | null): string => {
  const status = (value ?? "").trim().toLowerCase();
  return status || "offline";
};

const humanizeAgentStatus = (value: string): string =>
  value.replace(/_/g, " ").trim() || "offline";

const toLiveFeedFromAgentSnapshot = (agent: Agent): LiveFeedItem => {
  const status = normalizeAgentStatus(agent.status);
  const stamp = agent.last_seen_at ?? agent.updated_at ?? agent.created_at;
  const eventType: LiveFeedEventType =
    status === "online"
      ? "agent.online"
      : status === "offline"
        ? "agent.offline"
        : "agent.updated";
  return {
    id: `agent:${agent.id}:snapshot:${status}:${stamp}`,
    created_at: stamp,
    message: `${agent.name} is ${humanizeAgentStatus(status)}.`,
    agent_id: agent.id,
    actor_name: null,
    task_id: null,
    title: `Agent · ${agent.name}`,
    event_type: eventType,
  };
};

const toLiveFeedFromAgentUpdate = (
  agent: Agent,
  previous: Agent | null,
): LiveFeedItem | null => {
  const nextStatus = normalizeAgentStatus(agent.status);
  const previousStatus = previous
    ? normalizeAgentStatus(previous.status)
    : null;
  const statusChanged =
    previousStatus !== null && nextStatus !== previousStatus;
  const isNew = previous === null;
  const profileChanged =
    Boolean(previous) &&
    (previous?.name !== agent.name ||
      previous?.is_board_lead !== agent.is_board_lead ||
      JSON.stringify(previous?.identity_profile ?? {}) !==
        JSON.stringify(agent.identity_profile ?? {}));

  let eventType: LiveFeedEventType;
  if (isNew) {
    eventType = "agent.created";
  } else if (statusChanged && nextStatus === "online") {
    eventType = "agent.online";
  } else if (statusChanged && nextStatus === "offline") {
    eventType = "agent.offline";
  } else if (statusChanged || profileChanged) {
    eventType = "agent.updated";
  } else {
    return null;
  }

  const stamp = agent.last_seen_at ?? agent.updated_at ?? agent.created_at;
  const message =
    eventType === "agent.created"
      ? `${agent.name} joined this board.`
      : eventType === "agent.online"
        ? `${agent.name} is online.`
        : eventType === "agent.offline"
          ? `${agent.name} is offline.`
          : `${agent.name} updated (${humanizeAgentStatus(nextStatus)}).`;
  return {
    id: `agent:${agent.id}:${eventType}:${stamp}`,
    created_at: stamp,
    message,
    agent_id: agent.id,
    actor_name: null,
    task_id: null,
    title: `Agent · ${agent.name}`,
    event_type: eventType,
  };
};

const humanizeLiveFeedApprovalAction = (value: string): string => {
  const cleaned = value.replace(/[._-]+/g, " ").trim();
  if (!cleaned) return "Approval";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
};

const toLiveFeedFromApproval = (
  approval: ApprovalRead,
  previous: ApprovalRead | null = null,
): LiveFeedItem => {
  const nextStatus = approval.status ?? "pending";
  const previousStatus = previous?.status ?? null;
  const eventType: LiveFeedEventType =
    previousStatus === null
      ? nextStatus === "approved"
        ? "approval.approved"
        : nextStatus === "rejected"
          ? "approval.rejected"
          : "approval.created"
      : nextStatus !== previousStatus
        ? nextStatus === "approved"
          ? "approval.approved"
          : nextStatus === "rejected"
            ? "approval.rejected"
            : "approval.updated"
        : "approval.updated";
  const stamp =
    eventType === "approval.created"
      ? approval.created_at
      : (approval.resolved_at ?? approval.created_at);
  const action = humanizeLiveFeedApprovalAction(approval.action_type);
  const statusText =
    nextStatus === "approved"
      ? "approved"
      : nextStatus === "rejected"
        ? "rejected"
        : "pending";
  const message =
    eventType === "approval.created"
      ? `${action} requested (${approval.confidence}% confidence).`
      : eventType === "approval.approved"
        ? `${action} approved (${approval.confidence}% confidence).`
        : eventType === "approval.rejected"
          ? `${action} rejected (${approval.confidence}% confidence).`
          : `${action} updated (${statusText}, ${approval.confidence}% confidence).`;
  return {
    id: `approval:${approval.id}:${eventType}:${stamp}`,
    created_at: stamp,
    message,
    agent_id: approval.agent_id ?? null,
    actor_name: null,
    task_id: approval.task_id ?? null,
    title: `Approval · ${action}`,
    event_type: eventType,
  };
};

const liveFeedEventLabel = (eventType: LiveFeedEventType): string => {
  if (eventType === "task.comment") return "Comment";
  if (eventType === "task.created") return "Created";
  if (eventType === "task.status_changed") return "Status";
  if (eventType === "board.chat") return "Chat";
  if (eventType === "board.command") return "Command";
  if (eventType === "agent.created") return "Agent";
  if (eventType === "agent.online") return "Online";
  if (eventType === "agent.offline") return "Offline";
  if (eventType === "agent.updated") return "Agent update";
  if (eventType === "approval.created") return "Approval";
  if (eventType === "approval.updated") return "Approval update";
  if (eventType === "approval.approved") return "Approved";
  if (eventType === "approval.rejected") return "Rejected";
  return "Updated";
};

const liveFeedEventPillClass = (eventType: LiveFeedEventType): string => {
  if (eventType === "task.comment") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  if (eventType === "task.created") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (eventType === "task.status_changed") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (eventType === "board.chat") {
    return "border-teal-200 bg-teal-50 text-teal-700";
  }
  if (eventType === "board.command") {
    return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700";
  }
  if (eventType === "agent.created") {
    return "border-violet-200 bg-violet-50 text-violet-700";
  }
  if (eventType === "agent.online") {
    return "border-lime-200 bg-lime-50 text-lime-700";
  }
  if (eventType === "agent.offline") {
    return "border-slate-300 bg-slate-100 text-slate-700";
  }
  if (eventType === "agent.updated") {
    return "border-indigo-200 bg-indigo-50 text-indigo-700";
  }
  if (eventType === "approval.created") {
    return "border-cyan-200 bg-cyan-50 text-cyan-700";
  }
  if (eventType === "approval.updated") {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }
  if (eventType === "approval.approved") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (eventType === "approval.rejected") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  return "border-slate-200 bg-slate-100 text-slate-700";
};

const normalizeTask = (task: TaskCardRead): Task => ({
  ...task,
  status: task.status ?? "inbox",
  priority: task.priority ?? "medium",
  approvals_count: task.approvals_count ?? 0,
  approvals_pending_count: task.approvals_pending_count ?? 0,
});

const normalizeAgent = (agent: AgentRead): Agent => ({
  ...agent,
  status: agent.status ?? "offline",
});

const normalizeApproval = (approval: ApprovalRead): Approval => ({
  ...approval,
  status: approval.status ?? "pending",
});

const normalizeTagColor = (value?: string | null) => {
  const cleaned = (value ?? "").trim().replace(/^#/, "").toLowerCase();
  if (!/^[0-9a-f]{6}$/.test(cleaned)) return "9e9e9e";
  return cleaned;
};

const priorities = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];
const statusOptions = [
  { value: "inbox", label: "Inbox" },
  { value: "in_progress", label: "In progress" },
  { value: "review", label: "Review" },
  { value: "done", label: "Done" },
];

const EMOJI_GLYPHS: Record<string, string> = {
  ":gear:": "⚙️",
  ":sparkles:": "✨",
  ":rocket:": "🚀",
  ":megaphone:": "📣",
  ":chart_with_upwards_trend:": "📈",
  ":bulb:": "💡",
  ":wrench:": "🔧",
  ":shield:": "🛡️",
  ":memo:": "📝",
  ":brain:": "🧠",
};

const SSE_RECONNECT_BACKOFF = {
  baseMs: 1_000,
  factor: 2,
  jitter: 0.2,
  maxMs: 5 * 60_000,
} as const;

const formatShortTimestamp = (value: string) => {
  const date = parseApiDatetime(value);
  if (!date) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

type ToastMessage = {
  id: number;
  message: string;
  tone: "error" | "success";
};

const formatActionError = (err: unknown, fallback: string) => {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return "Read-only access. You do not have permission to make changes.";
    }
    return err.message || fallback;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
};

const resolveBoardAccess = (
  member: OrganizationMemberRead | null,
  boardId?: string | null,
) => {
  if (!member || !boardId) {
    return { canRead: false, canWrite: false };
  }
  if (member.all_boards_write) {
    return { canRead: true, canWrite: true };
  }
  if (member.all_boards_read) {
    return { canRead: true, canWrite: false };
  }
  const entry = member.board_access?.find(
    (access) => access.board_id === boardId,
  );
  if (!entry) {
    return { canRead: false, canWrite: false };
  }
  const canWrite = Boolean(entry.can_write);
  const canRead = Boolean(entry.can_read || entry.can_write);
  return { canRead, canWrite };
};

const TaskCommentCard = memo(function TaskCommentCard({
  comment,
  authorLabel,
}: {
  comment: TaskComment;
  authorLabel: string;
}) {
  const message = (comment.message ?? "").trim();
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{authorLabel}</span>
        <span>{formatShortTimestamp(comment.created_at)}</span>
      </div>
      {message ? (
        <div className="mt-2 select-text cursor-text text-sm leading-relaxed text-slate-900 break-words">
          <Markdown content={message} variant="comment" />
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-900">—</p>
      )}
    </div>
  );
});

TaskCommentCard.displayName = "TaskCommentCard";

const ChatMessageCard = memo(function ChatMessageCard({
  message,
  fallbackSource,
}: {
  message: BoardChatMessage;
  fallbackSource: string;
}) {
  const sourceLabel = resolveHumanActorName(message.source, fallbackSource);
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-900">{sourceLabel}</p>
        <span className="text-xs text-slate-400">
          {formatShortTimestamp(message.created_at)}
        </span>
      </div>
      <div className="mt-2 select-text cursor-text text-sm leading-relaxed text-slate-900 break-words">
        <Markdown content={message.content} variant="basic" />
      </div>
    </div>
  );
});

ChatMessageCard.displayName = "ChatMessageCard";

const LiveFeedCard = memo(function LiveFeedCard({
  item,
  taskTitle,
  authorName,
  authorRole,
  authorAvatar,
  onViewTask,
  isNew,
}: {
  item: LiveFeedItem;
  taskTitle: string;
  authorName: string;
  authorRole?: string | null;
  authorAvatar: string;
  onViewTask?: () => void;
  isNew?: boolean;
}) {
  const message = (item.message ?? "").trim();
  const eventLabel = liveFeedEventLabel(item.event_type);
  const eventPillClass = liveFeedEventPillClass(item.event_type);
  return (
    <div
      className={cn(
        "rounded-xl border p-3 transition-colors duration-300",
        isNew
          ? "border-blue-200 bg-blue-50/70 shadow-sm hover:border-blue-300 motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:slide-in-from-right-2 motion-safe:duration-300"
          : "border-slate-200 bg-white hover:border-slate-300",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700">
          {authorAvatar}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <button
              type="button"
              onClick={onViewTask}
              disabled={!onViewTask}
              className={cn(
                "text-left text-sm font-semibold leading-snug text-slate-900",
                onViewTask
                  ? "cursor-pointer transition hover:text-slate-950 hover:underline"
                  : "cursor-default",
              )}
              title={taskTitle}
              style={{
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {taskTitle}
            </button>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500">
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                eventPillClass,
              )}
            >
              {eventLabel}
            </span>
            <span className="font-medium text-slate-700">{authorName}</span>
            {authorRole ? (
              <>
                <span className="text-slate-300">·</span>
                <span className="text-slate-500">{authorRole}</span>
              </>
            ) : null}
            <span className="text-slate-300">·</span>
            <span className="text-slate-400">
              {formatShortTimestamp(item.created_at)}
            </span>
          </div>
        </div>
      </div>
      {message ? (
        <div className="mt-3 select-text cursor-text text-sm leading-relaxed text-slate-900 break-words">
          <Markdown content={message} variant="basic" />
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500">—</p>
      )}
    </div>
  );
});

LiveFeedCard.displayName = "LiveFeedCard";

export default function BoardDetailPage() {
  const router = useRouter();
  const params = useParams();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const boardIdParam = params?.boardId;
  const boardId = Array.isArray(boardIdParam) ? boardIdParam[0] : boardIdParam;
  const { isSignedIn } = useAuth();
  const isPageActive = usePageActive();
  const taskIdFromUrl = searchParams.get("taskId");

  const membershipQuery = useGetMyMembershipApiV1OrganizationsMeMemberGet<
    getMyMembershipApiV1OrganizationsMeMemberGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
    },
  });
  const tagsQuery = useListTagsApiV1TagsGet<
    listTagsApiV1TagsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
    },
  });
  const tags = useMemo(
    () =>
      tagsQuery.data?.status === 200 ? (tagsQuery.data.data.items ?? []) : [],
    [tagsQuery.data],
  );
  const customFieldDefinitionsQuery =
    useListOrgCustomFieldsApiV1OrganizationsMeCustomFieldsGet<
      listOrgCustomFieldsApiV1OrganizationsMeCustomFieldsGetResponse,
      ApiError
    >({
      query: {
        enabled: Boolean(isSignedIn),
        refetchOnMount: "always",
        retry: false,
      },
    });
  const boardCustomFieldDefinitions = useMemo(() => {
    if (!boardId || customFieldDefinitionsQuery.data?.status !== 200) {
      return [] as TaskCustomFieldDefinitionRead[];
    }
    return (customFieldDefinitionsQuery.data.data ?? [])
      .filter((definition) => (definition.board_ids ?? []).includes(boardId))
      .sort((left, right) =>
        (left.label || left.field_key).localeCompare(
          right.label || right.field_key,
        ),
      );
  }, [boardId, customFieldDefinitionsQuery.data]);

  const boardAccess = useMemo(
    () =>
      resolveBoardAccess(
        membershipQuery.data?.status === 200 ? membershipQuery.data.data : null,
        boardId,
      ),
    [membershipQuery.data, boardId],
  );
  const isOrgAdmin = useMemo(() => {
    const member =
      membershipQuery.data?.status === 200 ? membershipQuery.data.data : null;
    return member ? ["owner", "admin"].includes(member.role) : false;
  }, [membershipQuery.data]);
  const currentUserDisplayName = useMemo(() => {
    const member =
      membershipQuery.data?.status === 200 ? membershipQuery.data.data : null;
    return resolveMemberDisplayName(member, DEFAULT_HUMAN_LABEL);
  }, [membershipQuery.data]);
  const canWrite = boardAccess.canWrite;

  const [board, setBoard] = useState<Board | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [groupSnapshot, setGroupSnapshot] = useState<BoardGroupSnapshot | null>(
    null,
  );
  const [groupSnapshotError, setGroupSnapshotError] = useState<string | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [hasLoadedBoardSnapshot, setHasLoadedBoardSnapshot] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const selectedTaskIdRef = useRef<string | null>(null);
  const openedTaskIdFromUrlRef = useRef<string | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [liveFeed, setLiveFeed] = useState<LiveFeedItem[]>([]);
  const liveFeedRef = useRef<LiveFeedItem[]>([]);
  const liveFeedFlashTimersRef = useRef<Record<string, number>>({});
  const [liveFeedFlashIds, setLiveFeedFlashIds] = useState<
    Record<string, boolean>
  >({});
  const [isLiveFeedHistoryLoading, setIsLiveFeedHistoryLoading] =
    useState(false);
  const [liveFeedHistoryError, setLiveFeedHistoryError] = useState<
    string | null
  >(null);
  const liveFeedHistoryLoadedRef = useRef(false);
  const [isCommentsLoading, setIsCommentsLoading] = useState(false);
  const [commentsError, setCommentsError] = useState<string | null>(null);
  const [isPostingComment, setIsPostingComment] = useState(false);
  const [postCommentError, setPostCommentError] = useState<string | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const tasksRef = useRef<Task[]>([]);
  const approvalsRef = useRef<Approval[]>([]);
  const agentsRef = useRef<Agent[]>([]);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [isApprovalsLoading, setIsApprovalsLoading] = useState(false);
  const [approvalsError, setApprovalsError] = useState<string | null>(null);
  const [approvalsUpdatingId, setApprovalsUpdatingId] = useState<string | null>(
    null,
  );
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<BoardChatMessage[]>([]);
  const [isChatSending, setIsChatSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const chatMessagesRef = useRef<BoardChatMessage[]>([]);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const [isAgentsControlDialogOpen, setIsAgentsControlDialogOpen] =
    useState(false);
  const [agentsControlAction, setAgentsControlAction] = useState<
    "pause" | "resume"
  >("pause");
  const [isAgentsControlSending, setIsAgentsControlSending] = useState(false);
  const [agentsControlError, setAgentsControlError] = useState<string | null>(
    null,
  );
  const [isDeletingTask, setIsDeletingTask] = useState(false);
  const [deleteTaskError, setDeleteTaskError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"board" | "list">("board");
  const [isLiveFeedOpen, setIsLiveFeedOpen] = useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const isLiveFeedOpenRef = useRef(false);
  const toastIdRef = useRef(0);
  const toastTimersRef = useRef<Record<number, number>>({});
  const pushLiveFeed = useCallback((item: LiveFeedItem) => {
    const alreadySeen = liveFeedRef.current.some(
      (existing) => existing.id === item.id,
    );
    setLiveFeed((prev) => {
      if (prev.some((existing) => existing.id === item.id)) {
        return prev;
      }
      const next = [item, ...prev];
      return next.slice(0, 50);
    });

    if (alreadySeen) return;
    if (!isLiveFeedOpenRef.current) return;

    setLiveFeedFlashIds((prev) =>
      prev[item.id] ? prev : { ...prev, [item.id]: true },
    );

    if (typeof window === "undefined") return;
    const existingTimer = liveFeedFlashTimersRef.current[item.id];
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
    }
    liveFeedFlashTimersRef.current[item.id] = window.setTimeout(() => {
      delete liveFeedFlashTimersRef.current[item.id];
      setLiveFeedFlashIds((prev) => {
        if (!prev[item.id]) return prev;
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
    }, 2200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
    const timer = toastTimersRef.current[id];
    if (timer !== undefined) {
      window.clearTimeout(timer);
      delete toastTimersRef.current[id];
    }
  }, []);

  const pushToast = useCallback(
    (message: string, tone: ToastMessage["tone"] = "error") => {
      const trimmed = message.trim();
      if (!trimmed) return;
      const id = toastIdRef.current + 1;
      toastIdRef.current = id;
      setToasts((prev) => [...prev, { id, message: trimmed, tone }]);
      if (typeof window !== "undefined") {
        toastTimersRef.current[id] = window.setTimeout(() => {
          dismissToast(id);
        }, 3500);
      }
    },
    [dismissToast],
  );

  useEffect(() => {
    liveFeedHistoryLoadedRef.current = false;
    setIsLiveFeedHistoryLoading(false);
    setLiveFeedHistoryError(null);
    setLiveFeed([]);
    setLiveFeedFlashIds({});
    if (typeof window !== "undefined") {
      Object.values(liveFeedFlashTimersRef.current).forEach((timerId) => {
        window.clearTimeout(timerId);
      });
    }
    liveFeedFlashTimersRef.current = {};
  }, [boardId]);

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined") {
        Object.values(liveFeedFlashTimersRef.current).forEach((timerId) => {
          window.clearTimeout(timerId);
        });
      }
      liveFeedFlashTimersRef.current = {};
    };
  }, []);

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined") {
        Object.values(toastTimersRef.current).forEach((timerId) => {
          window.clearTimeout(timerId);
        });
      }
      toastTimersRef.current = {};
    };
  }, []);

  useEffect(() => {
    if (!isLiveFeedOpen) return;
    if (!isSignedIn || !boardId) return;
    if (isLoading) return;
    if (liveFeedHistoryLoadedRef.current) return;

    let cancelled = false;
    setIsLiveFeedHistoryLoading(true);
    setLiveFeedHistoryError(null);

    const fetchHistory = async () => {
      try {
        const sourceTasks =
          tasksRef.current.length > 0 ? tasksRef.current : tasks;
        const sourceApprovals =
          approvalsRef.current.length > 0 ? approvalsRef.current : approvals;
        const sourceAgents =
          agentsRef.current.length > 0 ? agentsRef.current : agents;
        const sourceChatMessages =
          chatMessagesRef.current.length > 0
            ? chatMessagesRef.current
            : chatMessages;
        const boardTaskIds = new Set(sourceTasks.map((task) => task.id));
        const collected: LiveFeedItem[] = [];
        const seen = new Set<string>();
        const limit = 200;
        const recentChatMessages = [...sourceChatMessages]
          .sort((a, b) => {
            const aTime = apiDatetimeToMs(a.created_at) ?? 0;
            const bTime = apiDatetimeToMs(b.created_at) ?? 0;
            return bTime - aTime;
          })
          .slice(0, 50);
        for (const memory of recentChatMessages) {
          const chatItem = toLiveFeedFromBoardChat(memory);
          if (seen.has(chatItem.id)) continue;
          seen.add(chatItem.id);
          collected.push(chatItem);
          if (collected.length >= 200) break;
        }
        for (const agent of sourceAgents) {
          if (collected.length >= 200) break;
          const agentItem = toLiveFeedFromAgentSnapshot(agent);
          if (seen.has(agentItem.id)) continue;
          seen.add(agentItem.id);
          collected.push(agentItem);
          if (collected.length >= 200) break;
        }
        for (const approval of sourceApprovals) {
          if (collected.length >= 200) break;
          const approvalItem = toLiveFeedFromApproval(approval);
          if (seen.has(approvalItem.id)) continue;
          seen.add(approvalItem.id);
          collected.push(approvalItem);
          if (collected.length >= 200) break;
        }

        for (
          let offset = 0;
          collected.length < 200 && offset < 1000;
          offset += limit
        ) {
          const result = await listActivityApiV1ActivityGet({
            limit,
            offset,
          });
          if (cancelled) return;
          if (result.status !== 200) {
            throw new Error("Unable to load live feed.");
          }
          const items = result.data.items ?? [];
          for (const event of items) {
            const mapped = toLiveFeedFromActivity(event);
            if (!mapped?.task_id) continue;
            if (!boardTaskIds.has(mapped.task_id)) continue;
            if (seen.has(mapped.id)) continue;
            seen.add(mapped.id);
            collected.push(mapped);
            if (collected.length >= 200) break;
          }
          if (collected.length >= 200 || items.length < limit) {
            break;
          }
        }
        liveFeedHistoryLoadedRef.current = true;

        setLiveFeed((prev) => {
          const map = new Map<string, LiveFeedItem>();
          [...prev, ...collected].forEach((item) => map.set(item.id, item));
          const merged = [...map.values()];
          merged.sort((a, b) => {
            const aTime = apiDatetimeToMs(a.created_at) ?? 0;
            const bTime = apiDatetimeToMs(b.created_at) ?? 0;
            return bTime - aTime;
          });
          return merged.slice(0, 50);
        });
      } catch (err) {
        if (cancelled) return;
        setLiveFeedHistoryError(
          err instanceof Error ? err.message : "Unable to load live feed.",
        );
      } finally {
        if (cancelled) return;
        setIsLiveFeedHistoryLoading(false);
      }
    };

    void fetchHistory();
    return () => {
      cancelled = true;
    };
  }, [
    agents,
    approvals,
    boardId,
    chatMessages,
    isLiveFeedOpen,
    isLoading,
    isSignedIn,
    tasks,
  ]);

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("medium");
  const [createDueDate, setCreateDueDate] = useState("");
  const [createTagIds, setCreateTagIds] = useState<string[]>([]);
  const [createCustomFieldValues, setCreateCustomFieldValues] =
    useState<TaskCustomFieldValues>({});
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editStatus, setEditStatus] = useState<TaskStatus>("inbox");
  const [editPriority, setEditPriority] = useState("medium");
  const [editDueDate, setEditDueDate] = useState("");
  const [editAssigneeId, setEditAssigneeId] = useState("");
  const [editTagIds, setEditTagIds] = useState<string[]>([]);
  const [editDependsOnTaskIds, setEditDependsOnTaskIds] = useState<string[]>(
    [],
  );
  const [editCustomFieldValues, setEditCustomFieldValues] =
    useState<TaskCustomFieldValues>({});
  const [isSavingTask, setIsSavingTask] = useState(false);
  const [saveTaskError, setSaveTaskError] = useState<string | null>(null);

  const isSidePanelOpen = isDetailOpen || isChatOpen || isLiveFeedOpen;
  const defaultCreateCustomFieldValues = useMemo(
    () => boardCustomFieldValues(boardCustomFieldDefinitions, {}),
    [boardCustomFieldDefinitions],
  );
  const selectedTaskCustomFieldValues = useMemo(
    () =>
      boardCustomFieldValues(
        boardCustomFieldDefinitions,
        selectedTask?.custom_field_values,
      ),
    [boardCustomFieldDefinitions, selectedTask?.custom_field_values],
  );

  useEffect(() => {
    setCreateCustomFieldValues((prev) =>
      boardCustomFieldValues(boardCustomFieldDefinitions, prev),
    );
  }, [boardCustomFieldDefinitions]);

  const titleLabel = useMemo(
    () => (board ? `${board.name} board` : "Board"),
    [board],
  );

  useEffect(() => {
    if (!isSidePanelOpen) return;

    const { body, documentElement } = document;
    const originalHtmlOverflow = documentElement.style.overflow;
    const originalBodyOverflow = body.style.overflow;
    const originalBodyPaddingRight = body.style.paddingRight;

    const scrollbarWidth = window.innerWidth - documentElement.clientWidth;

    documentElement.style.overflow = "hidden";
    body.style.overflow = "hidden";
    if (scrollbarWidth > 0) {
      body.style.paddingRight = `${scrollbarWidth}px`;
    }

    return () => {
      documentElement.style.overflow = originalHtmlOverflow;
      body.style.overflow = originalBodyOverflow;
      body.style.paddingRight = originalBodyPaddingRight;
    };
  }, [isSidePanelOpen]);

  const latestTaskTimestamp = (items: Task[]) => {
    let latestTime = 0;
    items.forEach((task) => {
      const value = task.updated_at ?? task.created_at;
      if (!value) return;
      const time = apiDatetimeToMs(value);
      if (time !== null && time > latestTime) {
        latestTime = time;
      }
    });
    return latestTime ? new Date(latestTime).toISOString() : null;
  };

  const latestApprovalTimestamp = (items: Approval[]) => {
    let latestTime = 0;
    items.forEach((approval) => {
      const value = approval.resolved_at ?? approval.created_at;
      if (!value) return;
      const time = apiDatetimeToMs(value);
      if (time !== null && time > latestTime) {
        latestTime = time;
      }
    });
    return latestTime ? new Date(latestTime).toISOString() : null;
  };

  const latestAgentTimestamp = (items: Agent[]) => {
    let latestTime = 0;
    items.forEach((agent) => {
      const value = agent.updated_at ?? agent.last_seen_at;
      if (!value) return;
      const time = apiDatetimeToMs(value);
      if (time !== null && time > latestTime) {
        latestTime = time;
      }
    });
    return latestTime ? new Date(latestTime).toISOString() : null;
  };

  const loadBoard = useCallback(async () => {
    if (!isSignedIn || !boardId) return;
    setHasLoadedBoardSnapshot(false);
    setIsLoading(true);
    setIsApprovalsLoading(true);
    setError(null);
    setApprovalsError(null);
    setChatError(null);
    setGroupSnapshotError(null);
    try {
      const snapshotResult =
        await getBoardSnapshotApiV1BoardsBoardIdSnapshotGet(boardId);
      if (snapshotResult.status !== 200) {
        throw new Error("Unable to load board snapshot.");
      }
      const snapshot = snapshotResult.data;
      setBoard(snapshot.board);
      setTasks((snapshot.tasks ?? []).map(normalizeTask));
      setAgents((snapshot.agents ?? []).map(normalizeAgent));
      setApprovals((snapshot.approvals ?? []).map(normalizeApproval));
      setChatMessages(snapshot.chat_messages ?? []);

      try {
        const groupResult =
          await getBoardGroupSnapshotApiV1BoardsBoardIdGroupSnapshotGet(
            boardId,
            {
              include_self: false,
              include_done: false,
              per_board_task_limit: 5,
            },
          );
        if (groupResult.status === 200) {
          setGroupSnapshot(groupResult.data);
        } else {
          setGroupSnapshot(null);
        }
      } catch (groupErr) {
        const message =
          groupErr instanceof Error
            ? groupErr.message
            : "Unable to load board group snapshot.";
        setGroupSnapshotError(message);
        setGroupSnapshot(null);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Something went wrong.";
      setError(message);
      setApprovalsError(message);
      setChatError(message);
      setGroupSnapshotError(message);
      setGroupSnapshot(null);
    } finally {
      setIsLoading(false);
      setIsApprovalsLoading(false);
      setHasLoadedBoardSnapshot(true);
    }
  }, [boardId, isSignedIn]);

  useEffect(() => {
    void loadBoard();
  }, [loadBoard]);

  useEffect(() => {
    tasksRef.current = tasks;
  }, [tasks]);

  useEffect(() => {
    approvalsRef.current = approvals;
  }, [approvals]);

  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  useEffect(() => {
    selectedTaskIdRef.current = selectedTask?.id ?? null;
  }, [selectedTask?.id]);

  useEffect(() => {
    chatMessagesRef.current = chatMessages;
  }, [chatMessages]);

  useEffect(() => {
    liveFeedRef.current = liveFeed;
  }, [liveFeed]);

  useEffect(() => {
    isLiveFeedOpenRef.current = isLiveFeedOpen;
  }, [isLiveFeedOpen]);

  useEffect(() => {
    if (!isChatOpen) return;
    const timeout = window.setTimeout(() => {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, 50);
    return () => window.clearTimeout(timeout);
  }, [chatMessages, isChatOpen]);

  const latestChatTimestamp = (items: BoardChatMessage[]) => {
    if (!items.length) return undefined;
    const latest = items.reduce((max, item) => {
      const ts = apiDatetimeToMs(item.created_at);
      return ts === null ? max : Math.max(max, ts);
    }, 0);
    if (!latest) return undefined;
    return new Date(latest).toISOString();
  };

  const lastAgentControlCommand = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
      const value = (chatMessages[i]?.content ?? "").trim().toLowerCase();
      if (value === "/pause" || value === "/resume") {
        return value;
      }
    }
    return null;
  }, [chatMessages]);

  const isAgentsPaused = lastAgentControlCommand === "/pause";

  useEffect(() => {
    if (!isPageActive) return;
    if (!isSignedIn || !boardId || !board) return;
    if (!isChatOpen && !isLiveFeedOpen) return;
    let isCancelled = false;
    const abortController = new AbortController();
    const backoff = createExponentialBackoff(SSE_RECONNECT_BACKOFF);
    let reconnectTimeout: number | undefined;

    const connect = async () => {
      try {
        const since = latestChatTimestamp(chatMessagesRef.current);
        const params = { is_chat: true, ...(since ? { since } : {}) };
        const streamResult =
          await streamBoardMemoryApiV1BoardsBoardIdMemoryStreamGet(
            boardId,
            params,
            {
              headers: { Accept: "text/event-stream" },
              signal: abortController.signal,
            },
          );
        if (streamResult.status !== 200) {
          throw new Error("Unable to connect board chat stream.");
        }
        const response = streamResult.data as Response;
        if (!(response instanceof Response) || !response.body) {
          throw new Error("Unable to connect board chat stream.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value && value.length) {
            // Consider the stream "healthy" once we receive any bytes (including pings),
            // then reset the backoff for future reconnects.
            backoff.reset();
          }
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const lines = raw.split("\n");
            let eventType = "message";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                data += line.slice(5).trim();
              }
            }
            if (eventType === "memory" && data) {
              try {
                const payload = JSON.parse(data) as {
                  memory?: BoardChatMessage;
                };
                if (payload.memory?.tags?.includes("chat")) {
                  pushLiveFeed(toLiveFeedFromBoardChat(payload.memory));
                  setChatMessages((prev) => {
                    const exists = prev.some(
                      (item) => item.id === payload.memory?.id,
                    );
                    if (exists) return prev;
                    const next = [...prev, payload.memory as BoardChatMessage];
                    next.sort((a, b) => {
                      const aTime = apiDatetimeToMs(a.created_at) ?? 0;
                      const bTime = apiDatetimeToMs(b.created_at) ?? 0;
                      return aTime - bTime;
                    });
                    return next;
                  });
                }
              } catch {
                // ignore malformed
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch {
        // Reconnect handled below.
      }

      if (!isCancelled) {
        if (reconnectTimeout !== undefined) {
          window.clearTimeout(reconnectTimeout);
        }
        const delay = backoff.nextDelayMs();
        reconnectTimeout = window.setTimeout(() => {
          reconnectTimeout = undefined;
          void connect();
        }, delay);
      }
    };

    void connect();
    return () => {
      isCancelled = true;
      abortController.abort();
      if (reconnectTimeout !== undefined) {
        window.clearTimeout(reconnectTimeout);
      }
    };
  }, [
    board,
    boardId,
    isChatOpen,
    isLiveFeedOpen,
    isPageActive,
    isSignedIn,
    pushLiveFeed,
  ]);

  useEffect(() => {
    if (!isPageActive) return;
    if (!isSignedIn || !boardId || !board) return;
    let isCancelled = false;
    const abortController = new AbortController();
    const backoff = createExponentialBackoff(SSE_RECONNECT_BACKOFF);
    let reconnectTimeout: number | undefined;

    const connect = async () => {
      try {
        const since = latestApprovalTimestamp(approvalsRef.current);
        const streamResult =
          await streamApprovalsApiV1BoardsBoardIdApprovalsStreamGet(
            boardId,
            since ? { since } : undefined,
            {
              headers: { Accept: "text/event-stream" },
              signal: abortController.signal,
            },
          );
        if (streamResult.status !== 200) {
          throw new Error("Unable to connect approvals stream.");
        }
        const response = streamResult.data as Response;
        if (!(response instanceof Response) || !response.body) {
          throw new Error("Unable to connect approvals stream.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value && value.length) {
            backoff.reset();
          }
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const lines = raw.split("\n");
            let eventType = "message";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                data += line.slice(5).trim();
              }
            }
            if (eventType === "approval" && data) {
              try {
                const payload = JSON.parse(data) as {
                  approval?: ApprovalRead;
                  task_counts?:
                    | {
                        task_id?: string;
                        approvals_count?: number;
                        approvals_pending_count?: number;
                      }
                    | Array<{
                        task_id?: string;
                        approvals_count?: number;
                        approvals_pending_count?: number;
                      }>;
                  pending_approvals_count?: number;
                };
                if (payload.approval) {
                  const normalized = normalizeApproval(payload.approval);
                  const previousApproval =
                    approvalsRef.current.find(
                      (item) => item.id === normalized.id,
                    ) ?? null;
                  pushLiveFeed(
                    toLiveFeedFromApproval(normalized, previousApproval),
                  );
                  setApprovals((prev) => {
                    const index = prev.findIndex(
                      (item) => item.id === normalized.id,
                    );
                    if (index === -1) {
                      return [normalized, ...prev];
                    }
                    const next = [...prev];
                    next[index] = {
                      ...next[index],
                      ...normalized,
                    };
                    return next;
                  });
                }
                const taskCounts = Array.isArray(payload.task_counts)
                  ? payload.task_counts
                  : payload.task_counts
                    ? [payload.task_counts]
                    : [];
                if (taskCounts.length > 0) {
                  setTasks((prev) => {
                    const countsByTaskId = new Map(
                      taskCounts
                        .filter((row) => Boolean(row.task_id))
                        .map((row) => [row.task_id as string, row]),
                    );
                    return prev.map((task) => {
                      const counts = countsByTaskId.get(task.id);
                      if (!counts) return task;
                      return {
                        ...task,
                        approvals_count:
                          counts.approvals_count ?? task.approvals_count,
                        approvals_pending_count:
                          counts.approvals_pending_count ??
                          task.approvals_pending_count,
                      };
                    });
                  });
                }
              } catch {
                // Ignore malformed payloads.
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch {
        // Reconnect handled below.
      }

      if (!isCancelled) {
        if (reconnectTimeout !== undefined) {
          window.clearTimeout(reconnectTimeout);
        }
        const delay = backoff.nextDelayMs();
        reconnectTimeout = window.setTimeout(() => {
          reconnectTimeout = undefined;
          void connect();
        }, delay);
      }
    };

    void connect();
    return () => {
      isCancelled = true;
      abortController.abort();
      if (reconnectTimeout !== undefined) {
        window.clearTimeout(reconnectTimeout);
      }
    };
  }, [board, boardId, isPageActive, isSignedIn, pushLiveFeed]);

  useEffect(() => {
    if (!selectedTask) {
      setEditTitle("");
      setEditDescription("");
      setEditStatus("inbox");
      setEditPriority("medium");
      setEditDueDate("");
      setEditAssigneeId("");
      setEditTagIds([]);
      setEditDependsOnTaskIds([]);
      setEditCustomFieldValues(
        boardCustomFieldValues(boardCustomFieldDefinitions, {}),
      );
      setSaveTaskError(null);
      return;
    }
    setEditTitle(selectedTask.title);
    setEditDescription(selectedTask.description ?? "");
    setEditStatus(selectedTask.status);
    setEditPriority(selectedTask.priority);
    setEditDueDate(toLocalDateInput(selectedTask.due_at));
    setEditAssigneeId(selectedTask.assigned_agent_id ?? "");
    setEditTagIds(selectedTask.tag_ids ?? []);
    setEditDependsOnTaskIds(selectedTask.depends_on_task_ids ?? []);
    setEditCustomFieldValues(
      boardCustomFieldValues(
        boardCustomFieldDefinitions,
        selectedTask.custom_field_values,
      ),
    );
    setSaveTaskError(null);
  }, [boardCustomFieldDefinitions, selectedTask]);

  useEffect(() => {
    if (!isPageActive) return;
    if (!isSignedIn || !boardId || !board) return;
    let isCancelled = false;
    const abortController = new AbortController();
    const backoff = createExponentialBackoff(SSE_RECONNECT_BACKOFF);
    let reconnectTimeout: number | undefined;

    const connect = async () => {
      try {
        const since = latestTaskTimestamp(tasksRef.current);
        const streamResult = await streamTasksApiV1BoardsBoardIdTasksStreamGet(
          boardId,
          since ? { since } : undefined,
          {
            headers: { Accept: "text/event-stream" },
            signal: abortController.signal,
          },
        );
        if (streamResult.status !== 200) {
          throw new Error("Unable to connect task stream.");
        }
        const response = streamResult.data as Response;
        if (!(response instanceof Response) || !response.body) {
          throw new Error("Unable to connect task stream.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value && value.length) {
            backoff.reset();
          }
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const lines = raw.split("\n");
            let eventType = "message";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                data += line.slice(5).trim();
              }
            }
            if (eventType === "task" && data) {
              try {
                const payload = JSON.parse(data) as {
                  type?: string;
                  activity?: ActivityEventRead;
                  task?: TaskRead;
                  comment?: TaskCommentRead;
                };
                const liveEvent = payload.activity
                  ? toLiveFeedFromActivity(payload.activity)
                  : payload.type === "task.comment" && payload.comment
                    ? toLiveFeedFromComment(payload.comment)
                    : null;
                if (liveEvent) {
                  pushLiveFeed(liveEvent);
                }
                if (
                  payload.comment?.task_id &&
                  payload.type === "task.comment"
                ) {
                  setComments((prev) => {
                    if (
                      selectedTaskIdRef.current !== payload.comment?.task_id
                    ) {
                      return prev;
                    }
                    const exists = prev.some(
                      (item) => item.id === payload.comment?.id,
                    );
                    if (exists) {
                      return prev;
                    }
                    const createdMs = apiDatetimeToMs(
                      payload.comment?.created_at,
                    );
                    if (prev.length === 0 || createdMs === null) {
                      return [payload.comment as TaskComment, ...prev];
                    }
                    const first = prev[0];
                    const firstMs = apiDatetimeToMs(first?.created_at);
                    if (firstMs !== null && createdMs >= firstMs) {
                      return [payload.comment as TaskComment, ...prev];
                    }
                    const last = prev[prev.length - 1];
                    const lastMs = apiDatetimeToMs(last?.created_at);
                    if (lastMs !== null && createdMs <= lastMs) {
                      return [...prev, payload.comment as TaskComment];
                    }
                    const next = [...prev, payload.comment as TaskComment];
                    next.sort((a, b) => {
                      const aTime = apiDatetimeToMs(a.created_at) ?? 0;
                      const bTime = apiDatetimeToMs(b.created_at) ?? 0;
                      return bTime - aTime;
                    });
                    return next;
                  });
                } else if (payload.task) {
                  const incomingTask = payload.task;
                  setTasks((prev) => {
                    const index = prev.findIndex(
                      (item) => item.id === incomingTask.id,
                    );
                    if (index === -1) {
                      const assignee = incomingTask.assigned_agent_id
                        ? (agentsRef.current.find(
                            (agent) =>
                              agent.id === incomingTask.assigned_agent_id,
                          )?.name ?? null)
                        : null;
                      const created = normalizeTask({
                        ...incomingTask,
                        assignee,
                        approvals_count: 0,
                        approvals_pending_count: 0,
                      } as TaskCardRead);
                      return [created, ...prev];
                    }
                    const next = [...prev];
                    const existing = next[index];
                    const assignee = incomingTask.assigned_agent_id
                      ? (agentsRef.current.find(
                          (agent) =>
                            agent.id === incomingTask.assigned_agent_id,
                        )?.name ?? null)
                      : null;
                    const updated = normalizeTask({
                      ...existing,
                      ...incomingTask,
                      assignee,
                      approvals_count: existing.approvals_count,
                      approvals_pending_count: existing.approvals_pending_count,
                    } as TaskCardRead);
                    next[index] = { ...existing, ...updated };
                    return next;
                  });
                  if (selectedTaskIdRef.current === incomingTask.id) {
                    setSelectedTask((prev) => {
                      if (!prev || prev.id !== incomingTask.id) {
                        return prev;
                      }
                      return {
                        ...prev,
                        ...incomingTask,
                        custom_field_values:
                          incomingTask.custom_field_values !== undefined
                            ? incomingTask.custom_field_values
                            : prev.custom_field_values,
                      };
                    });
                  }
                }
              } catch {
                // Ignore malformed payloads.
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch {
        // Reconnect handled below.
      }

      if (!isCancelled) {
        if (reconnectTimeout !== undefined) {
          window.clearTimeout(reconnectTimeout);
        }
        const delay = backoff.nextDelayMs();
        reconnectTimeout = window.setTimeout(() => {
          reconnectTimeout = undefined;
          void connect();
        }, delay);
      }
    };

    void connect();
    return () => {
      isCancelled = true;
      abortController.abort();
      if (reconnectTimeout !== undefined) {
        window.clearTimeout(reconnectTimeout);
      }
    };
  }, [board, boardId, isPageActive, isSignedIn, pushLiveFeed]);

  useEffect(() => {
    if (!isPageActive) return;
    if (!isSignedIn || !boardId || !isOrgAdmin) return;
    let isCancelled = false;
    const abortController = new AbortController();
    const backoff = createExponentialBackoff(SSE_RECONNECT_BACKOFF);
    let reconnectTimeout: number | undefined;

    const connect = async () => {
      try {
        const since = latestAgentTimestamp(agentsRef.current);
        const streamResult = await streamAgentsApiV1AgentsStreamGet(
          {
            board_id: boardId,
            since: since ?? null,
          },
          {
            headers: { Accept: "text/event-stream" },
            signal: abortController.signal,
          },
        );
        if (streamResult.status !== 200) {
          throw new Error("Unable to connect agent stream.");
        }
        const response = streamResult.data as Response;
        if (!(response instanceof Response) || !response.body) {
          throw new Error("Unable to connect agent stream.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value && value.length) {
            backoff.reset();
          }
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const lines = raw.split("\n");
            let eventType = "message";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                data += line.slice(5).trim();
              }
            }
            if (eventType === "agent" && data) {
              try {
                const payload = JSON.parse(data) as { agent?: AgentRead };
                if (payload.agent) {
                  const normalized = normalizeAgent(payload.agent);
                  const previousAgent =
                    agentsRef.current.find(
                      (item) => item.id === normalized.id,
                    ) ?? null;
                  const liveEvent = toLiveFeedFromAgentUpdate(
                    normalized,
                    previousAgent,
                  );
                  if (liveEvent) {
                    pushLiveFeed(liveEvent);
                  }
                  setAgents((prev) => {
                    const index = prev.findIndex(
                      (item) => item.id === normalized.id,
                    );
                    if (index === -1) {
                      return [normalized, ...prev];
                    }
                    const next = [...prev];
                    next[index] = {
                      ...next[index],
                      ...normalized,
                    };
                    return next;
                  });
                }
              } catch {
                // Ignore malformed payloads.
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch {
        // Reconnect handled below.
      }

      if (!isCancelled) {
        if (reconnectTimeout !== undefined) {
          window.clearTimeout(reconnectTimeout);
        }
        const delay = backoff.nextDelayMs();
        reconnectTimeout = window.setTimeout(() => {
          reconnectTimeout = undefined;
          void connect();
        }, delay);
      }
    };

    void connect();
    return () => {
      isCancelled = true;
      abortController.abort();
      if (reconnectTimeout !== undefined) {
        window.clearTimeout(reconnectTimeout);
      }
    };
  }, [board, boardId, isOrgAdmin, isPageActive, isSignedIn, pushLiveFeed]);

  const resetForm = () => {
    setTitle("");
    setDescription("");
    setPriority("medium");
    setCreateDueDate("");
    setCreateTagIds([]);
    setCreateCustomFieldValues(defaultCreateCustomFieldValues);
    setCreateError(null);
  };

  const handleCreateTask = async () => {
    if (!isSignedIn || !boardId) return;
    const trimmed = title.trim();
    if (!trimmed) {
      setCreateError("Add a task title to continue.");
      return;
    }
    const createCustomFieldPayload = customFieldPayload(
      boardCustomFieldDefinitions,
      createCustomFieldValues,
    );
    const missingRequiredCustomField = firstMissingRequiredCustomField(
      boardCustomFieldDefinitions,
      createCustomFieldPayload,
    );
    if (missingRequiredCustomField) {
      setCreateError(
        `Custom field "${missingRequiredCustomField}" is required.`,
      );
      return;
    }
    setIsCreating(true);
    setCreateError(null);
    try {
      const payload: BoardTaskCreatePayload = {
        title: trimmed,
        description: description.trim() || null,
        status: "inbox",
        priority,
        due_at: localDateInputToUtcIso(createDueDate),
        tag_ids: createTagIds,
        custom_field_values: createCustomFieldPayload,
      };
      const result = await createTaskApiV1BoardsBoardIdTasksPost(
        boardId,
        payload,
      );
      if (result.status !== 200) throw new Error("Unable to create task.");

      const created = normalizeTask({
        ...result.data,
        assignee: result.data.assigned_agent_id
          ? (assigneeById.get(result.data.assigned_agent_id) ?? null)
          : null,
        approvals_count: 0,
        approvals_pending_count: 0,
      } as TaskCardRead);
      setTasks((prev) => [created, ...prev]);
      setIsDialogOpen(false);
      resetForm();
    } catch (err) {
      const message = formatActionError(err, "Something went wrong.");
      setCreateError(message);
      pushToast(message);
    } finally {
      setIsCreating(false);
    }
  };

  const postBoardChatMessage = useCallback(
    async (content: string): Promise<{ ok: boolean; error: string | null }> => {
      if (!isSignedIn || !boardId) {
        return { ok: false, error: "Sign in to send messages." };
      }
      const trimmed = content.trim();
      if (!trimmed) return { ok: false, error: null };

      try {
        const result = await createBoardMemoryApiV1BoardsBoardIdMemoryPost(
          boardId,
          {
            content: trimmed,
            tags: ["chat"],
            source: currentUserDisplayName,
          },
        );
        if (result.status !== 200) {
          throw new Error("Unable to send message.");
        }
        const created = result.data;
        if (created.tags?.includes("chat")) {
          pushLiveFeed(toLiveFeedFromBoardChat(created));
          setChatMessages((prev) => {
            const exists = prev.some((item) => item.id === created.id);
            if (exists) return prev;
            const next = [...prev, created];
            next.sort((a, b) => {
              const aTime = apiDatetimeToMs(a.created_at) ?? 0;
              const bTime = apiDatetimeToMs(b.created_at) ?? 0;
              return aTime - bTime;
            });
            return next;
          });
        }
        return { ok: true, error: null };
      } catch (err) {
        const message = formatActionError(err, "Unable to send message.");
        return { ok: false, error: message };
      }
    },
    [boardId, currentUserDisplayName, isSignedIn, pushLiveFeed],
  );

  const handleSendChat = useCallback(
    async (content: string): Promise<boolean> => {
      const trimmed = content.trim();
      if (!trimmed) return false;
      setIsChatSending(true);
      setChatError(null);
      try {
        const result = await postBoardChatMessage(trimmed);
        if (!result.ok) {
          if (result.error) {
            setChatError(result.error);
            pushToast(result.error);
          }
          return false;
        }
        return true;
      } finally {
        setIsChatSending(false);
      }
    },
    [postBoardChatMessage, pushToast],
  );

  const openAgentsControlDialog = (action: "pause" | "resume") => {
    setAgentsControlAction(action);
    setAgentsControlError(null);
    setIsAgentsControlDialogOpen(true);
  };

  const handleConfirmAgentsControl = useCallback(async () => {
    const command = agentsControlAction === "pause" ? "/pause" : "/resume";
    setIsAgentsControlSending(true);
    setAgentsControlError(null);
    try {
      const result = await postBoardChatMessage(command);
      if (!result.ok) {
        const message = result.error ?? `Unable to send ${command} command.`;
        setAgentsControlError(message);
        pushToast(message);
        return;
      }
      setIsAgentsControlDialogOpen(false);
    } finally {
      setIsAgentsControlSending(false);
    }
  }, [agentsControlAction, postBoardChatMessage, pushToast]);

  const assigneeById = useMemo(() => {
    const map = new Map<string, string>();
    agents
      .filter((agent) => !boardId || agent.board_id === boardId)
      .forEach((agent) => {
        map.set(agent.id, agent.name);
      });
    return map;
  }, [agents, boardId]);

  const taskTitleById = useMemo(() => {
    const map = new Map<string, string>();
    tasks.forEach((task) => {
      map.set(task.id, task.title);
    });
    return map;
  }, [tasks]);

  const taskById = useMemo(() => {
    const map = new Map<string, Task>();
    tasks.forEach((task) => {
      map.set(task.id, task);
    });
    return map;
  }, [tasks]);

  const orderedLiveFeed = useMemo(() => {
    return [...liveFeed].sort((a, b) => {
      const aTime = apiDatetimeToMs(a.created_at) ?? 0;
      const bTime = apiDatetimeToMs(b.created_at) ?? 0;
      return bTime - aTime;
    });
  }, [liveFeed]);

  const assignableAgents = useMemo(
    () => agents.filter((agent) => !agent.is_board_lead),
    [agents],
  );
  const boardChatMentionSuggestions = useMemo(() => {
    const options = new Set<string>(["lead"]);
    agents.forEach((agent) => {
      if (agent.name) {
        options.add(agent.name);
      }
    });
    return [...options];
  }, [agents]);

  const tagById = useMemo(() => {
    const map = new Map<string, TagRead>();
    tags.forEach((tag) => {
      map.set(tag.id, tag);
    });
    return map;
  }, [tags]);

  const createTagOptions = useMemo<DropdownSelectOption[]>(() => {
    const selected = new Set(createTagIds);
    return tags.map((tag) => ({
      value: tag.id,
      label: `${tag.name} (#${normalizeTagColor(tag.color).toUpperCase()})`,
      disabled: selected.has(tag.id),
    }));
  }, [createTagIds, tags]);

  const editTagOptions = useMemo<DropdownSelectOption[]>(() => {
    const selected = new Set(editTagIds);
    return tags.map((tag) => ({
      value: tag.id,
      label: `${tag.name} (#${normalizeTagColor(tag.color).toUpperCase()})`,
      disabled: selected.has(tag.id),
    }));
  }, [editTagIds, tags]);

  const dependencyOptions = useMemo<DropdownSelectOption[]>(() => {
    if (!selectedTask) return [];
    const alreadySelected = new Set(editDependsOnTaskIds);
    return tasks
      .filter((task) => task.id !== selectedTask.id)
      .map((task) => ({
        value: task.id,
        label: `${task.title} (${task.status.replace(/_/g, " ")})`,
        disabled: alreadySelected.has(task.id),
      }));
  }, [editDependsOnTaskIds, selectedTask, tasks]);

  const addTaskDependency = useCallback((dependencyId: string) => {
    setEditDependsOnTaskIds((prev) =>
      prev.includes(dependencyId) ? prev : [...prev, dependencyId],
    );
  }, []);

  const removeTaskDependency = useCallback((dependencyId: string) => {
    setEditDependsOnTaskIds((prev) =>
      prev.filter((value) => value !== dependencyId),
    );
  }, []);

  const addEditTag = useCallback((tagId: string) => {
    setEditTagIds((prev) => (prev.includes(tagId) ? prev : [...prev, tagId]));
  }, []);

  const removeEditTag = useCallback((tagId: string) => {
    setEditTagIds((prev) => prev.filter((value) => value !== tagId));
  }, []);

  const addCreateTag = useCallback((tagId: string) => {
    setCreateTagIds((prev) => (prev.includes(tagId) ? prev : [...prev, tagId]));
  }, []);

  const removeCreateTag = useCallback((tagId: string) => {
    setCreateTagIds((prev) => prev.filter((value) => value !== tagId));
  }, []);

  const hasTaskChanges = useMemo(() => {
    if (!selectedTask) return false;
    const normalizedTitle = editTitle.trim();
    const normalizedDescription = editDescription.trim();
    const currentDescription = (selectedTask.description ?? "").trim();
    const currentDueDate = toLocalDateInput(selectedTask.due_at);
    const currentAssignee = selectedTask.assigned_agent_id ?? "";
    const currentTags = [...(selectedTask.tag_ids ?? [])].sort().join("|");
    const nextTags = [...editTagIds].sort().join("|");
    const currentDeps = [...(selectedTask.depends_on_task_ids ?? [])]
      .sort()
      .join("|");
    const nextDeps = [...editDependsOnTaskIds].sort().join("|");
    const currentCustomFieldValues = canonicalizeCustomFieldValues(
      boardCustomFieldValues(
        boardCustomFieldDefinitions,
        selectedTask.custom_field_values,
      ),
    );
    const nextCustomFieldValues = canonicalizeCustomFieldValues(
      customFieldPayload(boardCustomFieldDefinitions, editCustomFieldValues),
    );
    return (
      normalizedTitle !== selectedTask.title ||
      normalizedDescription !== currentDescription ||
      editStatus !== selectedTask.status ||
      editPriority !== selectedTask.priority ||
      editDueDate !== currentDueDate ||
      editAssigneeId !== currentAssignee ||
      currentTags !== nextTags ||
      currentDeps !== nextDeps ||
      currentCustomFieldValues !== nextCustomFieldValues
    );
  }, [
    editAssigneeId,
    editDueDate,
    editTagIds,
    editDependsOnTaskIds,
    editDescription,
    editPriority,
    editStatus,
    editTitle,
    editCustomFieldValues,
    boardCustomFieldDefinitions,
    selectedTask,
  ]);

  const pendingApprovals = useMemo(
    () => approvals.filter((approval) => approval.status === "pending"),
    [approvals],
  );

  const taskApprovals = useMemo(() => {
    if (!selectedTask) return [];
    const taskId = selectedTask.id;
    const taskIdsForApproval = (approval: Approval) => {
      const payload = approval.payload ?? {};
      const payloadValue = (key: string) => {
        const value = (payload as Record<string, unknown>)[key];
        if (typeof value === "string" || typeof value === "number") {
          return String(value);
        }
        return null;
      };
      const payloadArray = (key: string) => {
        const value = (payload as Record<string, unknown>)[key];
        if (!Array.isArray(value)) return [];
        return value.filter((item): item is string => typeof item === "string");
      };
      const linkedTaskIds = (
        approval as Approval & { task_ids?: string[] | null }
      ).task_ids;
      const singleTaskId =
        approval.task_id ??
        payloadValue("task_id") ??
        payloadValue("taskId") ??
        payloadValue("taskID");
      const merged = [
        ...(Array.isArray(linkedTaskIds) ? linkedTaskIds : []),
        ...payloadArray("task_ids"),
        ...payloadArray("taskIds"),
        ...payloadArray("taskIDs"),
        ...(singleTaskId ? [singleTaskId] : []),
      ];
      return [...new Set(merged)];
    };
    return approvals.filter((approval) =>
      taskIdsForApproval(approval).includes(taskId),
    );
  }, [approvals, selectedTask]);

  const workingAgentIds = useMemo(() => {
    const working = new Set<string>();
    tasks.forEach((task) => {
      if (task.status === "in_progress" && task.assigned_agent_id) {
        working.add(task.assigned_agent_id);
      }
    });
    return working;
  }, [tasks]);

  const sortedAgents = useMemo(() => {
    const rank = (agent: Agent) => {
      if (workingAgentIds.has(agent.id)) return 0;
      if (agent.status === "online") return 1;
      if (agent.status === "provisioning") return 2;
      return 3;
    };
    return [...agents].sort((a, b) => {
      const diff = rank(a) - rank(b);
      if (diff !== 0) return diff;
      return a.name.localeCompare(b.name);
    });
  }, [agents, workingAgentIds]);

  const boardLead = useMemo(
    () => agents.find((agent) => agent.is_board_lead) ?? null,
    [agents],
  );
  const isBoardLeadProvisioning = boardLead?.status === "provisioning";

  const loadComments = useCallback(
    async (taskId: string) => {
      if (!isSignedIn || !boardId) return;
      setIsCommentsLoading(true);
      setCommentsError(null);
      try {
        const result =
          await listTaskCommentsApiV1BoardsBoardIdTasksTaskIdCommentsGet(
            boardId,
            taskId,
          );
        if (result.status !== 200) throw new Error("Unable to load comments.");
        const items = [...(result.data.items ?? [])];
        items.sort((a, b) => {
          const aTime = apiDatetimeToMs(a.created_at) ?? 0;
          const bTime = apiDatetimeToMs(b.created_at) ?? 0;
          return bTime - aTime;
        });
        setComments(items);
      } catch (err) {
        setCommentsError(
          err instanceof Error ? err.message : "Something went wrong.",
        );
      } finally {
        setIsCommentsLoading(false);
      }
    },
    [boardId, isSignedIn],
  );

  const openComments = useCallback(
    (task: { id: string }) => {
      setIsChatOpen(false);
      setIsLiveFeedOpen(false);
      const fullTask = tasksRef.current.find((item) => item.id === task.id);
      if (!fullTask) return;
      const currentTaskIdFromUrl = searchParams.get("taskId");
      if (currentTaskIdFromUrl !== fullTask.id) {
        router.replace(
          buildUrlWithTaskId(pathname, searchParams, fullTask.id),
          {
            scroll: false,
          },
        );
      }
      selectedTaskIdRef.current = fullTask.id;
      setSelectedTask(fullTask);
      setIsDetailOpen(true);
      void loadComments(task.id);
    },
    [loadComments, pathname, router, searchParams],
  );

  const selectedTaskDependencies = useMemo<DependencyBannerDependency[]>(() => {
    if (!selectedTask) return [];
    const blockedDependencyIds = new Set(
      selectedTask.blocked_by_task_ids ?? [],
    );
    return (selectedTask.depends_on_task_ids ?? []).map((dependencyId) => {
      const dependencyTask = taskById.get(dependencyId);
      const statusLabel = dependencyTask?.status
        ? dependencyTask.status.replace(/_/g, " ")
        : "unknown";
      return {
        id: dependencyId,
        title: dependencyTask?.title ?? dependencyId,
        statusLabel,
        isBlocking: blockedDependencyIds.has(dependencyId),
        isDone: dependencyTask?.status === "done",
        disabled: !dependencyTask,
        onClick: dependencyTask
          ? () => {
              openComments({ id: dependencyId });
            }
          : undefined,
      };
    });
  }, [openComments, selectedTask, taskById]);

  const selectedTaskResolvedDependencies = useMemo<
    DependencyBannerDependency[]
  >(() => {
    if (!selectedTask) return [];
    return tasks
      .filter((task) => task.depends_on_task_ids?.includes(selectedTask.id))
      .map((task) => {
        const statusLabel = task.status
          ? task.status.replace(/_/g, " ")
          : "unknown";
        return {
          id: task.id,
          title: task.title,
          statusLabel,
          isBlocking: false,
          isDone: task.status === "done",
          onClick: () => {
            openComments({ id: task.id });
          },
          disabled: false,
        };
      });
  }, [openComments, selectedTask, tasks]);

  useEffect(() => {
    if (!hasLoadedBoardSnapshot) return;
    if (!taskIdFromUrl) {
      openedTaskIdFromUrlRef.current = null;
      return;
    }
    if (openedTaskIdFromUrlRef.current === taskIdFromUrl) return;
    const exists = tasks.some((task) => task.id === taskIdFromUrl);
    if (!exists) {
      router.replace(buildUrlWithTaskId(pathname, searchParams, null), {
        scroll: false,
      });
      return;
    }
    openedTaskIdFromUrlRef.current = taskIdFromUrl;
    openComments({ id: taskIdFromUrl });
  }, [
    hasLoadedBoardSnapshot,
    openComments,
    pathname,
    router,
    searchParams,
    taskIdFromUrl,
    tasks,
  ]);

  const closeComments = () => {
    openedTaskIdFromUrlRef.current = null;
    if (searchParams.get("taskId")) {
      router.replace(buildUrlWithTaskId(pathname, searchParams, null), {
        scroll: false,
      });
    }
    setIsDetailOpen(false);
    selectedTaskIdRef.current = null;
    setSelectedTask(null);
    setComments([]);
    setCommentsError(null);
    setPostCommentError(null);
    setIsEditDialogOpen(false);
  };

  const openBoardChat = () => {
    if (isDetailOpen) {
      closeComments();
    }
    setIsLiveFeedOpen(false);
    setIsChatOpen(true);
  };

  const closeBoardChat = () => {
    setIsChatOpen(false);
    setChatError(null);
  };

  const openLiveFeed = () => {
    if (isDetailOpen) {
      closeComments();
    }
    if (isChatOpen) {
      closeBoardChat();
    }
    setIsLiveFeedOpen(true);
  };

  const closeLiveFeed = () => {
    setIsLiveFeedOpen(false);
  };

  const handlePostComment = async (message: string): Promise<boolean> => {
    if (!selectedTask || !boardId || !isSignedIn) return false;
    const trimmed = message.trim();
    if (!trimmed) {
      setPostCommentError("Write a message before sending.");
      return false;
    }
    setIsPostingComment(true);
    setPostCommentError(null);
    try {
      const result =
        await createTaskCommentApiV1BoardsBoardIdTasksTaskIdCommentsPost(
          boardId,
          selectedTask.id,
          { message: trimmed },
        );
      if (result.status !== 200) throw new Error("Unable to send message.");
      const created = result.data;
      setComments((prev) => [created, ...prev]);
      return true;
    } catch (err) {
      const message = formatActionError(err, "Unable to send message.");
      setPostCommentError(message);
      pushToast(message);
      return false;
    } finally {
      setIsPostingComment(false);
    }
  };

  const handleTaskSave = async (closeOnSuccess = false) => {
    if (!selectedTask || !isSignedIn || !boardId) return;
    const trimmedTitle = editTitle.trim();
    if (!trimmedTitle) {
      setSaveTaskError("Title is required.");
      return;
    }
    const currentTaskCustomFieldValues = boardCustomFieldValues(
      boardCustomFieldDefinitions,
      selectedTask.custom_field_values,
    );
    const editCustomFieldPayload = customFieldPayload(
      boardCustomFieldDefinitions,
      editCustomFieldValues,
    );
    const editCustomFieldPatch = customFieldPatchPayload(
      boardCustomFieldDefinitions,
      currentTaskCustomFieldValues,
      editCustomFieldPayload,
    );
    const missingRequiredCustomField = firstMissingRequiredCustomField(
      boardCustomFieldDefinitions.filter((definition) =>
        Object.prototype.hasOwnProperty.call(
          editCustomFieldPatch,
          definition.field_key,
        ),
      ),
      editCustomFieldPatch,
    );
    if (missingRequiredCustomField) {
      setSaveTaskError(
        `Custom field "${missingRequiredCustomField}" is required.`,
      );
      return;
    }
    setIsSavingTask(true);
    setSaveTaskError(null);
    try {
      const currentDeps = [...(selectedTask.depends_on_task_ids ?? [])]
        .sort()
        .join("|");
      const nextDeps = [...editDependsOnTaskIds].sort().join("|");
      const depsChanged = currentDeps !== nextDeps;
      const currentTags = [...(selectedTask.tag_ids ?? [])].sort().join("|");
      const nextTags = [...editTagIds].sort().join("|");
      const tagsChanged = currentTags !== nextTags;
      const currentDueDate = toLocalDateInput(selectedTask.due_at);
      const dueDateChanged = editDueDate !== currentDueDate;
      const customFieldValuesChanged =
        Object.keys(editCustomFieldPatch).length > 0;

      const updatePayload: BoardTaskUpdatePayload = {
        title: trimmedTitle,
        description: editDescription.trim() || null,
        status: editStatus,
        priority: editPriority,
        assigned_agent_id: editAssigneeId || null,
      };

      if (depsChanged && selectedTask.status !== "done") {
        updatePayload.depends_on_task_ids = editDependsOnTaskIds;
      }
      if (tagsChanged) {
        updatePayload.tag_ids = editTagIds;
      }
      if (dueDateChanged) {
        updatePayload.due_at = localDateInputToUtcIso(editDueDate);
      }
      if (
        customFieldValuesChanged &&
        Object.keys(editCustomFieldPatch).length > 0
      ) {
        updatePayload.custom_field_values = editCustomFieldPatch;
      }

      const result = await updateTaskApiV1BoardsBoardIdTasksTaskIdPatch(
        boardId,
        selectedTask.id,
        updatePayload,
      );
      if (result.status === 409) {
        const blockedIds = result.data.detail.blocked_by_task_ids ?? [];
        const blockedTitles = blockedIds
          .map((id) => taskTitleById.get(id) ?? id)
          .join(", ");
        setSaveTaskError(
          blockedTitles
            ? `${result.data.detail.message} Blocked by: ${blockedTitles}`
            : result.data.detail.message,
        );
        return;
      }
      if (result.status === 422) {
        setSaveTaskError(
          result.data.detail?.[0]?.msg ?? "Validation error while saving task.",
        );
        return;
      }
      const previous =
        tasksRef.current.find((task) => task.id === selectedTask.id) ??
        selectedTask;
      const updated = normalizeTask({
        ...previous,
        ...result.data,
        assignee: result.data.assigned_agent_id
          ? (assigneeById.get(result.data.assigned_agent_id) ?? null)
          : null,
        approvals_count: previous.approvals_count,
        approvals_pending_count: previous.approvals_pending_count,
      } as TaskCardRead);
      setTasks((prev) =>
        prev.map((task) =>
          task.id === updated.id ? { ...task, ...updated } : task,
        ),
      );
      setSelectedTask(updated);
      if (closeOnSuccess) {
        setIsEditDialogOpen(false);
      }
    } catch (err) {
      const message = formatActionError(err, "Something went wrong.");
      setSaveTaskError(message);
      pushToast(message);
    } finally {
      setIsSavingTask(false);
    }
  };

  const handleTaskReset = () => {
    if (!selectedTask) return;
    setEditTitle(selectedTask.title);
    setEditDescription(selectedTask.description ?? "");
    setEditStatus(selectedTask.status);
    setEditPriority(selectedTask.priority);
    setEditDueDate(toLocalDateInput(selectedTask.due_at));
    setEditAssigneeId(selectedTask.assigned_agent_id ?? "");
    setEditTagIds(selectedTask.tag_ids ?? []);
    setEditDependsOnTaskIds(selectedTask.depends_on_task_ids ?? []);
    setEditCustomFieldValues(
      boardCustomFieldValues(
        boardCustomFieldDefinitions,
        selectedTask.custom_field_values,
      ),
    );
    setSaveTaskError(null);
  };

  const handleDeleteTask = async () => {
    if (!selectedTask || !boardId || !isSignedIn) return;
    setIsDeletingTask(true);
    setDeleteTaskError(null);
    try {
      const result = await deleteTaskApiV1BoardsBoardIdTasksTaskIdDelete(
        boardId,
        selectedTask.id,
      );
      if (result.status !== 200) throw new Error("Unable to delete task.");
      setTasks((prev) => prev.filter((task) => task.id !== selectedTask.id));
      setIsDeleteDialogOpen(false);
      closeComments();
    } catch (err) {
      const message = formatActionError(err, "Something went wrong.");
      setDeleteTaskError(message);
      pushToast(message);
    } finally {
      setIsDeletingTask(false);
    }
  };

  const handleTaskMove = useCallback(
    async (taskId: string, status: TaskStatus) => {
      if (!isSignedIn || !boardId) return;
      const currentTask = tasksRef.current.find((task) => task.id === taskId);
      if (!currentTask || currentTask.status === status) return;
      if (currentTask.is_blocked && status !== "inbox") {
        setError("Task is blocked by incomplete dependencies.");
        return;
      }
      const previousTasks = tasksRef.current;
      setTasks((prev) =>
        prev.map((task) =>
          task.id === taskId
            ? {
                ...task,
                status,
                assigned_agent_id:
                  status === "inbox" ? null : task.assigned_agent_id,
                assignee: status === "inbox" ? null : task.assignee,
              }
            : task,
        ),
      );
      try {
        const result = await updateTaskApiV1BoardsBoardIdTasksTaskIdPatch(
          boardId,
          taskId,
          { status },
        );
        if (result.status === 409) {
          const blockedIds = result.data.detail.blocked_by_task_ids ?? [];
          const blockedTitles = blockedIds
            .map((id) => taskTitleById.get(id) ?? id)
            .join(", ");
          throw new Error(
            blockedTitles
              ? `${result.data.detail.message} Blocked by: ${blockedTitles}`
              : result.data.detail.message,
          );
        }
        if (result.status === 422) {
          throw new Error(
            result.data.detail?.[0]?.msg ??
              "Validation error while moving task.",
          );
        }
        const assignee = result.data.assigned_agent_id
          ? (agentsRef.current.find(
              (agent) => agent.id === result.data.assigned_agent_id,
            )?.name ?? null)
          : null;
        const updated = normalizeTask({
          ...currentTask,
          ...result.data,
          assignee,
          approvals_count: currentTask.approvals_count,
          approvals_pending_count: currentTask.approvals_pending_count,
        } as TaskCardRead);
        setTasks((prev) =>
          prev.map((task) =>
            task.id === updated.id ? { ...task, ...updated } : task,
          ),
        );
      } catch (err) {
        setTasks(previousTasks);
        const message = formatActionError(err, "Unable to move task.");
        setError(message);
        pushToast(message);
      }
    },
    [boardId, isSignedIn, pushToast, taskTitleById],
  );

  const agentInitials = (agent: Agent) =>
    agent.name
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase();

  const resolveEmoji = (value?: string | null) => {
    if (!value) return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (EMOJI_GLYPHS[trimmed]) return EMOJI_GLYPHS[trimmed];
    if (trimmed.startsWith(":") && trimmed.endsWith(":")) return null;
    return trimmed;
  };

  const agentAvatarLabel = (agent: Agent) => {
    if (agent.is_board_lead) return "⚙️";
    let emojiValue: string | null = null;
    if (agent.identity_profile && typeof agent.identity_profile === "object") {
      const rawEmoji = (agent.identity_profile as Record<string, unknown>)
        .emoji;
      emojiValue = typeof rawEmoji === "string" ? rawEmoji : null;
    }
    const emoji = resolveEmoji(emojiValue);
    return emoji ?? agentInitials(agent);
  };

  const agentRoleLabel = (agent: Agent) => {
    // Prefer the configured identity role from the API.
    if (agent.identity_profile && typeof agent.identity_profile === "object") {
      const rawRole = (agent.identity_profile as Record<string, unknown>).role;
      if (typeof rawRole === "string") {
        const trimmed = rawRole.trim();
        if (trimmed) return trimmed;
      }
    }
    if (agent.is_board_lead) return "Board lead";
    if (agent.is_gateway_main) return "Gateway main";
    return "Agent";
  };

  const formatTaskTimestamp = (value?: string | null) => {
    if (!value) return "—";
    const date = parseApiDatetime(value);
    if (!date) return "—";
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const statusBadgeClass = (value?: string) => {
    switch (value) {
      case "in_progress":
        return "bg-purple-100 text-purple-700";
      case "review":
        return "bg-indigo-100 text-indigo-700";
      case "done":
        return "bg-emerald-100 text-emerald-700";
      default:
        return "bg-slate-100 text-slate-600";
    }
  };

  const priorityBadgeClass = (value?: string) => {
    switch (value?.toLowerCase()) {
      case "high":
        return "bg-rose-100 text-rose-700";
      case "medium":
        return "bg-amber-100 text-amber-700";
      case "low":
        return "bg-emerald-100 text-emerald-700";
      default:
        return "bg-slate-100 text-slate-600";
    }
  };

  const formatApprovalTimestamp = (value?: string | null) => {
    if (!value) return "—";
    const date = parseApiDatetime(value);
    if (!date) return value;
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const humanizeApprovalAction = (value: string) =>
    value
      .split(".")
      .map((part) =>
        part.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()),
      )
      .join(" · ");

  const approvalPayloadValue = (payload: Approval["payload"], key: string) => {
    if (!payload || typeof payload !== "object") return null;
    const value = (payload as Record<string, unknown>)[key];
    if (typeof value === "string" || typeof value === "number") {
      return String(value);
    }
    return null;
  };

  const approvalPayloadValues = (payload: Approval["payload"], key: string) => {
    if (!payload || typeof payload !== "object") return [];
    const value = (payload as Record<string, unknown>)[key];
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is string => typeof item === "string");
  };

  const approvalTaskIds = (approval: Approval) => {
    const payload = approval.payload ?? {};
    const linkedTaskIds = (
      approval as Approval & { task_ids?: string[] | null }
    ).task_ids;
    const singleTaskId =
      approval.task_id ??
      approvalPayloadValue(payload, "task_id") ??
      approvalPayloadValue(payload, "taskId") ??
      approvalPayloadValue(payload, "taskID");
    const manyTaskIds = [
      ...approvalPayloadValues(payload, "task_ids"),
      ...approvalPayloadValues(payload, "taskIds"),
      ...approvalPayloadValues(payload, "taskIDs"),
    ];
    const merged = [
      ...(Array.isArray(linkedTaskIds) ? linkedTaskIds : []),
      ...manyTaskIds,
      ...(singleTaskId ? [singleTaskId] : []),
    ];
    const deduped: string[] = [];
    const seen = new Set<string>();
    merged.forEach((value) => {
      if (seen.has(value)) return;
      seen.add(value);
      deduped.push(value);
    });
    return deduped;
  };

  const approvalRows = (approval: Approval) => {
    const payload = approval.payload ?? {};
    const taskIds = approvalTaskIds(approval);
    const assignedAgentId =
      approvalPayloadValue(payload, "assigned_agent_id") ??
      approvalPayloadValue(payload, "assignedAgentId");
    const title = approvalPayloadValue(payload, "title");
    const role = approvalPayloadValue(payload, "role");
    const isAssign = approval.action_type.includes("assign");
    const rows: Array<{ label: string; value: string }> = [];
    if (taskIds.length === 1) rows.push({ label: "Task", value: taskIds[0] });
    if (taskIds.length > 1)
      rows.push({ label: "Tasks", value: taskIds.join(", ") });
    if (isAssign) {
      rows.push({
        label: "Assignee",
        value: assignedAgentId ?? "Unassigned",
      });
    }
    if (title) rows.push({ label: "Title", value: title });
    if (role) rows.push({ label: "Role", value: role });
    return rows;
  };

  const approvalReason = (approval: Approval) =>
    approvalPayloadValue(approval.payload ?? {}, "reason");

  const handleApprovalDecision = useCallback(
    async (approvalId: string, status: "approved" | "rejected") => {
      if (!isSignedIn || !boardId) return;
      if (!canWrite) {
        pushToast(
          "Read-only access. You do not have permission to update approvals.",
        );
        return;
      }
      setApprovalsUpdatingId(approvalId);
      setApprovalsError(null);
      try {
        const result =
          await updateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch(
            boardId,
            approvalId,
            { status },
          );
        if (result.status !== 200) {
          throw new Error("Unable to update approval.");
        }
        const updated = normalizeApproval(result.data);
        setApprovals((prev) =>
          prev.map((item) => (item.id === approvalId ? updated : item)),
        );
      } catch (err) {
        const message = formatActionError(err, "Unable to update approval.");
        setApprovalsError(message);
        pushToast(message);
      } finally {
        setApprovalsUpdatingId(null);
      }
    },
    [boardId, canWrite, isSignedIn, pushToast],
  );

  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl surface-panel p-10 text-center">
          <p className="text-sm text-muted">Sign in to view boards.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/boards"
            signUpForceRedirectUrl="/boards"
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main
          className={cn(
            "flex-1 bg-gradient-to-br from-slate-50 to-slate-100",
            isSidePanelOpen ? "overflow-hidden" : "overflow-y-auto",
          )}
        >
          <div className="sticky top-0 z-30 border-b border-slate-200 bg-white shadow-sm">
            <div className="px-8 py-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h1 className="mt-2 text-2xl font-semibold text-slate-900 tracking-tight">
                    {board?.name ?? "Board"}
                  </h1>
                  <p className="mt-1 text-sm text-slate-500">
                    Keep tasks moving through your workflow.
                  </p>
                  {isBoardLeadProvisioning ? (
                    <div className="mt-3 inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800">
                      <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
                      <span>Provisioning board lead…</span>
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1">
                    <button
                      className={cn(
                        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                        viewMode === "board"
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-slate-200 hover:text-slate-900",
                      )}
                      onClick={() => setViewMode("board")}
                    >
                      Board
                    </button>
                    <button
                      className={cn(
                        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                        viewMode === "list"
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-slate-200 hover:text-slate-900",
                      )}
                      onClick={() => setViewMode("list")}
                    >
                      List
                    </button>
                  </div>
                  <Button
                    onClick={() => setIsDialogOpen(true)}
                    className="h-9 w-9 p-0"
                    aria-label="New task"
                    title={canWrite ? "New task" : "Read-only access"}
                    disabled={!canWrite}
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => router.push(`/boards/${boardId}/approvals`)}
                    className="relative h-9 w-9 p-0"
                    aria-label="Approvals"
                    title="Approvals"
                  >
                    <ShieldCheck className="h-4 w-4" />
                    {pendingApprovals.length > 0 ? (
                      <span className="absolute -right-1 -top-1 inline-flex min-w-[18px] items-center justify-center rounded-full bg-slate-900 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                        {pendingApprovals.length}
                      </span>
                    ) : null}
                  </Button>
                  {isOrgAdmin ? (
                    <Button
                      variant="outline"
                      onClick={() =>
                        openAgentsControlDialog(
                          isAgentsPaused ? "resume" : "pause",
                        )
                      }
                      disabled={
                        !isSignedIn ||
                        !boardId ||
                        isAgentsControlSending ||
                        !canWrite
                      }
                      className={cn(
                        "h-9 w-9 p-0",
                        isAgentsPaused
                          ? "border-amber-200 bg-amber-50/60 text-amber-700 hover:border-amber-300 hover:bg-amber-50 hover:text-amber-800"
                          : "",
                      )}
                      aria-label={
                        isAgentsPaused ? "Resume agents" : "Pause agents"
                      }
                      title={
                        canWrite
                          ? isAgentsPaused
                            ? "Resume agents"
                            : "Pause agents"
                          : "Read-only access"
                      }
                    >
                      {isAgentsPaused ? (
                        <Play className="h-4 w-4" />
                      ) : (
                        <Pause className="h-4 w-4" />
                      )}
                    </Button>
                  ) : null}
                  <Button
                    variant="outline"
                    onClick={openBoardChat}
                    className="h-9 w-9 p-0"
                    aria-label="Board chat"
                    title="Board chat"
                  >
                    <MessageSquare className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    onClick={openLiveFeed}
                    className="h-9 w-9 p-0"
                    aria-label="Live feed"
                    title="Live feed"
                  >
                    <Activity className="h-4 w-4" />
                  </Button>
                  {isOrgAdmin ? (
                    <button
                      type="button"
                      onClick={() => router.push(`/boards/${boardId}/edit`)}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
                      aria-label="Board settings"
                      title="Board settings"
                    >
                      <Settings className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          </div>

          <div className="relative flex gap-6 p-6">
            {isOrgAdmin ? (
              <aside className="flex h-full w-64 flex-col rounded-xl border border-slate-200 bg-white shadow-sm">
                <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Agents
                    </p>
                    <p className="text-xs text-slate-400">
                      {sortedAgents.length} total
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => router.push("/agents/new")}
                    className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
                  >
                    Add
                  </button>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto p-3">
                  {sortedAgents.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-500">
                      No agents assigned yet.
                    </div>
                  ) : (
                    sortedAgents.map((agent) => {
                      const isWorking = workingAgentIds.has(agent.id);
                      return (
                        <button
                          key={agent.id}
                          type="button"
                          className={cn(
                            "flex w-full items-center gap-3 rounded-lg border border-transparent px-2 py-2 text-left transition hover:border-slate-200 hover:bg-slate-50",
                          )}
                          onClick={() => router.push(`/agents/${agent.id}`)}
                        >
                          <div className="relative flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700">
                            {agentAvatarLabel(agent)}
                            <StatusDot
                              status={agent.status}
                              variant="agent"
                              className={cn(
                                "absolute -right-0.5 -bottom-0.5 h-2.5 w-2.5 rounded-full border-2 border-white",
                                isWorking && "ring-2 ring-emerald-200",
                              )}
                            />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-slate-900">
                              {agent.name}
                            </p>
                            <p className="text-[11px] text-slate-500">
                              {agentRoleLabel(agent)}
                            </p>
                          </div>
                        </button>
                      );
                    })
                  )}
                </div>
              </aside>
            ) : null}

            <div className="min-w-0 flex-1 space-y-6">
              {error && (
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600 shadow-sm">
                  {error}
                </div>
              )}

              {isLoading ? (
                <div className="flex min-h-[50vh] items-center justify-center text-sm text-slate-500">
                  Loading {titleLabel}…
                </div>
              ) : (
                <>
                  {viewMode === "list" ? (
                    <>
                      {groupSnapshotError ? (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 shadow-sm">
                          {groupSnapshotError}
                        </div>
                      ) : null}

                      {groupSnapshot?.group ? (
                        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
                          <div className="border-b border-slate-200 px-5 py-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                                  Related boards
                                </p>
                                <p className="mt-1 truncate text-sm font-semibold text-slate-900">
                                  {groupSnapshot.group.name}
                                </p>
                                {groupSnapshot.group.description ? (
                                  <p className="mt-1 max-w-3xl text-xs text-slate-500 line-clamp-2">
                                    {groupSnapshot.group.description}
                                  </p>
                                ) : null}
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() =>
                                    router.push(
                                      `/board-groups/${groupSnapshot.group?.id}`,
                                    )
                                  }
                                  disabled={!groupSnapshot.group?.id}
                                >
                                  View group
                                </Button>
                                {isOrgAdmin ? (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                      router.push(`/boards/${boardId}/edit`)
                                    }
                                    disabled={!boardId}
                                  >
                                    Settings
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                          </div>
                          <div className="px-5 py-4">
                            {groupSnapshot.boards &&
                            groupSnapshot.boards.length ? (
                              <div className="grid gap-4 md:grid-cols-2">
                                {groupSnapshot.boards.map((item) => (
                                  <div
                                    key={item.board.id}
                                    className="rounded-xl border border-slate-200 bg-slate-50/40 p-4"
                                  >
                                    <button
                                      type="button"
                                      className="group flex w-full items-start justify-between gap-3 text-left"
                                      onClick={() =>
                                        router.push(`/boards/${item.board.id}`)
                                      }
                                    >
                                      <div className="min-w-0">
                                        <p className="truncate text-sm font-semibold text-slate-900 group-hover:text-blue-600">
                                          {item.board.name}
                                        </p>
                                        <p className="mt-1 text-xs text-slate-500">
                                          Updated{" "}
                                          {formatTaskTimestamp(
                                            item.board.updated_at,
                                          )}
                                        </p>
                                      </div>
                                      <ArrowUpRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-400 group-hover:text-blue-600" />
                                    </button>

                                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                                      <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-700">
                                        Inbox {item.task_counts?.inbox ?? 0}
                                      </span>
                                      <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-700">
                                        In progress{" "}
                                        {item.task_counts?.in_progress ?? 0}
                                      </span>
                                      <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-700">
                                        Review {item.task_counts?.review ?? 0}
                                      </span>
                                    </div>

                                    {item.tasks && item.tasks.length ? (
                                      <ul className="mt-3 space-y-2">
                                        {item.tasks.slice(0, 3).map((task) => (
                                          <li
                                            key={task.id}
                                            className="rounded-lg border border-slate-200 bg-white p-3"
                                          >
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                              <div className="flex min-w-0 items-center gap-2">
                                                <span
                                                  className={cn(
                                                    "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                                                    statusBadgeClass(
                                                      task.status,
                                                    ),
                                                  )}
                                                >
                                                  {task.status.replace(
                                                    /_/g,
                                                    " ",
                                                  )}
                                                </span>
                                                <span
                                                  className={cn(
                                                    "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                                                    priorityBadgeClass(
                                                      task.priority,
                                                    ),
                                                  )}
                                                >
                                                  {task.priority}
                                                </span>
                                                <p className="truncate text-sm font-medium text-slate-900">
                                                  {task.title}
                                                </p>
                                              </div>
                                              <p className="text-xs text-slate-500">
                                                {formatTaskTimestamp(
                                                  task.updated_at,
                                                )}
                                              </p>
                                            </div>
                                            <p className="mt-2 truncate text-xs text-slate-600">
                                              Assignee:{" "}
                                              <span className="font-medium text-slate-900">
                                                {task.assignee ?? "Unassigned"}
                                              </span>
                                            </p>
                                            {task.tags?.length ? (
                                              <div className="mt-2 flex flex-wrap gap-1.5">
                                                {task.tags
                                                  .slice(0, 3)
                                                  .map((tag) => (
                                                    <span
                                                      key={tag.id}
                                                      className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-700"
                                                    >
                                                      <span
                                                        className="h-1.5 w-1.5 rounded-full"
                                                        style={{
                                                          backgroundColor: `#${normalizeTagColor(
                                                            tag.color,
                                                          )}`,
                                                        }}
                                                      />
                                                      {tag.name}
                                                    </span>
                                                  ))}
                                              </div>
                                            ) : null}
                                          </li>
                                        ))}
                                        {item.tasks.length > 3 ? (
                                          <li className="text-xs text-slate-500">
                                            +{item.tasks.length - 3} more…
                                          </li>
                                        ) : null}
                                      </ul>
                                    ) : (
                                      <p className="mt-3 text-sm text-slate-500">
                                        No tasks in this snapshot.
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="text-sm text-slate-500">
                                No other boards in this group yet.
                              </p>
                            )}
                          </div>
                        </div>
                      ) : groupSnapshot ? (
                        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600 shadow-sm">
                          <p className="font-semibold text-slate-900">
                            No board group configured
                          </p>
                          <p className="mt-1 text-sm text-slate-600">
                            Assign this board to a group to give agents
                            visibility into related work.
                          </p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                router.push(`/boards/${boardId}/edit`)
                              }
                              disabled={!boardId}
                            >
                              Open settings
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => router.push("/board-groups")}
                            >
                              View groups
                            </Button>
                          </div>
                        </div>
                      ) : null}
                    </>
                  ) : null}

                  {viewMode === "board" ? (
                    <TaskBoard
                      tasks={tasks}
                      onTaskSelect={openComments}
                      onTaskMove={canWrite ? handleTaskMove : undefined}
                      readOnly={!canWrite}
                    />
                  ) : (
                    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
                      <div className="border-b border-slate-200 px-5 py-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm font-semibold text-slate-900">
                              All tasks
                            </p>
                            <p className="text-xs text-slate-500">
                              {tasks.length} tasks in this board
                            </p>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setIsDialogOpen(true)}
                            disabled={isCreating || !canWrite}
                            title={canWrite ? "New task" : "Read-only access"}
                          >
                            New task
                          </Button>
                        </div>
                      </div>
                      <div className="divide-y divide-slate-100">
                        {tasks.length === 0 ? (
                          <div className="px-5 py-8 text-sm text-slate-500">
                            No tasks yet. Create your first task to get started.
                          </div>
                        ) : (
                          tasks.map((task) => (
                            <button
                              key={task.id}
                              type="button"
                              className="w-full px-5 py-4 text-left transition hover:bg-slate-50"
                              onClick={() => openComments(task)}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-semibold text-slate-900">
                                    {task.title}
                                  </p>
                                  <p className="mt-1 text-xs text-slate-500">
                                    {task.description
                                      ? task.description
                                          .toString()
                                          .trim()
                                          .slice(0, 120)
                                      : "No description"}
                                  </p>
                                </div>
                                <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
                                  {task.approvals_pending_count ? (
                                    <span className="inline-flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                                      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                                      Approval needed ·{" "}
                                      {task.approvals_pending_count}
                                    </span>
                                  ) : null}
                                  <span
                                    className={cn(
                                      "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                                      statusBadgeClass(task.status),
                                    )}
                                  >
                                    {task.status.replace(/_/g, " ")}
                                  </span>
                                  <span
                                    className={cn(
                                      "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                                      priorityBadgeClass(task.priority),
                                    )}
                                  >
                                    {task.priority}
                                  </span>
                                  {task.tags?.length ? (
                                    <div className="flex flex-wrap items-center gap-1">
                                      {task.tags.slice(0, 2).map((tag) => (
                                        <span
                                          key={tag.id}
                                          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-700"
                                        >
                                          <span
                                            className="h-1.5 w-1.5 rounded-full"
                                            style={{
                                              backgroundColor: `#${normalizeTagColor(
                                                tag.color,
                                              )}`,
                                            }}
                                          />
                                          {tag.name}
                                        </span>
                                      ))}
                                      {task.tags.length > 2 ? (
                                        <span className="text-[10px] font-semibold text-slate-500">
                                          +{task.tags.length - 2}
                                        </span>
                                      ) : null}
                                    </div>
                                  ) : null}
                                  <span className="text-xs text-slate-500">
                                    {task.assignee ?? "Unassigned"}
                                  </span>
                                  <span className="text-xs text-slate-500">
                                    {formatTaskTimestamp(
                                      task.updated_at ?? task.created_at,
                                    )}
                                  </span>
                                </div>
                              </div>
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </main>
      </SignedIn>
      {isDetailOpen || isChatOpen || isLiveFeedOpen ? (
        <div
          className="fixed inset-0 z-40 bg-slate-900/20"
          onClick={() => {
            if (isChatOpen) {
              closeBoardChat();
            } else if (isLiveFeedOpen) {
              closeLiveFeed();
            } else {
              closeComments();
            }
          }}
        />
      ) : null}
      <aside
        className={cn(
          "fixed right-0 top-0 z-50 h-full w-[max(760px,45vw)] max-w-[99vw] transform bg-white shadow-2xl transition-transform",
          isDetailOpen ? "transform-none" : "translate-x-full",
        )}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Task detail
              </p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                {selectedTask?.title ?? "Task"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsEditDialogOpen(true)}
                className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
                disabled={!selectedTask || !canWrite}
                title={canWrite ? "Edit task" : "Read-only access"}
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={closeComments}
                className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Description
              </p>
              {selectedTask?.description ? (
                <div className="prose prose-sm max-w-none text-slate-700">
                  <Markdown
                    content={selectedTask.description}
                    variant="description"
                  />
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  No description provided.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Custom fields
              </p>
              {customFieldDefinitionsQuery.isLoading ? (
                <p className="text-sm text-slate-500">Loading custom fields…</p>
              ) : boardCustomFieldDefinitions.length > 0 ? (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <dl className="space-y-2">
                    {boardCustomFieldDefinitions.map((definition) => {
                      const value =
                        selectedTaskCustomFieldValues[definition.field_key];
                      if (!isCustomFieldVisible(definition, value)) {
                        return null;
                      }
                      return (
                        <div
                          key={definition.id}
                          className="grid grid-cols-[160px_1fr] gap-3"
                        >
                          <dt className="text-xs font-semibold text-slate-600">
                            {definition.label || definition.field_key}
                            {definition.required === true ? (
                              <span className="ml-1 text-rose-600">*</span>
                            ) : null}
                          </dt>
                          <dd className="text-xs text-slate-800">
                            {formatCustomFieldDetailValue(definition, value)}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                </div>
              ) : (
                <p className="text-sm text-slate-500">No custom fields.</p>
              )}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Tags
              </p>
              {selectedTask?.tags?.length ? (
                <div className="flex flex-wrap gap-2">
                  {selectedTask.tags.map((tag) => (
                    <span
                      key={tag.id}
                      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700"
                    >
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{
                          backgroundColor: `#${normalizeTagColor(tag.color)}`,
                        }}
                      />
                      {tag.name}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No tags assigned.</p>
              )}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Dependencies
              </p>
              {(() => {
                const hasDependencies =
                  (selectedTask?.depends_on_task_ids?.length ?? 0) > 0;
                const hasResolvedDependencies =
                  selectedTaskResolvedDependencies.length > 0;
                const isDependencyModeBlocked = hasDependencies
                  ? selectedTask?.is_blocked === true
                  : false;
                const bannerVariant =
                  hasDependencies || hasResolvedDependencies
                    ? isDependencyModeBlocked
                      ? "blocked"
                      : "resolved"
                    : "blocked";
                const displayedDependencies =
                  hasDependencies && selectedTask
                    ? selectedTaskDependencies
                    : selectedTaskResolvedDependencies;
                const childrenMessage =
                  hasDependencies && selectedTask?.is_blocked
                    ? "Blocked by incomplete dependencies."
                    : hasDependencies
                      ? "Dependencies resolved."
                      : hasResolvedDependencies
                        ? "This task resolves these tasks."
                        : null;

                return (
                  <DependencyBanner
                    dependencies={displayedDependencies}
                    variant={bannerVariant}
                    emptyMessage="No dependencies."
                  >
                    {childrenMessage}
                  </DependencyBanner>
                );
              })()}
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Approvals
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => router.push(`/boards/${boardId}/approvals`)}
                >
                  View all
                </Button>
              </div>
              {approvalsError ? (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
                  {approvalsError}
                </div>
              ) : isApprovalsLoading ? (
                <p className="text-sm text-slate-500">Loading approvals…</p>
              ) : taskApprovals.length === 0 ? (
                <p className="text-sm text-slate-500">
                  No approvals tied to this task.{" "}
                  {pendingApprovals.length > 0
                    ? `${pendingApprovals.length} pending on this board.`
                    : "No pending approvals on this board."}
                </p>
              ) : (
                <div className="space-y-3">
                  {taskApprovals.map((approval) => (
                    <div
                      key={approval.id}
                      className="rounded-xl border border-slate-200 bg-white p-3"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2 text-xs text-slate-500">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                            {humanizeApprovalAction(approval.action_type)}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            Requested{" "}
                            {formatApprovalTimestamp(approval.created_at)}
                          </p>
                        </div>
                        <span className="text-xs font-semibold text-slate-700">
                          {approval.confidence}% confidence · {approval.status}
                        </span>
                      </div>
                      {approvalRows(approval).length > 0 ? (
                        <div className="mt-2 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
                          {approvalRows(approval).map((row) => (
                            <div key={`${approval.id}-${row.label}`}>
                              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                                {row.label}
                              </p>
                              <p className="mt-1 text-xs text-slate-700">
                                {row.value}
                              </p>
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {approvalReason(approval) ? (
                        <p className="mt-2 text-xs text-slate-600">
                          {approvalReason(approval)}
                        </p>
                      ) : null}
                      {approval.status === "pending" ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            onClick={() =>
                              handleApprovalDecision(approval.id, "approved")
                            }
                            disabled={
                              approvalsUpdatingId === approval.id || !canWrite
                            }
                            title={canWrite ? "Approve" : "Read-only access"}
                          >
                            Approve
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              handleApprovalDecision(approval.id, "rejected")
                            }
                            disabled={
                              approvalsUpdatingId === approval.id || !canWrite
                            }
                            title={canWrite ? "Reject" : "Read-only access"}
                            className="border-slate-300 text-slate-700"
                          >
                            Reject
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Comments
              </p>
              <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
                <BoardChatComposer
                  placeholder={
                    canWrite
                      ? "Write a message for the assigned agent. Tag @lead or @name."
                      : "Read-only access. Comments are disabled."
                  }
                  isSending={isPostingComment}
                  onSend={handlePostComment}
                  disabled={!canWrite}
                  mentionSuggestions={boardChatMentionSuggestions}
                />
                {postCommentError ? (
                  <p className="text-xs text-rose-600">{postCommentError}</p>
                ) : null}
                {!canWrite ? (
                  <p className="text-xs text-slate-500">
                    Read-only access. You cannot post comments on this board.
                  </p>
                ) : null}
              </div>
              {isCommentsLoading ? (
                <p className="text-sm text-slate-500">Loading comments…</p>
              ) : commentsError ? (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
                  {commentsError}
                </div>
              ) : comments.length === 0 ? (
                <p className="text-sm text-slate-500">No comments yet.</p>
              ) : (
                <div className="space-y-3">
                  {comments.map((comment) => (
                    <TaskCommentCard
                      key={comment.id}
                      comment={comment}
                      authorLabel={
                        comment.agent_id
                          ? (assigneeById.get(comment.agent_id) ?? "Agent")
                          : currentUserDisplayName
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </aside>

      <aside
        className={cn(
          "fixed right-0 top-0 z-50 h-full w-[560px] max-w-[96vw] transform border-l border-slate-200 bg-white shadow-2xl transition-transform",
          isChatOpen ? "transform-none" : "translate-x-full",
        )}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Board chat
              </p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                Talk to the lead agent. Tag others with @name.
              </p>
            </div>
            <button
              type="button"
              onClick={closeBoardChat}
              className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
              aria-label="Close board chat"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex flex-1 flex-col overflow-hidden px-6 py-4">
            <div className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4">
              {chatError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {chatError}
                </div>
              ) : null}
              {chatMessages.length === 0 ? (
                <p className="text-sm text-slate-500">
                  No messages yet. Start the conversation with your lead agent.
                </p>
              ) : (
                chatMessages.map((message) => (
                  <ChatMessageCard
                    key={message.id}
                    message={message}
                    fallbackSource={currentUserDisplayName}
                  />
                ))
              )}
              <div ref={chatEndRef} />
            </div>
            <BoardChatComposer
              isSending={isChatSending}
              onSend={handleSendChat}
              disabled={!canWrite}
              mentionSuggestions={boardChatMentionSuggestions}
              placeholder={
                canWrite
                  ? "Message the board lead. Tag agents with @name."
                  : "Read-only access. Chat is disabled."
              }
            />
          </div>
        </div>
      </aside>

      <aside
        className={cn(
          "fixed right-0 top-0 z-50 h-full w-[520px] max-w-[96vw] transform border-l border-slate-200 bg-white shadow-2xl transition-transform",
          isLiveFeedOpen ? "transform-none" : "translate-x-full",
        )}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Live feed
              </p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                Realtime task, approval, agent, and board-chat activity.
              </p>
            </div>
            <button
              type="button"
              onClick={closeLiveFeed}
              className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
              aria-label="Close live feed"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {isLiveFeedHistoryLoading && orderedLiveFeed.length === 0 ? (
              <p className="text-sm text-slate-500">Loading feed…</p>
            ) : liveFeedHistoryError ? (
              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm">
                {liveFeedHistoryError}
              </div>
            ) : orderedLiveFeed.length === 0 ? (
              <p className="text-sm text-slate-500">
                Waiting for new activity…
              </p>
            ) : (
              <div className="space-y-3">
                {orderedLiveFeed.map((item) => {
                  const taskId = item.task_id;
                  const authorAgent = item.agent_id
                    ? (agents.find((agent) => agent.id === item.agent_id) ??
                      null)
                    : null;
                  const authorName =
                    authorAgent?.name ??
                    resolveHumanActorName(
                      item.actor_name,
                      currentUserDisplayName,
                    );
                  const authorRole = authorAgent
                    ? agentRoleLabel(authorAgent)
                    : null;
                  const authorAvatar = authorAgent
                    ? agentAvatarLabel(authorAgent)
                    : (authorName[0] ?? "A").toUpperCase();
                  return (
                    <LiveFeedCard
                      key={item.id}
                      item={item}
                      isNew={Boolean(liveFeedFlashIds[item.id])}
                      taskTitle={
                        item.title
                          ? item.title
                          : taskId
                            ? (taskTitleById.get(taskId) ?? "Unknown task")
                            : "Activity"
                      }
                      authorName={authorName}
                      authorRole={authorRole}
                      authorAvatar={authorAvatar}
                      onViewTask={
                        taskId ? () => openComments({ id: taskId }) : undefined
                      }
                    />
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </aside>

      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent aria-label="Edit task">
          <DialogHeader>
            <DialogTitle>Edit task</DialogTitle>
            <DialogDescription>
              Update task details, priority, status, or assignment.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Title
              </label>
              <Input
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
                placeholder="Task title"
                disabled={!selectedTask || isSavingTask || !canWrite}
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Description
              </label>
              <Textarea
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
                placeholder="Task details"
                className="min-h-[140px]"
                disabled={!selectedTask || isSavingTask || !canWrite}
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Custom fields
              </label>
              <TaskCustomFieldsEditor
                definitions={boardCustomFieldDefinitions}
                values={editCustomFieldValues}
                setValues={setEditCustomFieldValues}
                isLoading={customFieldDefinitionsQuery.isLoading}
                disabled={!selectedTask || isSavingTask || !canWrite}
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Status
                </label>
                <Select
                  value={editStatus}
                  onValueChange={(value) => setEditStatus(value as TaskStatus)}
                  disabled={!selectedTask || isSavingTask || !canWrite}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select status" />
                  </SelectTrigger>
                  <SelectContent>
                    {statusOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Priority
                </label>
                <Select
                  value={editPriority}
                  onValueChange={setEditPriority}
                  disabled={!selectedTask || isSavingTask || !canWrite}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select priority" />
                  </SelectTrigger>
                  <SelectContent>
                    {priorities.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Due date
                </label>
                <Input
                  type="date"
                  value={editDueDate}
                  onChange={(event) => setEditDueDate(event.target.value)}
                  disabled={!selectedTask || isSavingTask || !canWrite}
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Assignee
              </label>
              <Select
                value={editAssigneeId || "unassigned"}
                onValueChange={(value) =>
                  setEditAssigneeId(value === "unassigned" ? "" : value)
                }
                disabled={!selectedTask || isSavingTask || !canWrite}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Unassigned" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="unassigned">Unassigned</SelectItem>
                  {assignableAgents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {assignableAgents.length === 0 ? (
                <p className="text-xs text-slate-500">
                  Add agents to assign tasks.
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Tags
                </label>
                <button
                  type="button"
                  onClick={() => router.push("/tags")}
                  className="text-xs font-medium text-slate-500 underline underline-offset-2 transition hover:text-slate-700"
                >
                  Manage tags
                </button>
              </div>
              <DropdownSelect
                ariaLabel="Add tag"
                placeholder="Add tag"
                options={editTagOptions}
                onValueChange={addEditTag}
                disabled={!selectedTask || isSavingTask || !canWrite}
                emptyMessage="No tags configured."
              />
              {editTagIds.length === 0 ? (
                <p className="text-xs text-slate-500">No tags assigned.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {editTagIds.map((tagId) => {
                    const tag = tagById.get(tagId);
                    const label = tag?.name ?? tagId;
                    const color = normalizeTagColor(tag?.color);
                    return (
                      <span
                        key={tagId}
                        className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-700"
                      >
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ backgroundColor: `#${color}` }}
                        />
                        <span className="max-w-[16rem] truncate">{label}</span>
                        <button
                          type="button"
                          onClick={() => removeEditTag(tagId)}
                          className={cn(
                            "rounded-full p-0.5 text-slate-500 transition",
                            canWrite
                              ? "hover:bg-white hover:text-slate-700"
                              : "opacity-50 cursor-not-allowed",
                          )}
                          aria-label="Remove tag"
                          disabled={!canWrite}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Dependencies
              </label>
              <p className="text-xs text-slate-500">
                Tasks stay blocked until every dependency is marked done.
              </p>
              <DropdownSelect
                ariaLabel="Add dependency"
                placeholder="Add dependency"
                options={dependencyOptions}
                onValueChange={addTaskDependency}
                disabled={
                  !selectedTask ||
                  isSavingTask ||
                  selectedTask.status === "done" ||
                  !canWrite
                }
                emptyMessage="No other tasks found."
              />
              {selectedTask?.status === "done" ? (
                <p className="text-xs text-slate-500">
                  Dependencies can only be edited until the task is done.
                </p>
              ) : null}
              {editDependsOnTaskIds.length === 0 ? (
                <p className="text-xs text-slate-500">No dependencies.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {editDependsOnTaskIds.map((depId) => {
                    const depTask = taskById.get(depId);
                    const label = depTask?.title ?? depId;
                    const statusLabel = depTask?.status
                      ? depTask.status.replace(/_/g, " ")
                      : null;
                    const isDone = depTask?.status === "done";
                    return (
                      <span
                        key={depId}
                        className={cn(
                          "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs",
                          isDone
                            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                            : "border-slate-200 bg-slate-50 text-slate-700",
                        )}
                      >
                        <span className="max-w-[18rem] truncate">{label}</span>
                        {statusLabel ? (
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                            {statusLabel}
                          </span>
                        ) : null}
                        {selectedTask?.status !== "done" ? (
                          <button
                            type="button"
                            onClick={() => removeTaskDependency(depId)}
                            className={cn(
                              "rounded-full p-0.5 text-slate-500 transition",
                              canWrite
                                ? "hover:bg-white hover:text-slate-700"
                                : "opacity-50 cursor-not-allowed",
                            )}
                            aria-label="Remove dependency"
                            disabled={!canWrite}
                          >
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
            {saveTaskError ? (
              <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
                {saveTaskError}
              </div>
            ) : null}
          </div>
          <DialogFooter className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(true)}
              disabled={!selectedTask || isSavingTask || !canWrite}
              className="border-rose-200 text-rose-600 hover:border-rose-300 hover:text-rose-700"
              title={canWrite ? "Delete task" : "Read-only access"}
            >
              Delete task
            </Button>
            <Button
              variant="outline"
              onClick={handleTaskReset}
              disabled={
                !selectedTask || isSavingTask || !hasTaskChanges || !canWrite
              }
            >
              Reset
            </Button>
            <Button
              onClick={() => handleTaskSave(true)}
              disabled={
                !selectedTask || isSavingTask || !hasTaskChanges || !canWrite
              }
            >
              {isSavingTask ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent aria-label="Delete task">
          <DialogHeader>
            <DialogTitle>Delete task</DialogTitle>
            <DialogDescription>
              This removes the task permanently. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {deleteTaskError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
              {deleteTaskError}
            </div>
          ) : null}
          <DialogFooter className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(false)}
              disabled={isDeletingTask}
            >
              Cancel
            </Button>
            <Button
              onClick={handleDeleteTask}
              disabled={isDeletingTask || !canWrite}
              className="bg-rose-600 text-white hover:bg-rose-700"
            >
              {isDeletingTask ? "Deleting…" : "Delete task"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={isDialogOpen}
        onOpenChange={(nextOpen) => {
          setIsDialogOpen(nextOpen);
          if (!nextOpen) {
            resetForm();
          }
        }}
      >
        <DialogContent aria-label={titleLabel}>
          <DialogHeader>
            <DialogTitle>New task</DialogTitle>
            <DialogDescription>
              Add a task to the inbox and triage it when you are ready.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-strong">Title</label>
              <Input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="e.g. Prepare launch notes"
                disabled={!canWrite || isCreating}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-strong">
                Description
              </label>
              <Textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Optional details"
                className="min-h-[120px]"
                disabled={!canWrite || isCreating}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-strong">
                Custom fields
              </label>
              <TaskCustomFieldsEditor
                definitions={boardCustomFieldDefinitions}
                values={createCustomFieldValues}
                setValues={setCreateCustomFieldValues}
                isLoading={customFieldDefinitionsQuery.isLoading}
                disabled={!canWrite || isCreating}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-strong">
                Priority
              </label>
              <Select
                value={priority}
                onValueChange={setPriority}
                disabled={!canWrite || isCreating}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select priority" />
                </SelectTrigger>
                <SelectContent>
                  {priorities.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-strong">
                Due date
              </label>
              <Input
                type="date"
                value={createDueDate}
                onChange={(event) => setCreateDueDate(event.target.value)}
                disabled={!canWrite || isCreating}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-sm font-medium text-strong">Tags</label>
                <button
                  type="button"
                  onClick={() => router.push("/tags")}
                  className="text-xs font-medium text-slate-500 underline underline-offset-2 transition hover:text-slate-700"
                >
                  Manage tags
                </button>
              </div>
              <DropdownSelect
                ariaLabel="Add tag"
                placeholder="Add tag"
                options={createTagOptions}
                onValueChange={addCreateTag}
                disabled={!canWrite || isCreating}
                emptyMessage="No tags configured."
              />
              {createTagIds.length ? (
                <div className="flex flex-wrap gap-2">
                  {createTagIds.map((tagId) => {
                    const tag = tagById.get(tagId);
                    const color = normalizeTagColor(tag?.color);
                    return (
                      <span
                        key={tagId}
                        className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-700"
                      >
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ backgroundColor: `#${color}` }}
                        />
                        {tag?.name ?? tagId}
                        <button
                          type="button"
                          onClick={() => removeCreateTag(tagId)}
                          className="rounded-full p-0.5 text-slate-500 transition hover:bg-white hover:text-slate-700"
                          aria-label="Remove tag"
                          disabled={!canWrite || isCreating}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              ) : (
                <p className="text-xs text-slate-500">No tags assigned.</p>
              )}
            </div>
            {createError ? (
              <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
                {createError}
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateTask}
              disabled={!canWrite || isCreating}
            >
              {isCreating ? "Creating…" : "Create task"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isOrgAdmin ? (
        <Dialog
          open={isAgentsControlDialogOpen}
          onOpenChange={(nextOpen) => {
            setIsAgentsControlDialogOpen(nextOpen);
            if (!nextOpen) {
              setAgentsControlError(null);
            }
          }}
        >
          <DialogContent aria-label="Agent controls">
            <DialogHeader>
              <DialogTitle>
                {agentsControlAction === "pause"
                  ? "Pause agents"
                  : "Resume agents"}
              </DialogTitle>
              <DialogDescription>
                {agentsControlAction === "pause"
                  ? "Send /pause to every agent on this board."
                  : "Send /resume to every agent on this board."}
              </DialogDescription>
            </DialogHeader>

            {agentsControlError ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                {agentsControlError}
              </div>
            ) : null}

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
              <p className="font-semibold text-slate-900">What happens</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>
                  This posts{" "}
                  <span className="font-mono">
                    {agentsControlAction === "pause" ? "/pause" : "/resume"}
                  </span>{" "}
                  to board chat.
                </li>
                <li>
                  Mission Control forwards it to all agents on this board.
                </li>
              </ul>
            </div>

            <DialogFooter className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => setIsAgentsControlDialogOpen(false)}
                disabled={isAgentsControlSending}
              >
                Cancel
              </Button>
              <Button
                onClick={handleConfirmAgentsControl}
                disabled={isAgentsControlSending}
              >
                {isAgentsControlSending
                  ? "Sending…"
                  : agentsControlAction === "pause"
                    ? "Pause agents"
                    : "Resume agents"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

      {toasts.length ? (
        <div className="fixed bottom-6 right-6 z-[60] flex w-[320px] max-w-[90vw] flex-col gap-3">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={cn(
                "rounded-xl border bg-white px-4 py-3 text-sm shadow-lush",
                toast.tone === "error"
                  ? "border-rose-200 text-rose-700"
                  : "border-emerald-200 text-emerald-700",
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "mt-1 h-2 w-2 rounded-full",
                    toast.tone === "error" ? "bg-rose-500" : "bg-emerald-500",
                  )}
                />
                <p className="flex-1 text-sm text-slate-700">{toast.message}</p>
                <button
                  type="button"
                  className="text-xs text-slate-400 hover:text-slate-600"
                  onClick={() => dismissToast(toast.id)}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* onboarding moved to board settings */}
    </DashboardShell>
  );
}
