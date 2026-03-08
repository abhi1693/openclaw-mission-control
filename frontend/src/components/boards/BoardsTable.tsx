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

import { type BoardGroupRead, type BoardRead } from "@/api/generated/model";
import {
  DataTable,
  type DataTableEmptyState,
} from "@/components/tables/DataTable";
import { dateCell, linkifyCell } from "@/components/tables/cell-formatters";

type BoardsTableProps = {
  boards: BoardRead[];
  boardGroups?: BoardGroupRead[];
  isLoading?: boolean;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  stickyHeader?: boolean;
  showActions?: boolean;
  hiddenColumns?: string[];
  columnOrder?: string[];
  disableSorting?: boolean;
  onDelete?: (board: BoardRead) => void;
  emptyMessage?: string;
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
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
  </svg>
);

const compactId = (value: string) =>
  value.length > 8 ? `${value.slice(0, 8)}…` : value;

export function BoardsTable({
  boards,
  boardGroups = [],
  isLoading = false,
  sorting,
  onSortingChange,
  stickyHeader = false,
  showActions = true,
  hiddenColumns,
  columnOrder,
  disableSorting = false,
  onDelete,
  emptyMessage = "No boards found.",
  emptyState,
}: BoardsTableProps) {
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
  const groupById = useMemo(() => {
    const map = new Map<string, BoardGroupRead>();
    for (const group of boardGroups) {
      map.set(group.id, group);
    }
    return map;
  }, [boardGroups]);

  const columns = useMemo<ColumnDef<BoardRead>[]>(() => {
    const baseColumns: ColumnDef<BoardRead>[] = [
      {
        accessorKey: "name",
        header: "Board",
        cell: ({ row }) =>
          linkifyCell({
            href: `/boards/${row.original.id}`,
            label: row.original.name,
          }),
      },
      {
        id: "group",
        accessorFn: (row) => {
          const groupId = row.board_group_id;
          if (!groupId) return "";
          return groupById.get(groupId)?.name ?? groupId;
        },
        header: "Group",
        cell: ({ row }) => {
          const groupId = row.original.board_group_id;
          if (!groupId) {
            return <span className="text-sm text-slate-400">—</span>;
          }
          const group = groupById.get(groupId);
          const label = group?.name ?? compactId(groupId);
          const title = group?.name ?? groupId;
          return linkifyCell({
            href: `/board-groups/${groupId}`,
            label,
            title,
            block: false,
          });
        },
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        cell: ({ row }) => dateCell(row.original.updated_at),
      },
    ];

    return baseColumns;
  }, [groupById]);

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: boards,
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
      rowClassName="transition hover:bg-slate-50"
      cellClassName="px-3 py-3 md:px-6 md:py-4 align-top"
      rowActions={
        showActions
          ? {
              getEditHref: (board) => `/boards/${board.id}/edit`,
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
