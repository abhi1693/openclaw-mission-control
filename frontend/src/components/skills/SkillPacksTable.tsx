import { useMemo } from "react";
import Link from "next/link";

import {
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";

import type { SkillPackRead } from "@/api/generated/model";
import {
  DataTable,
  type DataTableEmptyState,
} from "@/components/tables/DataTable";
import { dateCell } from "@/components/tables/cell-formatters";
import { Button } from "@/components/ui/button";
import {
  SKILLS_TABLE_EMPTY_ICON,
  useTableSortingState,
} from "@/components/skills/table-helpers";
import { truncateText as truncate } from "@/lib/formatters";

type SkillPacksTableProps = {
  packs: SkillPackRead[];
  isLoading?: boolean;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  stickyHeader?: boolean;
  canSync?: boolean;
  syncingPackIds?: Set<string>;
  onSync?: (pack: SkillPackRead) => void;
  onDelete?: (pack: SkillPackRead) => void;
  getEditHref?: (pack: SkillPackRead) => string;
  emptyState?: Omit<DataTableEmptyState, "icon"> & {
    icon?: DataTableEmptyState["icon"];
  };
};

export function SkillPacksTable({
  packs,
  isLoading = false,
  sorting,
  onSortingChange,
  stickyHeader = false,
  canSync = false,
  syncingPackIds,
  onSync,
  onDelete,
  getEditHref,
  emptyState,
}: SkillPacksTableProps) {
  const { resolvedSorting, handleSortingChange } = useTableSortingState(
    sorting,
    onSortingChange,
    [{ id: "name", desc: false }],
  );

  const columns = useMemo<ColumnDef<SkillPackRead>[]>(() => {
    const baseColumns: ColumnDef<SkillPackRead>[] = [
      {
        accessorKey: "name",
        header: "Pack",
        cell: ({ row }) => (
          <div>
            <p className="text-sm font-medium text-slate-900">
              {row.original.name}
            </p>
            <p className="mt-1 line-clamp-2 text-xs text-slate-500">
              {row.original.description || "No description provided."}
            </p>
          </div>
        ),
      },
      {
        accessorKey: "source_url",
        header: "Pack URL",
        cell: ({ row }) => (
          <Link
            href={row.original.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-medium text-slate-700 hover:text-blue-600"
          >
            {truncate(row.original.source_url, 48)}
          </Link>
        ),
      },
      {
        accessorKey: "branch",
        header: "Branch",
        cell: ({ row }) => (
          <p className="text-sm text-slate-900">
            {row.original.branch || "main"}
          </p>
        ),
      },
      {
        accessorKey: "skill_count",
        header: "Skills",
        cell: ({ row }) => (
          <Link
            href={`/skills/marketplace?packId=${encodeURIComponent(row.original.id)}`}
            className="text-sm font-medium text-blue-700 hover:text-blue-600 hover:underline"
          >
            {row.original.skill_count ?? 0}
          </Link>
        ),
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        cell: ({ row }) => dateCell(row.original.updated_at),
      },
      {
        id: "sync",
        header: "",
        enableSorting: false,
        cell: ({ row }) => {
          if (!onSync) return null;
          const isThisPackSyncing = Boolean(
            syncingPackIds?.has(row.original.id),
          );
          return (
            <div className="flex justify-end">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onSync(row.original)}
                disabled={isThisPackSyncing || !canSync}
              >
                {isThisPackSyncing ? "Syncing..." : "Sync"}
              </Button>
            </div>
          );
        },
      },
    ];
    return baseColumns;
  }, [canSync, onSync, syncingPackIds]);

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: packs,
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
        getEditHref || onDelete
          ? {
              ...(getEditHref ? { getEditHref } : {}),
              ...(onDelete ? { onDelete } : {}),
            }
          : undefined
      }
      emptyState={
        emptyState
          ? {
              icon: emptyState.icon ?? SKILLS_TABLE_EMPTY_ICON,
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
