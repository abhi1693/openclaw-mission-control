import type React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  type ColumnDef,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { describe, expect, it, vi } from "vitest";

import { DataTable } from "./DataTable";

vi.mock("next/link", () => {
  type LinkProps = React.PropsWithChildren<{
    href: string | { pathname?: string };
  }> &
    Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

  return {
    default: ({ href, children, ...props }: LinkProps) => (
      <a href={typeof href === "string" ? href : "#"} {...props}>
        {children}
      </a>
    ),
  };
});

type Row = {
  id: string;
  name: string;
};

type HarnessProps = {
  rows: Row[];
  isLoading?: boolean;
  emptyMessage?: string;
  emptyState?: React.ComponentProps<typeof DataTable<Row>>["emptyState"];
  rowActions?: React.ComponentProps<typeof DataTable<Row>>["rowActions"];
};

function DataTableHarness({
  rows,
  isLoading = false,
  emptyMessage,
  emptyState,
  rowActions,
}: HarnessProps) {
  const columns: ColumnDef<Row>[] = [{ accessorKey: "name", header: "Name" }];
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataTable
      table={table}
      isLoading={isLoading}
      emptyMessage={emptyMessage}
      emptyState={emptyState}
      rowActions={rowActions}
    />
  );
}

describe("DataTable", () => {
  it("renders default Edit/Delete row actions", () => {
    const onDelete = vi.fn();
    const row = { id: "row-1", name: "Alpha" };

    render(
      <DataTableHarness
        rows={[row]}
        rowActions={{
          getEditHref: (current) => `/items/${current.id}/edit`,
          onDelete,
        }}
      />,
    );

    const editLink = screen.getByRole("link", { name: "Edit" });
    expect(editLink).toHaveAttribute("href", "/items/row-1/edit");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith(row);
  });

  it("uses custom row actions when provided", () => {
    const onArchive = vi.fn();
    const row = { id: "row-1", name: "Alpha" };

    render(
      <DataTableHarness
        rows={[row]}
        rowActions={{
          getEditHref: (current) => `/items/${current.id}/edit`,
          onDelete: vi.fn(),
          actions: [
            {
              key: "view",
              label: "View",
              href: (current) => `/items/${current.id}`,
            },
            {
              key: "archive",
              label: "Archive",
              onClick: onArchive,
            },
          ],
        }}
      />,
    );

    expect(screen.getByRole("link", { name: "View" })).toHaveAttribute(
      "href",
      "/items/row-1",
    );
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(onArchive).toHaveBeenCalledWith(row);
  });

  it("renders loading and empty states", () => {
    const { rerender } = render(
      <DataTableHarness rows={[]} isLoading={true} />,
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    rerender(
      <DataTableHarness
        rows={[]}
        isLoading={false}
        emptyMessage="No rows yet"
      />,
    );
    expect(screen.getByText("No rows yet")).toBeInTheDocument();
  });

  it("renders custom empty state", () => {
    render(
      <DataTableHarness
        rows={[]}
        emptyState={{
          icon: <span data-testid="empty-icon">icon</span>,
          title: "No records",
          description: "Create one to continue.",
          actionHref: "/new",
          actionLabel: "Create",
        }}
      />,
    );

    expect(screen.getByTestId("empty-icon")).toBeInTheDocument();
    expect(screen.getByText("No records")).toBeInTheDocument();
    expect(screen.getByText("Create one to continue.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "href",
      "/new",
    );
  });
});
