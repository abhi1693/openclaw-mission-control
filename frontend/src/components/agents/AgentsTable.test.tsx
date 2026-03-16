import type React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentRead, BoardRead } from "@/api/generated/model";
import { AgentsTable } from "./AgentsTable";

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

const buildAgent = (overrides: Partial<AgentRead> = {}): AgentRead => ({
  id: "agent-1",
  name: "Ava",
  gateway_id: "gateway-1",
  board_id: "board-1",
  status: "online",
  openclaw_session_id: "session-1234",
  last_seen_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const buildBoard = (overrides: Partial<BoardRead> = {}): BoardRead => ({
  id: "board-1",
  name: "Ops Board",
  slug: "ops-board",
  description: "Operations board context.",
  organization_id: "org-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("AgentsTable", () => {
  it("renders linked board name and default row actions", () => {
    const onDelete = vi.fn();
    const agent = buildAgent();
    const board = buildBoard();

    render(
      <AgentsTable agents={[agent]} boards={[board]} onDelete={onDelete} />,
    );

    expect(
      screen.getByRole("link", { name: /Ava ID agent-1/i }),
    ).toHaveAttribute("href", "/agents/agent-1");
    expect(screen.getByRole("link", { name: "Ops Board" })).toHaveAttribute(
      "href",
      "/boards/board-1",
    );
    expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      "/agents/agent-1/edit",
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith(agent);
  });

  it("hides row actions when showActions is false", () => {
    render(
      <AgentsTable
        agents={[buildAgent()]}
        boards={[buildBoard()]}
        showActions={false}
      />,
    );

    expect(
      screen.queryByRole("link", { name: "Edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  it("supports hiddenColumns and columnOrder", () => {
    render(
      <AgentsTable
        agents={[buildAgent()]}
        boards={[buildBoard()]}
        showActions={false}
        hiddenColumns={["status", "openclaw_session_id"]}
        columnOrder={["updated_at", "name", "board_id", "last_seen_at"]}
      />,
    );

    expect(
      screen.queryByRole("columnheader", { name: "Status" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Session" }),
    ).not.toBeInTheDocument();

    const headers = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent?.replace(/[↑↓↕]/g, "").trim());
    expect(headers.slice(0, 4)).toEqual([
      "Updated",
      "Agent",
      "Board",
      "Last seen",
    ]);
  });

  it("supports disableSorting and preserves input order", () => {
    const zulu = buildAgent({ id: "agent-z", name: "Zulu" });
    const alpha = buildAgent({ id: "agent-a", name: "Alpha" });

    const { rerender } = render(
      <AgentsTable
        agents={[zulu, alpha]}
        boards={[buildBoard()]}
        showActions={false}
      />,
    );

    // Default behavior applies name sorting.
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Alpha");

    rerender(
      <AgentsTable
        agents={[zulu, alpha]}
        boards={[buildBoard()]}
        showActions={false}
        disableSorting
      />,
    );

    // disableSorting keeps incoming data order.
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Zulu");
  });
});
