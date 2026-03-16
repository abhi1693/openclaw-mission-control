import type { ReactNode } from "react";
import Link from "next/link";

import { StatusPill } from "@/components/atoms/StatusPill";
import {
  formatRelativeTimestamp as formatRelative,
  formatTimestamp,
} from "@/lib/formatters";
import { cn } from "@/lib/utils";

type LinkifyCellOptions = {
  href: string;
  label: ReactNode;
  subtitle?: ReactNode;
  title?: string;
  block?: boolean;
  className?: string;
  labelClassName?: string;
  subtitleClassName?: string;
};

type DateCellOptions = {
  relative?: boolean;
  className?: string;
  fallback?: ReactNode;
};

export function linkifyCell({
  href,
  label,
  subtitle,
  title,
  block = subtitle != null,
  className,
  labelClassName,
  subtitleClassName,
}: LinkifyCellOptions) {
  if (block) {
    return (
      <Link href={href} title={title} className={cn("group block", className)}>
        <p
          className={cn(
            "text-sm font-medium text-slate-900 group-hover:text-blue-600",
            labelClassName,
          )}
        >
          {label}
        </p>
        {subtitle != null ? (
          <p className={cn("text-xs text-slate-500", subtitleClassName)}>
            {subtitle}
          </p>
        ) : null}
      </Link>
    );
  }

  return (
    <Link
      href={href}
      title={title}
      className={cn(
        "text-sm font-medium text-slate-700 hover:text-blue-600",
        className,
      )}
    >
      {label}
    </Link>
  );
}

export function pillCell(
  value: string | null | undefined,
  fallback = "unknown",
) {
  return <StatusPill status={value ?? fallback} />;
}

export function dateCell(
  value: string | null | undefined,
  { relative = false, className, fallback = "—" }: DateCellOptions = {},
) {
  const display = relative ? formatRelative(value) : formatTimestamp(value);
  return (
    <span className={cn("text-sm text-slate-700", className)}>
      {display ?? fallback}
    </span>
  );
}
