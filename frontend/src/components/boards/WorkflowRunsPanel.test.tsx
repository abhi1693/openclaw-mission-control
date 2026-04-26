import { render, screen } from "@testing-library/react";

import { WorkflowRunsPanel } from "./WorkflowRunsPanel";

describe("WorkflowRunsPanel", () => {
  it("renders workflow run summaries", () => {
    render(
      <WorkflowRunsPanel
        runs={[
          {
            id: "run-1",
            title: "Research → plan",
            status: "waiting_human",
            current_step_key: "review",
            source_task_id: "task-1",
            waiting_step_count: 1,
            approval_step_count: 0,
            human_step_count: 1,
            created_at: "2026-04-25T20:00:00Z",
            updated_at: "2026-04-25T20:05:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("Workflow runs")).toBeInTheDocument();
    expect(screen.getByText("Research → plan")).toBeInTheDocument();
    expect(screen.getByText(/Current step: review/i)).toBeInTheDocument();
    expect(screen.getByText(/Waiting 1/i)).toBeInTheDocument();
  });

  it("renders an empty state", () => {
    render(<WorkflowRunsPanel runs={[]} />);

    expect(screen.getByText(/No workflow runs yet/i)).toBeInTheDocument();
  });
});
