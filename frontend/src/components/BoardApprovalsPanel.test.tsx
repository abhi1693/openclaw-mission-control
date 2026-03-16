import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ApprovalRead } from "@/api/generated/model";
import { BoardApprovalsPanel } from "./BoardApprovalsPanel";

vi.mock("@/auth/clerk", () => ({
  useAuth: () => ({ isSignedIn: true }),
}));

vi.mock("recharts", () => {
  type BoxProps = React.PropsWithChildren<{ className?: string }>;
  const Box = ({ children, className }: BoxProps) => (
    <div className={className}>{children}</div>
  );
  return {
    ResponsiveContainer: Box,
    Tooltip: Box,
    Legend: Box,
    PieChart: Box,
    Pie: Box,
    Cell: Box,
  };
});

const renderWithQueryClient = (ui: React.ReactNode) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
};

describe("BoardApprovalsPanel", () => {
  it("renders nested linked-approval metadata and rubric scores", () => {
    const approval = {
      id: "approval-1",
      board_id: "board-1",
      action_type: "task.create",
      confidence: 62,
      status: "pending",
      task_id: "task-1",
      created_at: "2026-02-12T10:00:00Z",
      resolved_at: null,
      payload: {
        linked_request: {
          tasks: [
            {
              task_id: "task-1",
              title: "Launch onboarding checklist",
              description: "Create and validate the v1 onboarding checklist.",
            },
            {
              task_id: "task-2",
              title: "Publish onboarding checklist",
            },
          ],
          task_ids: ["task-1", "task-2"],
        },
        decision: { reason: "Needs explicit sign-off before rollout." },
        analytics: {
          rubric_scores: {
            clarity: 25,
            risk: 20,
            dependencies: 15,
          },
        },
      },
      task_ids: ["task-1", "task-2"],
      rubric_scores: null,
    } as ApprovalRead;

    renderWithQueryClient(
      <BoardApprovalsPanel boardId="board-1" approvals={[approval]} />,
    );

    expect(
      screen.getAllByText("Launch onboarding checklist").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText("Create and validate the v1 onboarding checklist."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Needs explicit sign-off before rollout."),
    ).toBeInTheDocument();
    expect(screen.getByText("62% score")).toBeInTheDocument();
    expect(screen.getByText(/related tasks/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Launch onboarding checklist" }),
    ).toHaveAttribute("href", "/boards/board-1?taskId=task-1");
    expect(
      screen.getByRole("link", { name: "Publish onboarding checklist" }),
    ).toHaveAttribute("href", "/boards/board-1?taskId=task-2");
    expect(screen.getByText(/rubric scores/i)).toBeInTheDocument();
    expect(screen.getByText("Clarity")).toBeInTheDocument();
  });

  it("uses schema task_titles for related task links when payload titles are missing", () => {
    const approval = {
      id: "approval-2",
      board_id: "board-1",
      action_type: "task.update",
      confidence: 88,
      status: "pending",
      task_id: "task-a",
      task_ids: ["task-a", "task-b"],
      task_titles: ["Prepare release notes", "Publish release notes"],
      created_at: "2026-02-12T11:00:00Z",
      resolved_at: null,
      payload: {
        task_ids: ["task-a", "task-b"],
        reason: "Needs sign-off before publishing.",
      },
      rubric_scores: null,
    } as ApprovalRead;

    renderWithQueryClient(
      <BoardApprovalsPanel boardId="board-1" approvals={[approval]} />,
    );

    expect(
      screen.getByRole("link", { name: "Prepare release notes" }),
    ).toHaveAttribute("href", "/boards/board-1?taskId=task-a");
    expect(
      screen.getByRole("link", { name: "Publish release notes" }),
    ).toHaveAttribute("href", "/boards/board-1?taskId=task-b");
  });
});
