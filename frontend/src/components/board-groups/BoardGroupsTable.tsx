import { useMemo, useState } from "react";

import {
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
  type Updater,
  type VisibilityState,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";

import { type BoardGroupRead } from "@/api/generated/model";
import {
  DataTable,
  type DataTableEmptyState,
} from "@/components/tables/DataTable";
import { dateCell, linkifyCell } from "@/components/tables/cell-formatters";

type BoardGroupsTableProps = {
  groups: BoardGroupRead[];
  isLoading?: boolean;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  stickyHeader?: boolean;
  showActions?: boolean;
  hiddenColumns?: string[];
  columnOrder?: string[];
  disableSorting?: boolean;
  onDelete?: (group: BoardGroupRead) => void;
  emptyMessage?: string;
  emptyState?: Omit<DataTableEmptyState, "icon"> & {
    icon?: DataTableEmptyState["icon"];
  };
};

const DEFAULT_EMPTY_ICON = (
  <svg
    className="h-16 w-16 text-[var(--text-quiet)]"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M3 7h8" />
    <path d="M3 17h8" />
    <path d="M13 7h8" />
    <path d="M13 17h8" />
    <path d="M3 12h18" />
  </svg>
);

export function BoardGroupsTable({
  groups,
  isLoading = false,
  sorting,
  onSortingChange,
  stickyHeader = false,
  showActions = true,
  hiddenColumns,
  columnOrder,
  disableSorting = false,
  onDelete,
  emptyMessage = "No groups found.",
  emptyState,
}: BoardGroupsTableProps) {
  const [internalSorting, setInternalSorting] = useState<SortingState>([
    { id: "name", desc: false },
  ]);
  const resolvedSorting = sorting ?? internalSorting;
  const handleSortingChange: OnChangeFn<SortingState> =
    onSortingChange ??
    ((updater: Updater<SortingState>) => {
      setInternalSorting(updater);
    });
  const columnVisibility = useMemo<VisibilityState>(
    () =>
      Object.fromEntries(
        (hiddenColumns ?? []).map((columnId) => [columnId, false]),
      ),
    [hiddenColumns],
  );
  const columns = useMemo<ColumnDef<BoardGroupRead>[]>(() => {
    const baseColumns: ColumnDef<BoardGroupRead>[] = [
      {
        accessorKey: "name",
        header: "Group",
        cell: ({ row }) =>
          linkifyCell({
            href: `/board-groups/${row.original.id}`,
            label: row.original.name,
            subtitle: row.original.description ?? "No description",
            subtitleClassName: row.original.description
              ? "mt-1 line-clamp-2 text-xs text-[var(--text-muted)]"
              : "mt-1 text-xs text-[var(--text-quiet)]",
          }),
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        cell: ({ row }) => dateCell(row.original.updated_at),
      },
    ];

    return baseColumns;
  }, []);

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: groups,
    columns,
    enableSorting: !disableSorting,
    state: {
      ...(!disableSorting ? { sorting: resolvedSorting } : {}),
      ...(columnOrder ? { columnOrder } : {}),
      columnVisibility,
    },
    ...(disableSorting ? {} : { onSortingChange: handleSortingChange }),
    getCoreRowModel: getCoreRowModel(),
    ...(disableSorting ? {} : { getSortedRowModel: getSortedRowModel() }),
  });

  return (
    <DataTable
      table={table}
      isLoading={isLoading}
      stickyHeader={stickyHeader}
      emptyMessage={emptyMessage}
      rowClassName="transition hover:bg-[var(--surface-muted)]"
      cellClassName="px-3 py-3 md:px-6 md:py-4 align-top"
      rowActions={
        showActions
          ? {
              getEditHref: (group) => `/board-groups/${group.id}/edit`,
              onDelete,
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
