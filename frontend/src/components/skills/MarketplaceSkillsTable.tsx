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

import type { MarketplaceSkillCardRead } from "@/api/generated/model";
import {
  DataTable,
  type DataTableEmptyState,
} from "@/components/tables/DataTable";
import { dateCell } from "@/components/tables/cell-formatters";
import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  SKILLS_TABLE_EMPTY_ICON,
  useTableSortingState,
} from "@/components/skills/table-helpers";
import { truncateText as truncate } from "@/lib/formatters";
import {
  packLabelFromUrl,
  packUrlFromSkillSourceUrl,
  packsHrefFromPackUrl,
} from "@/lib/skills-source";

function riskBadgeVariant(risk: string | null | undefined) {
  const normalizedRisk = (risk || "unknown").trim().toLowerCase();

  switch (normalizedRisk) {
    case "safe":
    case "low":
      return "success";
    case "minimal":
    case "medium":
    case "moderate":
      return "outline";
    case "high":
    case "critical":
      return "danger";
    case "elevated":
      return "warning";
    case "unknown":
      return "outline";
    default:
      return "accent";
  }
}

function riskPillClassName(risk: string | null | undefined) {
  const normalizedRisk = (risk || "unknown").trim().toLowerCase();

  switch (normalizedRisk) {
    case "safe":
    case "low":
      return "bg-[color:rgba(16,185,129,0.16)] text-emerald-800 border border-emerald-200/70";
    case "medium":
    case "moderate":
      return "bg-[color:rgba(245,158,11,0.16)] text-amber-800 border border-amber-200/70";
    case "elevated":
      return "bg-[color:rgba(245,158,11,0.16)] text-amber-800 border border-amber-200/70";
    case "high":
    case "critical":
      return "bg-[color:rgba(244,63,94,0.16)] text-rose-800 border border-rose-200/70";
    case "unknown":
      return "bg-[color:rgba(148,163,184,0.16)] text-slate-700 border border-slate-200/80";
    default:
      return "bg-[color:rgba(99,102,241,0.16)] text-indigo-800 border border-indigo-200/70";
  }
}

function riskBadgeLabel(risk: string | null | undefined) {
  return (risk || "unknown").trim() || "unknown";
}

type MarketplaceSkillsTableProps = {
  skills: MarketplaceSkillCardRead[];
  installedGatewayNamesBySkillId?: Record<
    string,
    { id: string; name: string }[]
  >;
  isLoading?: boolean;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  stickyHeader?: boolean;
  disableSorting?: boolean;
  isMutating?: boolean;
  onSkillClick?: (skill: MarketplaceSkillCardRead) => void;
  onDelete?: (skill: MarketplaceSkillCardRead) => void;
  getEditHref?: (skill: MarketplaceSkillCardRead) => string;
  emptyState?: Omit<DataTableEmptyState, "icon"> & {
    icon?: DataTableEmptyState["icon"];
  };
};

export function MarketplaceSkillsTable({
  skills,
  installedGatewayNamesBySkillId,
  isLoading = false,
  sorting,
  onSortingChange,
  stickyHeader = false,
  disableSorting = false,
  isMutating = false,
  onSkillClick,
  onDelete,
  getEditHref,
  emptyState,
}: MarketplaceSkillsTableProps) {
  const { resolvedSorting, handleSortingChange } = useTableSortingState(
    sorting,
    onSortingChange,
    [{ id: "name", desc: false }],
  );

  const columns = useMemo<ColumnDef<MarketplaceSkillCardRead>[]>(() => {
    const baseColumns: ColumnDef<MarketplaceSkillCardRead>[] = [
      {
        accessorKey: "name",
        header: "Skill",
        cell: ({ row }) => (
          <div>
            {onSkillClick ? (
              <button
                type="button"
                onClick={() => onSkillClick(row.original)}
                className="text-sm font-medium text-blue-700 hover:text-blue-600 hover:underline"
              >
                {row.original.name}
              </button>
            ) : (
              <p className="text-sm font-medium text-slate-900">
                {row.original.name}
              </p>
            )}
            <p
              className="mt-1 line-clamp-2 text-xs text-slate-500"
              title={row.original.description || "No description provided."}
            >
              {row.original.description || "No description provided."}
            </p>
          </div>
        ),
      },
      {
        accessorKey: "source_url",
        header: "Pack",
        cell: ({ row }) => {
          const packUrl = packUrlFromSkillSourceUrl(row.original.source_url);
          return (
            <Link
              href={packsHrefFromPackUrl(packUrl)}
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-700 hover:text-blue-600"
            >
              {truncate(packLabelFromUrl(packUrl), 40)}
            </Link>
          );
        },
      },
      {
        accessorKey: "category",
        header: "Category",
        cell: ({ row }) => (
          <span className="text-sm text-slate-700">
            {row.original.category || "uncategorized"}
          </span>
        ),
      },
      {
        accessorKey: "risk",
        header: "Risk",
        cell: ({ row }) => (
          <Badge
            variant={riskBadgeVariant(row.original.risk)}
            className={`px-2 py-0.5 ${riskPillClassName(row.original.risk)} font-semibold`}
          >
            {riskBadgeLabel(row.original.risk)}
          </Badge>
        ),
      },
      {
        accessorKey: "source",
        header: "Source",
        cell: ({ row }) => {
          const sourceHref = row.original.source || row.original.source_url;

          if (!sourceHref) {
            return <span className="text-sm text-slate-400">No source</span>;
          }

          return (
            <Link
              href={sourceHref}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium text-slate-700 hover:text-blue-600 hover:underline"
              title={sourceHref}
            >
              {truncate(sourceHref, 36)}
            </Link>
          );
        },
      },
      {
        id: "installed_on",
        header: "Installed On",
        enableSorting: false,
        cell: ({ row }) => {
          const installedOn =
            installedGatewayNamesBySkillId?.[row.original.id] ?? [];
          if (installedOn.length === 0) {
            return <span className="text-sm text-slate-500">-</span>;
          }
          return (
            <div className="flex flex-wrap gap-1">
              {installedOn.map((gateway, index) => {
                const isLast = index === installedOn.length - 1;
                return (
                  <span
                    key={`${gateway.id}-${index}`}
                    className="inline-flex items-center gap-1 text-sm text-slate-700"
                    title={gateway.name}
                  >
                    <Link
                      href={`/gateways/${gateway.id}`}
                      className="text-blue-700 hover:text-blue-600 hover:underline"
                    >
                      {gateway.name}
                    </Link>
                    {!isLast ? "," : ""}
                  </span>
                );
              })}
            </div>
          );
        },
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        cell: ({ row }) => dateCell(row.original.updated_at),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end gap-2">
            {getEditHref ? (
              <Link
                href={getEditHref(row.original)}
                className={buttonVariants({ variant: "ghost", size: "sm" })}
              >
                Edit
              </Link>
            ) : null}
            {onDelete ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onDelete(row.original)}
                disabled={isMutating}
              >
                Delete
              </Button>
            ) : null}
          </div>
        ),
      },
    ];

    return baseColumns;
  }, [
    getEditHref,
    installedGatewayNamesBySkillId,
    isMutating,
    onDelete,
    onSkillClick,
  ]);

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: skills,
    columns,
    enableSorting: !disableSorting,
    state: {
      ...(!disableSorting ? { sorting: resolvedSorting } : {}),
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
      rowClassName="transition hover:bg-slate-50"
      cellClassName="px-6 py-4 align-top"
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
