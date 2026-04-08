import { cn } from "@/lib/utils";

type StatusDotVariant = "agent" | "approval" | "task";

const AGENT_STATUS_DOT_CLASS_BY_STATUS: Record<string, string> = {
  online: "bg-[var(--success)]",
  busy: "bg-[var(--warning)]",
  provisioning: "bg-[var(--warning)]",
  updating: "bg-[var(--accent)]",
  deleting: "bg-[var(--danger)]",
  offline: "bg-[var(--text-quiet)]",
};

const APPROVAL_STATUS_DOT_CLASS_BY_STATUS: Record<string, string> = {
  approved: "bg-[var(--success)]",
  rejected: "bg-[var(--danger)]",
  pending: "bg-[var(--warning)]",
};

const TASK_STATUS_DOT_CLASS_BY_STATUS: Record<string, string> = {
  inbox: "bg-[var(--text-quiet)]",
  in_progress: "bg-[var(--accent)]",
  review: "bg-[var(--accent-strong)]",
  done: "bg-[var(--success)]",
};

const STATUS_DOT_CLASS_BY_VARIANT: Record<
  StatusDotVariant,
  Record<string, string>
> = {
  agent: AGENT_STATUS_DOT_CLASS_BY_STATUS,
  approval: APPROVAL_STATUS_DOT_CLASS_BY_STATUS,
  task: TASK_STATUS_DOT_CLASS_BY_STATUS,
};

const DEFAULT_STATUS_DOT_CLASS: Record<StatusDotVariant, string> = {
  agent: "bg-[var(--text-muted)]",
  approval: "bg-[var(--warning)]",
  task: "bg-[var(--text-muted)]",
};

export const statusDotClass = (
  status: string | null | undefined,
  variant: StatusDotVariant = "agent",
) => {
  const normalized = (status ?? "").trim().toLowerCase();
  if (!normalized) {
    return DEFAULT_STATUS_DOT_CLASS[variant];
  }
  return (
    STATUS_DOT_CLASS_BY_VARIANT[variant][normalized] ??
    DEFAULT_STATUS_DOT_CLASS[variant]
  );
};

type StatusDotProps = {
  status?: string | null;
  variant?: StatusDotVariant;
  className?: string;
};

export function StatusDot({
  status,
  variant = "agent",
  className,
}: StatusDotProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block h-2.5 w-2.5 rounded-full",
        statusDotClass(status, variant),
        className,
      )}
    />
  );
}
