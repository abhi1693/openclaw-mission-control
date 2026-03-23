import { CalendarClock, UserCircle } from "lucide-react";

import { cn } from "@/lib/utils";

type TaskStatus = "inbox" | "in_progress" | "review" | "done";

interface TaskCardProps {
  title: string;
  status?: TaskStatus;
  priority?: string;
  assignee?: string;
  due?: string;
  isOverdue?: boolean;
  approvalsPendingCount?: number;
  tags?: Array<{ id: string; name: string; color: string }>;
  isBlocked?: boolean;
  blockedByCount?: number;
  onClick?: () => void;
  draggable?: boolean;
  isDragging?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLDivElement>) => void;
  onDragEnd?: (event: React.DragEvent<HTMLDivElement>) => void;
}

export function TaskCard({
  title,
  status,
  priority,
  assignee,
  due,
  isOverdue = false,
  approvalsPendingCount = 0,
  tags = [],
  isBlocked = false,
  blockedByCount = 0,
  onClick,
  draggable = false,
  isDragging = false,
  onDragStart,
  onDragEnd,
}: TaskCardProps) {
  const hasPendingApproval = approvalsPendingCount > 0;
  const needsLeadReview =
    status === "review" && !isBlocked && !hasPendingApproval;
  const leftBarClassName = isBlocked
    ? "bg-rose-400"
    : hasPendingApproval
      ? "bg-amber-400"
      : needsLeadReview
        ? "bg-indigo-400"
        : null;
  const priorityBadge = (value?: string) => {
    if (!value) return null;
    const normalized = value.toLowerCase();
    if (normalized === "high") {
      return "bg-rose-400/15 text-rose-300";
    }
    if (normalized === "medium") {
      return "bg-amber-400/15 text-amber-300";
    }
    if (normalized === "low") {
      return "bg-emerald-500/15 text-emerald-300";
    }
    return "bg-[color:var(--surface-muted)] text-muted";
  };

  const priorityLabel = priority ? priority.toUpperCase() : "MEDIUM";
  const visibleTags = tags.slice(0, 3);

  return (
    <div
      className={cn(
        "group relative cursor-pointer rounded-lg border border-[color:var(--border)] bg-[color:var(--surface)] p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-[color:var(--border-strong)] hover:shadow-md",
        isDragging && "opacity-60 shadow-none",
        hasPendingApproval && "border-amber-500/30 bg-amber-400/8",
        isBlocked && "border-rose-500/30 bg-rose-400/8",
        needsLeadReview && "border-indigo-500/30 bg-indigo-400/8",
      )}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick?.();
        }
      }}
    >
      {leftBarClassName ? (
        <span
          className={cn(
            "absolute left-0 top-0 h-full w-1 rounded-l-lg",
            leftBarClassName,
          )}
        />
      ) : null}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-medium text-strong line-clamp-2 break-words">
            {title}
          </p>
          {isBlocked ? (
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-rose-300">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
              Blocked{blockedByCount > 0 ? ` · ${blockedByCount}` : ""}
            </div>
          ) : null}
          {hasPendingApproval ? (
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              Approval needed · {approvalsPendingCount}
            </div>
          ) : null}
          {needsLeadReview ? (
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-indigo-300">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
              Waiting for lead review
            </div>
          ) : null}
          {visibleTags.length ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {visibleTags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 rounded-full border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-2 py-0.5 text-[10px] font-semibold text-strong"
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: `#${tag.color}` }}
                  />
                  {tag.name}
                </span>
              ))}
              {tags.length > visibleTags.length ? (
                <span className="text-[10px] font-semibold text-muted">
                  +{tags.length - visibleTags.length}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex flex-shrink-0 flex-col items-end gap-2">
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
              priorityBadge(priority) ?? "bg-[color:var(--surface-muted)] text-muted",
            )}
          >
            {priorityLabel}
          </span>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-muted">
        <div className="flex items-center gap-2">
          <UserCircle className="h-4 w-4 text-quiet" />
          <span>{assignee ?? "Unassigned"}</span>
        </div>
        {due ? (
          <div
            className={cn(
              "flex items-center gap-2",
              isOverdue && "font-semibold text-rose-300",
            )}
          >
            <CalendarClock
              className={cn(
                "h-4 w-4",
                isOverdue ? "text-rose-400" : "text-quiet",
              )}
            />
            <span>{due}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
