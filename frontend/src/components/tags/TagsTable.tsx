import { useMemo, useState } from "react";

import {
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
  type Updater,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";

import { type TagRead } from "@/api/generated/model";
import {
  DataTable,
  type DataTableEmptyState,
} from "@/components/tables/DataTable";
import { dateCell } from "@/components/tables/cell-formatters";

type TagsTableProps = {
  tags: TagRead[];
  isLoading?: boolean;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  stickyHeader?: boolean;
  onEdit?: (tag: TagRead) => void;
  onDelete?: (tag: TagRead) => void;
  emptyState?: Omit<DataTableEmptyState, "icon"> & {
    icon?: DataTableEmptyState["icon"];
  };
};

const DEFAULT_EMPTY_ICON = (
  <svg
    className="h-16 w-16 text-slate-300"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h10" />
  </svg>
);

const normalizeColor = (value?: string | null) => {
  const cleaned = (value ?? "").trim().replace(/^#/, "").toLowerCase();
  if (!/^[0-9a-f]{6}$/.test(cleaned)) return "9e9e9e";
  return cleaned;
};

export function TagsTable({
  tags,
  isLoading = false,
  sorting,
  onSortingChange,
  stickyHeader = false,
  onEdit,
  onDelete,
  emptyState,
}: TagsTableProps) {
  const [internalSorting, setInternalSorting] = useState<SortingState>([
    { id: "name", desc: false },
  ]);
  const resolvedSorting = sorting ?? internalSorting;
  const handleSortingChange: OnChangeFn<SortingState> =
    onSortingChange ??
    ((updater: Updater<SortingState>) => {
      setInternalSorting(updater);
    });

  const columns = useMemo<ColumnDef<TagRead>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Tag",
        cell: ({ row }) => {
          const color = normalizeColor(row.original.color);
          return (
            <div className="space-y-1">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-800">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: `#${color}` }}
                />
                {row.original.name}
              </div>
              <p className="text-xs text-slate-500">
                {row.original.slug}
                {row.original.description
                  ? ` · ${row.original.description}`
                  : ""}
              </p>
            </div>
          );
        },
      },
      {
        accessorKey: "color",
        header: "Color",
        cell: ({ row }) => {
          const color = normalizeColor(row.original.color);
          return (
            <div className="inline-flex items-center gap-2 text-xs text-slate-700">
              <span
                className="h-4 w-4 rounded border border-slate-300"
                style={{ backgroundColor: `#${color}` }}
              />
              #{color.toUpperCase()}
            </div>
          );
        },
      },
      {
        accessorKey: "task_count",
        header: "Tasks",
        cell: ({ row }) => (
          <span className="text-sm font-medium text-slate-700">
            {row.original.task_count ?? 0}
          </span>
        ),
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        cell: ({ row }) => dateCell(row.original.updated_at),
      },
    ],
    [],
  );

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: tags,
    columns,
    state: {
      sorting: resolvedSorting,
    },
    onSortingChange: handleSortingChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <DataTable
      table={table}
      isLoading={isLoading}
      stickyHeader={stickyHeader}
      rowClassName="transition hover:bg-slate-50"
      cellClassName="px-6 py-4 align-top"
      rowActions={
        onEdit || onDelete
          ? {
              actions: [
                ...(onEdit
                  ? [{ key: "edit", label: "Edit", onClick: onEdit }]
                  : []),
                ...(onDelete
                  ? [{ key: "delete", label: "Delete", onClick: onDelete }]
                  : []),
              ],
            }
          : undefined
      }
      emptyState={
        emptyState
          ? {
              icon: emptyState.icon ?? DEFAULT_EMPTY_ICON,
              title: emptyState.title,
              description: emptyState.description,
              actionHref: emptyState.actionHref,
              actionLabel: emptyState.actionLabel,
            }
          : undefined
      }
    />
  );
}
