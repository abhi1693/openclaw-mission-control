import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskBoard } from "./TaskBoard";

describe("TaskBoard", () => {
  it("uses a mobile-first stacked layout (no horizontal scroll) with responsive kanban columns on larger screens", () => {
    render(
      <TaskBoard
        tasks={[
          {
            id: "t1",
            title: "Inbox item",
            status: "inbox",
            priority: "medium",
          },
        ]}
      />,
    );

    const board = screen.getByTestId("task-board");

    expect(board.className).toContain("overflow-x-hidden");
    expect(board.className).toContain("sm:overflow-x-auto");
    expect(board.className).toContain("grid-cols-1");
    expect(board.className).toContain("sm:grid-flow-col");
  });

  it("only sticks column headers on larger screens (avoids weird stacked sticky headers on mobile)", () => {
    render(
      <TaskBoard
        tasks={[
          {
            id: "t1",
            title: "Inbox item",
            status: "inbox",
            priority: "medium",
          },
        ]}
      />,
    );

    const header = screen
      .getByRole("heading", { name: "Inbox" })
      .closest(".column-header");
    expect(header?.className).toContain("sm:sticky");
    expect(header?.className).toContain("sm:top-0");
    // Ensure we didn't accidentally keep unscoped sticky behavior.
    expect(header?.className).not.toContain("sticky top-0");
  });
});
