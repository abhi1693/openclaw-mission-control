"use client";

import {
  memo,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { TaskCard } from "@/components/molecules/TaskCard";
import { parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

type TaskStatus = "inbox" | "in_progress" | "review" | "done";

type Task = {
  id: string;
  title: string;
  status: TaskStatus;
  priority: string;
  description?: string | null;
  due_at?: string | null;
  assigned_agent_id?: string | null;
  assignee?: string | null;
  approvals_pending_count?: number;
  tags?: Array<{ id: string; name: string; slug: string; color: string }>;
  depends_on_task_ids?: string[];
  blocked_by_task_ids?: string[];
  is_blocked?: boolean;
};

type TaskBoardProps = {
  tasks: Task[];
  onTaskSelect?: (task: Task) => void;
  onTaskMove?: (taskId: string, status: TaskStatus) => void | Promise<void>;
  readOnly?: boolean;
};

type ReviewBucket = "all" | "approval_needed" | "waiting_lead" | "blocked";

const columns: Array<{
  title: string;
  status: TaskStatus;
  dot: string;
  accent: string;
  text: string;
  badge: string;
}> = [
  {
    title: "Inbox",
    status: "inbox",
    dot: "bg-slate-400",
    accent: "hover:border-slate-400 hover:bg-slate-50",
    text: "group-hover:text-slate-700 text-slate-500",
    badge: "bg-slate-100 text-slate-600",
  },
  {
    title: "In Progress",
    status: "in_progress",
    dot: "bg-purple-500",
    accent: "hover:border-purple-400 hover:bg-purple-50",
    text: "group-hover:text-purple-600 text-slate-500",
    badge: "bg-purple-100 text-purple-700",
  },
  {
    title: "Review",
    status: "review",
    dot: "bg-indigo-500",
    accent: "hover:border-indigo-400 hover:bg-indigo-50",
    text: "group-hover:text-indigo-600 text-slate-500",
    badge: "bg-indigo-100 text-indigo-700",
  },
  {
    title: "Done",
    status: "done",
    dot: "bg-green-500",
    accent: "hover:border-green-400 hover:bg-green-50",
    text: "group-hover:text-green-600 text-slate-500",
    badge: "bg-emerald-100 text-emerald-700",
  },
];

const resolveDueState = (
  task: Task,
): { due: string | undefined; isOverdue: boolean } => {
  const date = parseApiDatetime(task.due_at);
  if (!date) return { due: undefined, isOverdue: false };
  const dueLabel = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const isOverdue = task.status !== "done" && date.getTime() < Date.now();
  return {
    due: isOverdue ? `Overdue · ${dueLabel}` : dueLabel,
    isOverdue,
  };
};

type CardPosition = { left: number; top: number };

const KANBAN_MOVE_ANIMATION_MS = 240;
const KANBAN_MOVE_EASING = "cubic-bezier(0.2, 0.8, 0.2, 1)";

export const TaskBoard = memo(function TaskBoard({
  tasks,
  onTaskSelect,
  onTaskMove,
  readOnly = false,
}: TaskBoardProps) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const prevPositionsRef = useRef<Map<string, CardPosition>>(new Map());
  const animationRafRef = useRef<number | null>(null);
  const cleanupTimeoutRef = useRef<number | null>(null);
  const animatedTaskIdsRef = useRef<Set<string>>(new Set());

  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [activeColumn, setActiveColumn] = useState<TaskStatus | null>(null);
  const [reviewBucket, setReviewBucket] = useState<ReviewBucket>("all");

  const setCardRef = useCallback(
    (taskId: string) => (node: HTMLDivElement | null) => {
      if (node) {
        cardRefs.current.set(taskId, node);
        return;
      }
      cardRefs.current.delete(taskId);
    },
    [],
  );

  const measurePositions = useCallback((): Map<string, CardPosition> => {
    const positions = new Map<string, CardPosition>();
    const container = boardRef.current;
    const containerRect = container?.getBoundingClientRect();
    const scrollLeft = container?.scrollLeft ?? 0;
    const scrollTop = container?.scrollTop ?? 0;

    for (const [taskId, element] of cardRefs.current.entries()) {
      const rect = element.getBoundingClientRect();
      positions.set(taskId, {
        left:
          containerRect && container
            ? rect.left - containerRect.left + scrollLeft
            : rect.left,
        top:
          containerRect && container
            ? rect.top - containerRect.top + scrollTop
            : rect.top,
      });
    }

    return positions;
  }, []);

  // Animate card reordering smoothly by applying FLIP whenever layout positions change.
  useLayoutEffect(() => {
    const cardRefsSnapshot = cardRefs.current;
    if (animationRafRef.current !== null) {
      window.cancelAnimationFrame(animationRafRef.current);
      animationRafRef.current = null;
    }
    if (cleanupTimeoutRef.current !== null) {
      window.clearTimeout(cleanupTimeoutRef.current);
      cleanupTimeoutRef.current = null;
    }
    for (const taskId of animatedTaskIdsRef.current) {
      const element = cardRefsSnapshot.get(taskId);
      if (!element) continue;
      element.style.transform = "";
      element.style.transition = "";
      element.style.willChange = "";
      element.style.position = "";
      element.style.zIndex = "";
    }
    animatedTaskIdsRef.current.clear();

    const prevPositions = prevPositionsRef.current;
    const nextPositions = measurePositions();
    prevPositionsRef.current = nextPositions;

    // Avoid fighting the browser while it manages the drag image.
    if (draggingId) return;

    const prefersReducedMotion =
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    if (prefersReducedMotion) return;

    const moved: Array<{
      taskId: string;
      element: HTMLDivElement;
      dx: number;
      dy: number;
    }> = [];
    for (const [taskId, next] of nextPositions.entries()) {
      const prev = prevPositions.get(taskId);
      if (!prev) continue;
      const dx = prev.left - next.left;
      const dy = prev.top - next.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      const element = cardRefsSnapshot.get(taskId);
      if (!element) continue;
      moved.push({ taskId, element, dx, dy });
    }

    if (!moved.length) return;
    animatedTaskIdsRef.current = new Set(moved.map(({ taskId }) => taskId));

    // FLIP: invert to the previous position before paint, then animate back to 0.
    for (const { element, dx, dy } of moved) {
      element.style.transform = `translate(${dx}px, ${dy}px)`;
      element.style.transition = "transform 0s";
      element.style.willChange = "transform";
      element.style.position = "relative";
      element.style.zIndex = "1";
    }

    animationRafRef.current = window.requestAnimationFrame(() => {
      for (const { element } of moved) {
        element.style.transition = `transform ${KANBAN_MOVE_ANIMATION_MS}ms ${KANBAN_MOVE_EASING}`;
        element.style.transform = "";
      }

      cleanupTimeoutRef.current = window.setTimeout(() => {
        for (const { element } of moved) {
          element.style.transition = "";
          element.style.willChange = "";
          element.style.position = "";
          element.style.zIndex = "";
        }
        animatedTaskIdsRef.current.clear();
        cleanupTimeoutRef.current = null;
      }, KANBAN_MOVE_ANIMATION_MS + 60);

      animationRafRef.current = null;
    });

    return () => {
      if (animationRafRef.current !== null) {
        window.cancelAnimationFrame(animationRafRef.current);
        animationRafRef.current = null;
      }
      if (cleanupTimeoutRef.current !== null) {
        window.clearTimeout(cleanupTimeoutRef.current);
        cleanupTimeoutRef.current = null;
      }
      for (const taskId of animatedTaskIdsRef.current) {
        const element = cardRefsSnapshot.get(taskId);
        if (!element) continue;
        element.style.transform = "";
        element.style.transition = "";
        element.style.willChange = "";
        element.style.position = "";
        element.style.zIndex = "";
      }
      animatedTaskIdsRef.current.clear();
    };
  }, [draggingId, measurePositions, tasks]);

  const grouped = useMemo(() => {
    const buckets: Record<TaskStatus, Task[]> = {
      inbox: [],
      in_progress: [],
      review: [],
      done: [],
    };
    for (const column of columns) {
      buckets[column.status] = [];
    }
    tasks.forEach((task) => {
      const bucket = buckets[task.status] ?? buckets.inbox;
      bucket.push(task);
    });
    return buckets;
  }, [tasks]);

  // Keep drag/drop state and payload handling centralized for column move interactions.
  const handleDragStart =
    (task: Task) => (event: React.DragEvent<HTMLDivElement>) => {
      if (readOnly) {
        event.preventDefault();
        return;
      }
      if (task.is_blocked) {
        event.preventDefault();
        return;
      }
      setDraggingId(task.id);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(
        "text/plain",
        JSON.stringify({ taskId: task.id, status: task.status }),
      );
    };

  const handleDragEnd = () => {
    setDraggingId(null);
    setActiveColumn(null);
  };

  const handleDrop =
    (status: TaskStatus) => (event: React.DragEvent<HTMLDivElement>) => {
      if (readOnly) return;
      event.preventDefault();
      setActiveColumn(null);
      const raw = event.dataTransfer.getData("text/plain");
      if (!raw) return;
      try {
        const payload = JSON.parse(raw) as { taskId?: string; status?: string };
        if (!payload.taskId || !payload.status) return;
        if (payload.status === status) return;
        onTaskMove?.(payload.taskId, status);
      } catch {
        // Ignore malformed payloads.
      }
    };

  const handleDragOver =
    (status: TaskStatus) => (event: React.DragEvent<HTMLDivElement>) => {
      if (readOnly) return;
      event.preventDefault();
      if (activeColumn !== status) {
        setActiveColumn(status);
      }
    };

  const handleDragLeave = (status: TaskStatus) => () => {
    if (readOnly) return;
    if (activeColumn === status) {
      setActiveColumn(null);
    }
  };

  return (
    <div
      ref={boardRef}
      data-testid="task-board"
      className={cn(
        // Mobile-first: stack columns vertically to avoid horizontal scrolling.
        "grid grid-cols-1 gap-4 overflow-x-hidden pb-6",
        // Desktop/tablet: switch back to horizontally scrollable kanban columns.
        "sm:grid-flow-col sm:auto-cols-[minmax(260px,320px)] sm:grid-cols-none sm:overflow-x-auto",
      )}
    >
      {columns.map((column) => {
        const columnTasks = grouped[column.status] ?? [];
        // Derive review tab counts and the active subset from one canonical task list.
        const reviewCounts =
          column.status === "review"
            ? columnTasks.reduce(
                (acc, task) => {
                  if (task.is_blocked) {
                    acc.blocked += 1;
                    return acc;
                  }
                  if ((task.approvals_pending_count ?? 0) > 0) {
                    acc.approval_needed += 1;
                    return acc;
                  }
                  acc.waiting_lead += 1;
                  return acc;
                },
                {
                  all: columnTasks.length,
                  approval_needed: 0,
                  waiting_lead: 0,
                  blocked: 0,
                },
              )
            : null;

        const filteredTasks =
          column.status === "review" && reviewBucket !== "all"
            ? columnTasks.filter((task) => {
                if (reviewBucket === "blocked") return Boolean(task.is_blocked);
                if (reviewBucket === "approval_needed")
                  return (
                    (task.approvals_pending_count ?? 0) > 0 && !task.is_blocked
                  );
                if (reviewBucket === "waiting_lead")
                  return (
                    !task.is_blocked &&
                    (task.approvals_pending_count ?? 0) === 0
                  );
                return true;
              })
            : columnTasks;

        return (
          <div
            key={column.title}
            className={cn(
              // On mobile, columns are stacked, so avoid forcing tall fixed heights.
              "kanban-column min-h-0",
              // On larger screens, keep columns tall to reduce empty space during drag.
              "sm:min-h-[calc(100vh-260px)]",
              activeColumn === column.status &&
                !readOnly &&
                "ring-2 ring-slate-200",
            )}
            onDrop={readOnly ? undefined : handleDrop(column.status)}
            onDragOver={readOnly ? undefined : handleDragOver(column.status)}
            onDragLeave={readOnly ? undefined : handleDragLeave(column.status)}
          >
            <div className="column-header z-10 rounded-t-xl border border-b-0 border-slate-200 bg-white px-4 py-3 sm:sticky sm:top-0 sm:bg-white/80 sm:backdrop-blur">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={cn("h-2 w-2 rounded-full", column.dot)} />
                  <h3 className="text-sm font-semibold text-slate-900">
                    {column.title}
                  </h3>
                </div>
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                    column.badge,
                  )}
                >
                  {filteredTasks.length}
                </span>
              </div>
              {column.status === "review" && reviewCounts ? (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {(
                    [
                      { key: "all", label: "All", count: reviewCounts.all },
                      {
                        key: "approval_needed",
                        label: "Approval needed",
                        count: reviewCounts.approval_needed,
                      },
                      {
                        key: "waiting_lead",
                        label: "Lead review",
                        count: reviewCounts.waiting_lead,
                      },
                      {
                        key: "blocked",
                        label: "Blocked",
                        count: reviewCounts.blocked,
                      },
                    ] as const
                  ).map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => setReviewBucket(option.key)}
                      className={cn(
                        "rounded-full border px-2.5 py-1 transition",
                        reviewBucket === option.key
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50",
                      )}
                      aria-pressed={reviewBucket === option.key}
                    >
                      {option.label} · {option.count}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <div className="rounded-b-xl border border-t-0 border-slate-200 bg-white p-3">
              <div className="space-y-3">
                {filteredTasks.map((task) => {
                  const dueState = resolveDueState(task);
                  return (
                    <div key={task.id} ref={setCardRef(task.id)}>
                      <TaskCard
                        title={task.title}
                        status={task.status}
                        priority={task.priority}
                        assignee={task.assignee ?? undefined}
                        due={dueState.due}
                        isOverdue={dueState.isOverdue}
                        approvalsPendingCount={task.approvals_pending_count}
                        tags={task.tags}
                        isBlocked={task.is_blocked}
                        blockedByCount={task.blocked_by_task_ids?.length ?? 0}
                        onClick={() => onTaskSelect?.(task)}
                        draggable={!readOnly && !task.is_blocked}
                        isDragging={draggingId === task.id}
                        onDragStart={
                          readOnly ? undefined : handleDragStart(task)
                        }
                        onDragEnd={readOnly ? undefined : handleDragEnd}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
});

TaskBoard.displayName = "TaskBoard";
