import type { ReactNode } from "react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

type TableLoadingRowProps = {
  colSpan: number;
  label?: string;
};

export function TableLoadingRow({
  colSpan,
  label = "Loading…",
}: TableLoadingRowProps) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-6 py-8">
        <span className="text-sm text-slate-500">{label}</span>
      </td>
    </tr>
  );
}

type TableEmptyStateRowProps = {
  colSpan: number;
  icon: ReactNode;
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
};

export function TableEmptyStateRow({
  colSpan,
  icon,
  title,
  description,
  actionHref,
  actionLabel,
}: TableEmptyStateRowProps) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-6 py-16">
        <div className="flex flex-col items-center justify-center text-center">
          <div className="mb-4 rounded-full bg-slate-50 p-4">{icon}</div>
          <h3 className="mb-2 text-lg font-semibold text-slate-900">{title}</h3>
          <p className="mb-6 max-w-md text-sm text-slate-500">{description}</p>
          {actionHref && actionLabel ? (
            <Link
              href={actionHref}
              className={buttonVariants({ size: "md", variant: "primary" })}
            >
              {actionLabel}
            </Link>
          ) : null}
        </div>
      </td>
    </tr>
  );
}
