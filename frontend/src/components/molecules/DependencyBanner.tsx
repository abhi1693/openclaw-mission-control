import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface DependencyBannerDependency {
  id: string;
  title: string;
  statusLabel: string;
  isBlocking?: boolean;
  isDone?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}

interface DependencyBannerProps {
  variant?: DependencyBannerVariant;
  dependencies?: DependencyBannerDependency[];
  children?: ReactNode;
  className?: string;
  emptyMessage?: string;
}

type DependencyBannerVariant = "blocked" | "resolved";

const toneClassByVariant: Record<DependencyBannerVariant, string> = {
  blocked: "border-rose-200 bg-rose-50 text-rose-700",
  resolved: "border-blue-200 bg-blue-50 text-blue-700",
};

export function DependencyBanner({
  variant = "blocked",
  dependencies = [],
  children,
  className,
  emptyMessage = "No dependencies.",
}: DependencyBannerProps) {
  return (
    <div className={cn("space-y-2", className)}>
      {dependencies.length > 0 ? (
        dependencies.map((dependency) => {
          const isBlocking = dependency.isBlocking === true;
          const isDone = dependency.isDone === true;
          return (
            <button
              key={dependency.id}
              type="button"
              onClick={dependency.onClick}
              disabled={dependency.disabled}
              className={cn(
                "w-full rounded-lg border px-3 py-2 text-left transition",
                isBlocking
                  ? "border-rose-200 bg-rose-50 hover:bg-rose-100/40"
                  : isDone
                    ? "border-emerald-200 bg-emerald-50 hover:bg-emerald-100/40"
                    : "border-slate-200 bg-white hover:bg-slate-50",
                dependency.disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="truncate text-sm font-medium text-slate-900">
                  {dependency.title}
                </p>
                <span
                  className={cn(
                    "text-[10px] font-semibold uppercase tracking-wide",
                    isBlocking
                      ? "text-rose-700"
                      : isDone
                        ? "text-emerald-700"
                        : "text-slate-500",
                  )}
                >
                  {dependency.statusLabel}
                </span>
              </div>
            </button>
          );
        })
      ) : (
        <p className="text-sm text-slate-500">{emptyMessage}</p>
      )}
      {children ? (
        <div
          className={cn(
            "rounded-lg border p-3 text-xs",
            toneClassByVariant[variant],
          )}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
