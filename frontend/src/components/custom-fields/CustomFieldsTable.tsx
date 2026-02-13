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

import {
  DataTable,
  type DataTableEmptyState,
} from "@/components/tables/DataTable";
import { dateCell } from "@/components/tables/cell-formatters";
import type { TaskCustomFieldDefinitionRead } from "@/api/generated/model";
import { formatCustomFieldDefaultValue } from "./custom-field-form-utils";

type CustomFieldsTableProps = {
  fields: TaskCustomFieldDefinitionRead[];
  isLoading?: boolean;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  stickyHeader?: boolean;
  editHref?: (field: TaskCustomFieldDefinitionRead) => string;
  onDelete?: (field: TaskCustomFieldDefinitionRead) => void;
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
    <path d="M8 6h13" />
    <path d="M8 12h13" />
    <path d="M8 18h13" />
    <path d="M3 6h.01" />
    <path d="M3 12h.01" />
    <path d="M3 18h.01" />
  </svg>
);

export function CustomFieldsTable({
  fields,
  isLoading = false,
  sorting,
  onSortingChange,
  stickyHeader = false,
  editHref,
  onDelete,
  emptyState,
}: CustomFieldsTableProps) {
  const [internalSorting, setInternalSorting] = useState<SortingState>([
    { id: "field_key", desc: false },
  ]);
  const resolvedSorting = sorting ?? internalSorting;
  const handleSortingChange: OnChangeFn<SortingState> =
    onSortingChange ??
    ((updater: Updater<SortingState>) => {
      setInternalSorting(updater);
    });

  const columns = useMemo<ColumnDef<TaskCustomFieldDefinitionRead>[]>(
    () => [
      {
        accessorKey: "field_key",
        header: "Field",
        cell: ({ row }) => (
          <div>
            <p className="text-sm font-semibold text-slate-900">
              {row.original.label || row.original.field_key}
            </p>
            <p className="mt-1 font-mono text-xs text-slate-500">
              key: {row.original.field_key}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {row.original.description || "No description"}
            </p>
          </div>
        ),
      },
      {
        accessorKey: "required",
        header: "Required",
        cell: ({ row }) => (
          <span className="text-sm text-slate-700">
            {row.original.required === true ? "Required" : "Optional"}
          </span>
        ),
      },
      {
        accessorKey: "field_type",
        header: "Type",
        cell: ({ row }) => (
          <span className="text-sm text-slate-700">
            {row.original.field_type}
          </span>
        ),
      },
      {
        accessorKey: "ui_visibility",
        header: "UI visible",
        cell: ({ row }) => (
          <span className="text-sm text-slate-700">
            {row.original.ui_visibility}
          </span>
        ),
      },
      {
        accessorKey: "default_value",
        header: "Default value",
        enableSorting: false,
        cell: ({ row }) => (
          <p className="font-mono text-xs break-all text-slate-700">
            {formatCustomFieldDefaultValue(row.original.default_value) || "—"}
          </p>
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
    data: fields,
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
        editHref || onDelete
          ? {
              actions: [
                ...(editHref
                  ? [
                      {
                        key: "edit",
                        label: "Edit",
                        href: editHref,
                      },
                    ]
                  : []),
                ...(onDelete
                  ? [
                      {
                        key: "delete",
                        label: "Delete",
                        onClick: onDelete,
                      },
                    ]
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
