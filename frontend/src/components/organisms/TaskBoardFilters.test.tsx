import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  TaskBoardFilters,
  applyTaskBoardFilters,
  type TaskBoardFilterValues,
} from "./TaskBoardFilters";

type FilterableTask = {
  custom_field_values?: Record<string, unknown> | null;
  assignee?: string | null;
  priority?: string | null;
  tags?: Array<{ id: string; name: string; color: string }>;
};

const buildTask = (overrides: Partial<FilterableTask> = {}): FilterableTask => ({
  assignee: null,
  priority: "medium",
  tags: [],
  custom_field_values: null,
  ...overrides,
});

// ---------------------------------------------------------------------------
// applyTaskBoardFilters (pure logic)
// ---------------------------------------------------------------------------

describe("applyTaskBoardFilters", () => {
  const tasks: FilterableTask[] = [
    buildTask({
      assignee: "Alice",
      priority: "high",
      tags: [{ id: "t1", name: "frontend", color: "#000" }],
      custom_field_values: { sprint: "Sprint 1", type: "feature" },
    }),
    buildTask({
      assignee: "Bob",
      priority: "low",
      tags: [
        { id: "t2", name: "backend", color: "#111" },
        { id: "t1", name: "frontend", color: "#000" },
      ],
      custom_field_values: { sprint: "Sprint 2", type: "bug" },
    }),
    buildTask({
      assignee: "Alice",
      priority: "medium",
      tags: [{ id: "t2", name: "backend", color: "#111" }],
      custom_field_values: { sprint: "Sprint 1", type: "bug" },
    }),
  ];

  it("returns all tasks when no filters are active", () => {
    expect(applyTaskBoardFilters(tasks, {})).toHaveLength(3);
  });

  it("filters by assignee", () => {
    const result = applyTaskBoardFilters(tasks, { assignee: "Alice" });
    expect(result).toHaveLength(2);
    expect(result.every((t) => t.assignee === "Alice")).toBe(true);
  });

  it("filters by priority", () => {
    const result = applyTaskBoardFilters(tasks, { priority: "high" });
    expect(result).toHaveLength(1);
    expect(result[0].priority).toBe("high");
  });

  it("filters by tag", () => {
    const result = applyTaskBoardFilters(tasks, { tag: "frontend" });
    expect(result).toHaveLength(2);
  });

  it("filters by custom field (sprint)", () => {
    const result = applyTaskBoardFilters(tasks, { sprint: "Sprint 1" });
    expect(result).toHaveLength(2);
  });

  it("combines multiple filters with AND logic", () => {
    const result = applyTaskBoardFilters(tasks, {
      assignee: "Alice",
      priority: "high",
    });
    expect(result).toHaveLength(1);
    expect(result[0].assignee).toBe("Alice");
    expect(result[0].priority).toBe("high");
  });

  it("combines task-property and custom-field filters", () => {
    const result = applyTaskBoardFilters(tasks, {
      assignee: "Alice",
      sprint: "Sprint 1",
      type: "bug",
    });
    expect(result).toHaveLength(1);
    expect(result[0].priority).toBe("medium");
  });

  it("returns empty array when no tasks match", () => {
    const result = applyTaskBoardFilters(tasks, { assignee: "Charlie" });
    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// TaskBoardFilters component
// ---------------------------------------------------------------------------

describe("TaskBoardFilters", () => {
  const tasks: FilterableTask[] = [
    buildTask({
      assignee: "Alice",
      priority: "high",
      tags: [{ id: "t1", name: "frontend", color: "#000" }],
    }),
    buildTask({
      assignee: "Bob",
      priority: "low",
      tags: [{ id: "t2", name: "backend", color: "#111" }],
    }),
    buildTask({
      assignee: "Alice",
      priority: "medium",
      tags: [{ id: "t2", name: "backend", color: "#111" }],
    }),
  ];

  it("renders assignee, priority, and tag filter dropdowns", () => {
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{}}
        onFiltersChange={() => {}}
      />,
    );

    expect(
      screen.getByRole("button", { name: /filter by assignee/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /filter by priority/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /filter by tag/i }),
    ).toBeInTheDocument();
  });

  it("does not render when there are no tasks at all", () => {
    const { container } = render(
      <TaskBoardFilters
        tasks={[]}
        filters={{}}
        onFiltersChange={() => {}}
      />,
    );

    expect(container.innerHTML).toBe("");
  });

  it("always renders assignee, priority, and tag filters even when all tasks are unassigned", () => {
    render(
      <TaskBoardFilters
        tasks={[buildTask()]}
        filters={{}}
        onFiltersChange={() => {}}
      />,
    );

    // Task-property filters are always visible (may be disabled when no options exist)
    expect(
      screen.getByRole("button", { name: /filter by assignee/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /filter by priority/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /filter by tag/i }),
    ).toBeInTheDocument();
  });

  it("calls onFiltersChange when a filter value is selected", () => {
    const onFiltersChange = vi.fn();
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{}}
        onFiltersChange={onFiltersChange}
      />,
    );

    // Open priority dropdown
    fireEvent.click(
      screen.getByRole("button", { name: /filter by priority/i }),
    );

    // Select "High"
    const listbox = screen.getByRole("listbox");
    fireEvent.click(within(listbox).getByText("High"));

    expect(onFiltersChange).toHaveBeenCalledWith({ priority: "high" });
  });

  it("shows clear all button with badge count when filters are active", () => {
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{ assignee: "Alice", priority: "high" }}
        onFiltersChange={() => {}}
      />,
    );

    const clearBtn = screen.getByRole("button", { name: /clear all/i });
    expect(clearBtn).toBeInTheDocument();

    // Badge shows count of active filters
    expect(
      within(clearBtn).getByLabelText(/2 active filters/i),
    ).toBeInTheDocument();
  });

  it("calls onFiltersChange with empty object on clear all", () => {
    const onFiltersChange = vi.fn();
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{ assignee: "Alice" }}
        onFiltersChange={onFiltersChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(onFiltersChange).toHaveBeenCalledWith({});
  });

  it("has correct aria-label on the filter group", () => {
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{}}
        onFiltersChange={() => {}}
      />,
    );

    expect(
      screen.getByRole("group", { name: /task board filters/i }),
    ).toBeInTheDocument();
  });

  it("dropdowns are keyboard accessible", () => {
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{}}
        onFiltersChange={() => {}}
      />,
    );

    const assigneeButton = screen.getByRole("button", {
      name: /filter by assignee/i,
    });

    // Button should be focusable and have aria attributes
    expect(assigneeButton).toHaveAttribute("aria-haspopup", "listbox");
    expect(assigneeButton).toHaveAttribute("aria-expanded", "false");
  });

  it("highlights active filter trigger with different styling", () => {
    render(
      <TaskBoardFilters
        tasks={tasks}
        filters={{ priority: "high" }}
        onFiltersChange={() => {}}
      />,
    );

    const priorityButton = screen.getByRole("button", {
      name: /filter by priority/i,
    });
    // Active filter should have dark background styling
    expect(priorityButton.className).toContain("bg-slate-900");
  });
});
