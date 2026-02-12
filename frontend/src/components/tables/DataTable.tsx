import type { ReactNode } from "react";
import Link from "next/link";

import { type Row, type Table, flexRender } from "@tanstack/react-table";

import {
  TableEmptyStateRow,
  TableLoadingRow,
} from "@/components/ui/table-state";
import { Button, buttonVariants } from "@/components/ui/button";

export type DataTableEmptyState = {
  icon: ReactNode;
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
};

export type DataTableRowAction<TData> = {
  key: string;
  label: string;
  href?: (row: TData) => string | null;
  onClick?: (row: TData) => void;
  className?: string;
};

export type DataTableRowActions<TData> = {
  header?: ReactNode;
  actions?: DataTableRowAction<TData>[];
  getEditHref?: (row: TData) => string | null;
  onDelete?: (row: TData) => void;
  cellClassName?: string;
};

type DataTableProps<TData> = {
  table: Table<TData>;
  isLoading?: boolean;
  loadingLabel?: string;
  emptyMessage?: string;
  emptyState?: DataTableEmptyState;
  rowActions?: DataTableRowActions<TData>;
  stickyHeader?: boolean;
  tableClassName?: string;
  headerClassName?: string;
  headerCellClassName?: string;
  bodyClassName?: string;
  rowClassName?: string | ((row: Row<TData>) => string);
  cellClassName?: string;
};

export function DataTable<TData>({
  table,
  isLoading = false,
  loadingLabel = "Loading…",
  emptyMessage = "No rows found.",
  emptyState,
  rowActions,
  stickyHeader = false,
  tableClassName = "w-full text-left text-sm",
  headerClassName,
  headerCellClassName = "px-6 py-3",
  bodyClassName = "divide-y divide-slate-100",
  rowClassName = "hover:bg-slate-50",
  cellClassName = "px-6 py-4",
}: DataTableProps<TData>) {
  const resolvedRowActions = rowActions
    ? (rowActions.actions ??
      [
        rowActions.getEditHref
          ? ({
              key: "edit",
              label: "Edit",
              href: rowActions.getEditHref,
            } as DataTableRowAction<TData>)
          : null,
        rowActions.onDelete
          ? ({
              key: "delete",
              label: "Delete",
              onClick: rowActions.onDelete,
            } as DataTableRowAction<TData>)
          : null,
      ].filter((value): value is DataTableRowAction<TData> => value !== null))
    : [];
  const hasRowActions = resolvedRowActions.length > 0;
  const colSpan =
    (table.getVisibleLeafColumns().length || 1) + (hasRowActions ? 1 : 0);

  return (
    <div className="overflow-x-hidden sm:overflow-x-auto">
      <table className={tableClassName}>
        <thead
          className={
            headerClassName ??
            `${stickyHeader ? "sticky top-0 z-10 " : ""}bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500`
          }
        >
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th key={header.id} className={headerCellClassName}>
                  {header.isPlaceholder ? null : header.column.getCanSort() ? (
                    <button
                      type="button"
                      onClick={header.column.getToggleSortingHandler()}
                      className="inline-flex items-center gap-1 text-left"
                    >
                      <span>
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                      </span>
                      {header.column.getIsSorted() === "asc" ? (
                        "↑"
                      ) : header.column.getIsSorted() === "desc" ? (
                        "↓"
                      ) : (
                        <span className="text-slate-300">↕</span>
                      )}
                    </button>
                  ) : (
                    flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )
                  )}
                </th>
              ))}
              {hasRowActions ? (
                <th className={headerCellClassName}>
                  {rowActions?.header ?? ""}
                </th>
              ) : null}
            </tr>
          ))}
        </thead>
        <tbody className={bodyClassName}>
          {isLoading ? (
            <TableLoadingRow colSpan={colSpan} label={loadingLabel} />
          ) : table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={
                  typeof rowClassName === "function"
                    ? rowClassName(row)
                    : rowClassName
                }
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={cellClassName}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
                {hasRowActions ? (
                  <td className={rowActions?.cellClassName ?? cellClassName}>
                    <div className="flex justify-end gap-2">
                      {resolvedRowActions.map((action) => {
                        const href = action.href?.(row.original) ?? null;
                        if (href) {
                          return (
                            <Link
                              key={action.key}
                              href={href}
                              className={
                                action.className ??
                                buttonVariants({ variant: "ghost", size: "sm" })
                              }
                            >
                              {action.label}
                            </Link>
                          );
                        }
                        if (action.onClick) {
                          return (
                            <Button
                              key={action.key}
                              variant="ghost"
                              size="sm"
                              className={action.className}
                              onClick={() => action.onClick?.(row.original)}
                            >
                              {action.label}
                            </Button>
                          );
                        }
                        return null;
                      })}
                    </div>
                  </td>
                ) : null}
              </tr>
            ))
          ) : emptyState ? (
            <TableEmptyStateRow
              colSpan={colSpan}
              icon={emptyState.icon}
              title={emptyState.title}
              description={emptyState.description}
              actionHref={emptyState.actionHref}
              actionLabel={emptyState.actionLabel}
            />
          ) : (
            <tr>
              <td
                colSpan={colSpan}
                className="px-6 py-8 text-sm text-slate-500"
              >
                {emptyMessage}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
