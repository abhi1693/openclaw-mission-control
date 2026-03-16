import type React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { dateCell, linkifyCell, pillCell } from "./cell-formatters";

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

describe("cell formatters", () => {
  it("renders linkifyCell in block mode with subtitle", () => {
    render(
      linkifyCell({
        href: "/agents/agent-1",
        label: "Agent One",
        subtitle: "ID agent-1",
      }),
    );

    expect(screen.getByRole("link", { name: /agent one/i })).toHaveAttribute(
      "href",
      "/agents/agent-1",
    );
    expect(screen.getByText("ID agent-1")).toBeInTheDocument();
  });

  it("renders linkifyCell in inline mode", () => {
    render(
      linkifyCell({
        href: "/boards/board-1",
        label: "Board One",
        block: false,
      }),
    );

    expect(screen.getByRole("link", { name: "Board One" })).toHaveAttribute(
      "href",
      "/boards/board-1",
    );
  });

  it("renders pillCell and default fallback", () => {
    const { rerender } = render(pillCell("in_progress"));
    expect(screen.getByText("in progress")).toBeInTheDocument();

    rerender(pillCell(null));
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });

  it("renders dateCell relative and fallback states", () => {
    const now = new Date("2026-01-01T01:00:00Z").getTime();
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(now);
    const { rerender } = render(
      dateCell("2026-01-01T00:00:00Z", { relative: true }),
    );
    expect(screen.getByText("1h ago")).toBeInTheDocument();

    rerender(dateCell(null));
    expect(screen.getByText("—")).toBeInTheDocument();
    nowSpy.mockRestore();
  });
});
