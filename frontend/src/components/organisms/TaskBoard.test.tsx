import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { TaskBoard } from "./TaskBoard";

type Task = ComponentProps<typeof TaskBoard>["tasks"][number];

const buildTask = (overrides: Partial<Task> = {}): Task => ({
  id: `task-${Math.random().toString(16).slice(2)}`,
  title: "Task",
  status: "inbox",
  priority: "medium",
  approvals_pending_count: 0,
  blocked_by_task_ids: [],
  is_blocked: false,
  ...overrides,
});

describe("TaskBoard", () => {
  it("uses a mobile-first stacked layout with responsive kanban columns on larger screens", () => {
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

    expect(board.className).toContain("overflow-x-auto");
    expect(board.className).toContain("grid-cols-1");
    expect(board.className).toContain("lg:grid-flow-col");
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
    expect(header?.className).toContain("lg:sticky");
    expect(header?.className).toContain("lg:top-0");
  });

  it("renders the 6 columns and shows per-column counts", () => {
    const tasks: Task[] = [
      buildTask({ id: "t1", title: "Inbox A", status: "inbox" }),
      buildTask({ id: "t2", title: "Todo A", status: "todo" }),
      buildTask({ id: "t3", title: "Doing A", status: "in_progress" }),
      buildTask({ id: "t4", title: "Review A", status: "in_review" }),
      buildTask({ id: "t5", title: "Sprint Done A", status: "sprint_done" }),
      buildTask({ id: "t6", title: "Done A", status: "done" }),
      buildTask({ id: "t7", title: "Inbox B", status: "inbox" }),
    ];

    render(<TaskBoard tasks={tasks} />);

    const inboxHeading = screen.getByRole("heading", { name: "Inbox" });
    const todoHeading = screen.getByRole("heading", { name: "Todo" });
    const inProgressHeading = screen.getByRole("heading", {
      name: "In Progress",
    });
    const inReviewHeading = screen.getByRole("heading", { name: "In Review" });
    const sprintDoneHeading = screen.getByRole("heading", {
      name: "Sprint Done",
    });
    const doneHeading = screen.getByRole("heading", { name: "Done" });

    expect(inboxHeading).toBeInTheDocument();
    expect(todoHeading).toBeInTheDocument();
    expect(inProgressHeading).toBeInTheDocument();
    expect(inReviewHeading).toBeInTheDocument();
    expect(sprintDoneHeading).toBeInTheDocument();
    expect(doneHeading).toBeInTheDocument();

    const inboxColumn = inboxHeading.closest(".kanban-column") as HTMLElement | null;
    const todoColumn = todoHeading.closest(".kanban-column") as HTMLElement | null;
    const inProgressColumn = inProgressHeading.closest(
      ".kanban-column",
    ) as HTMLElement | null;
    const inReviewColumn = inReviewHeading.closest(".kanban-column") as HTMLElement | null;
    const sprintDoneColumn = sprintDoneHeading.closest(
      ".kanban-column",
    ) as HTMLElement | null;
    const doneColumn = doneHeading.closest(".kanban-column") as HTMLElement | null;
    expect(inboxColumn).toBeTruthy();
    expect(todoColumn).toBeTruthy();
    expect(inProgressColumn).toBeTruthy();
    expect(inReviewColumn).toBeTruthy();
    expect(sprintDoneColumn).toBeTruthy();
    expect(doneColumn).toBeTruthy();
    if (!inboxColumn || !todoColumn || !inProgressColumn || !inReviewColumn || !sprintDoneColumn || !doneColumn) return;

    const getColumnCountBadge = (column: HTMLElement) =>
      column.querySelector(
        ".column-header span.h-6.w-6.rounded-full",
      ) as HTMLElement | null;

    const inboxCountBadge = getColumnCountBadge(inboxColumn);
    const todoCountBadge = getColumnCountBadge(todoColumn);
    const inProgressCountBadge = getColumnCountBadge(inProgressColumn);
    const inReviewCountBadge = getColumnCountBadge(inReviewColumn);
    const sprintDoneCountBadge = getColumnCountBadge(sprintDoneColumn);
    const doneCountBadge = getColumnCountBadge(doneColumn);

    expect(inboxCountBadge).toHaveTextContent("2");
    expect(todoCountBadge).toHaveTextContent("1");
    expect(inProgressCountBadge).toHaveTextContent("1");
    expect(inReviewCountBadge).toHaveTextContent("1");
    expect(sprintDoneCountBadge).toHaveTextContent("1");
    expect(doneCountBadge).toHaveTextContent("1");

    expect(screen.getByText("Inbox A")).toBeInTheDocument();
    expect(screen.getByText("Inbox B")).toBeInTheDocument();
  });

  it("filters the in_review column by bucket", () => {
    const tasks: Task[] = [
      buildTask({
        id: "blocked",
        title: "Blocked Review",
        status: "in_review",
        is_blocked: true,
        blocked_by_task_ids: ["dep-1"],
      }),
      buildTask({
        id: "approval",
        title: "Needs Approval",
        status: "in_review",
        approvals_pending_count: 2,
      }),
      buildTask({
        id: "lead",
        title: "Lead Review",
        status: "in_review",
      }),
    ];

    render(<TaskBoard tasks={tasks} />);

    const reviewHeading = screen.getByRole("heading", { name: "In Review" });
    const reviewColumn = reviewHeading.closest(".kanban-column") as HTMLElement | null;
    expect(reviewColumn).toBeTruthy();
    if (!reviewColumn) return;

    const header = reviewColumn.querySelector(
      ".column-header",
    ) as HTMLElement | null;
    expect(header).toBeTruthy();
    if (!header) return;

    const headerQueries = within(header);

    expect(headerQueries.getByRole("button", { name: /All · 3/i })).toBeInTheDocument();
    expect(
      headerQueries.getByRole("button", { name: /Approval needed · 1/i }),
    ).toBeInTheDocument();
    expect(
      headerQueries.getByRole("button", { name: /Lead review · 1/i }),
    ).toBeInTheDocument();
    expect(
      headerQueries.getByRole("button", { name: /Blocked · 1/i }),
    ).toBeInTheDocument();

    fireEvent.click(headerQueries.getByRole("button", { name: /Blocked · 1/i }));
    expect(screen.getByText("Blocked Review")).toBeInTheDocument();
    expect(screen.queryByText("Needs Approval")).not.toBeInTheDocument();
    expect(screen.queryByText("Lead Review")).not.toBeInTheDocument();

    fireEvent.click(
      headerQueries.getByRole("button", { name: /Approval needed · 1/i }),
    );
    expect(screen.getByText("Needs Approval")).toBeInTheDocument();
    expect(screen.queryByText("Blocked Review")).not.toBeInTheDocument();
    expect(screen.queryByText("Lead Review")).not.toBeInTheDocument();

    fireEvent.click(
      headerQueries.getByRole("button", { name: /Lead review · 1/i }),
    );
    expect(screen.getByText("Lead Review")).toBeInTheDocument();
    expect(screen.queryByText("Blocked Review")).not.toBeInTheDocument();
    expect(screen.queryByText("Needs Approval")).not.toBeInTheDocument();
  });

  it("invokes onTaskMove when a task is dropped onto a different column", () => {
    const onTaskMove = vi.fn();
    const tasks: Task[] = [
      buildTask({ id: "t1", title: "Inbox A", status: "inbox" }),
    ];

    render(<TaskBoard tasks={tasks} onTaskMove={onTaskMove} />);

    const dropTarget = screen
      .getByRole("heading", { name: "Done" })
      .closest(".kanban-column") as HTMLElement | null;
    expect(dropTarget).toBeTruthy();
    if (!dropTarget) return;

    fireEvent.drop(dropTarget, {
      dataTransfer: {
        getData: () => JSON.stringify({ taskId: "t1", status: "inbox" }),
      },
    });

    expect(onTaskMove).toHaveBeenCalledWith("t1", "done");
  });

  it("does not allow dragging when readOnly is true", () => {
    const tasks: Task[] = [buildTask({ id: "t1", title: "Inbox A" })];

    render(<TaskBoard tasks={tasks} readOnly />);

    expect(screen.getByRole("button", { name: /Inbox A/i })).toHaveAttribute(
      "draggable",
      "false",
    );
  });

  it("renders empty columns as valid drop targets", () => {
    render(<TaskBoard tasks={[]} />);

    const headings = ["Inbox", "Todo", "In Progress", "In Review", "Sprint Done", "Done"];
    for (const name of headings) {
      const heading = screen.getByRole("heading", { name });
      const column = heading.closest(".kanban-column");
      expect(column).toBeTruthy();
    }
  });
});
