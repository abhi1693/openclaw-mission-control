import { useMemo } from "react";

import {
  type ColumnDef,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";

import { type BoardRead } from "@/api/generated/model";
import { linkifyCell } from "@/components/tables/cell-formatters";
import { DataTable } from "@/components/tables/DataTable";

type BoardAccessState = Record<string, { read: boolean; write: boolean }>;

type BoardAccessTableProps = {
  boards: BoardRead[];
  access: BoardAccessState;
  onToggleRead: (boardId: string) => void;
  onToggleWrite: (boardId: string) => void;
  disabled?: boolean;
};

export function BoardAccessTable({
  boards,
  access,
  onToggleRead,
  onToggleWrite,
  disabled = false,
}: BoardAccessTableProps) {
  const columns = useMemo<ColumnDef<BoardRead>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Board",
        cell: ({ row }) =>
          linkifyCell({
            href: `/boards/${row.original.id}`,
            label: row.original.name,
            subtitle: row.original.slug,
            subtitleClassName: "mt-1 text-xs text-slate-500",
          }),
      },
      {
        id: "read",
        header: "Read",
        cell: ({ row }) => {
          const entry = access[row.original.id] ?? {
            read: false,
            write: false,
          };
          return (
            <div className="flex justify-center">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={entry.read}
                onChange={() => onToggleRead(row.original.id)}
                disabled={disabled}
              />
            </div>
          );
        },
      },
      {
        id: "write",
        header: "Write",
        cell: ({ row }) => {
          const entry = access[row.original.id] ?? {
            read: false,
            write: false,
          };
          return (
            <div className="flex justify-center">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={entry.write}
                onChange={() => onToggleWrite(row.original.id)}
                disabled={disabled}
              />
            </div>
          );
        },
      },
    ],
    [access, disabled, onToggleRead, onToggleWrite],
  );

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: boards,
    columns,
    enableSorting: false,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataTable
      table={table}
      rowClassName="border-t border-slate-200 hover:bg-slate-50"
      headerClassName="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500"
      headerCellClassName="px-4 py-2 font-medium"
      cellClassName="px-4 py-3"
    />
  );
}
