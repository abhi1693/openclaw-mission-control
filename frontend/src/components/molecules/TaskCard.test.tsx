import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TaskCard } from "./TaskCard";

describe("TaskCard", () => {
  it("renders title, assignee, and due date", () => {
    render(
      <TaskCard
        title="Fix flaky test"
        assignee="Zara"
        due="Feb 11"
        priority="high"
      />,
    );

    expect(screen.getByText("Fix flaky test")).toBeInTheDocument();
    expect(screen.getByText("Zara")).toBeInTheDocument();
    expect(screen.getByText("Feb 11")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
  });

  it("shows blocked state with count", () => {
    render(
      <TaskCard title="Blocked task" isBlocked blockedByCount={2} priority="low" />,
    );

    expect(screen.getByText(/Blocked · 2/i)).toBeInTheDocument();
  });

  it("shows approvals pending indicator", () => {
    render(
      <TaskCard
        title="Needs approval"
        approvalsPendingCount={3}
        priority="medium"
      />,
    );

    expect(screen.getByText(/Approval needed · 3/i)).toBeInTheDocument();
  });

  it("shows lead review indicator when status is review with no approvals and not blocked", () => {
    render(<TaskCard title="Waiting" status="review" approvalsPendingCount={0} />);

    expect(screen.getByText(/Waiting for lead review/i)).toBeInTheDocument();
  });

  it("invokes onClick for mouse and keyboard activation", () => {
    const onClick = vi.fn();

    render(<TaskCard title="Clickable" onClick={onClick} />);

    fireEvent.click(screen.getByRole("button", { name: /Clickable/i }));
    expect(onClick).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByRole("button", { name: /Clickable/i }), {
      key: "Enter",
    });
    expect(onClick).toHaveBeenCalledTimes(2);

    fireEvent.keyDown(screen.getByRole("button", { name: /Clickable/i }), {
      key: " ",
    });
    expect(onClick).toHaveBeenCalledTimes(3);
  });
});
