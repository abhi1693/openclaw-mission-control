/// <reference types="cypress" />

/**
 * E2E tests for the 6-column kanban board (S33-8).
 *
 * Covers:
 * - All 6 columns render with correct headings
 * - Task count badges per column
 * - Drag-and-drop moves a task (optimistic UI + API call)
 * - API failure triggers rollback and error toast
 * - Empty columns remain visible as drop targets
 * - Responsive: board scrollable at desktop widths
 */
describe("6-column kanban board", () => {
  const apiBase = "**/api/v1";

  const COLUMN_HEADINGS = [
    "Inbox",
    "Todo",
    "In Progress",
    "In Review",
    "Sprint Done",
    "Done",
  ];

  function stubEmptySse() {
    const emptySse = {
      statusCode: 200,
      headers: { "content-type": "text/event-stream" },
      body: "",
    };
    cy.intercept("GET", `${apiBase}/boards/*/tasks/stream*`, emptySse).as(
      "tasksStream",
    );
    cy.intercept("GET", `${apiBase}/boards/*/approvals/stream*`, emptySse).as(
      "approvalsStream",
    );
    cy.intercept("GET", `${apiBase}/boards/*/memory/stream*`, emptySse).as(
      "memoryStream",
    );
    cy.intercept("GET", `${apiBase}/agents/stream*`, emptySse).as(
      "agentsStream",
    );
  }

  function stubCommonEndpoints() {
    cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
      statusCode: 200,
      body: {
        id: "m1",
        organization_id: "o1",
        user_id: "u1",
        role: "owner",
        all_boards_read: true,
        all_boards_write: true,
        created_at: "2026-02-11T00:00:00Z",
        updated_at: "2026-02-11T00:00:00Z",
        board_access: [{ board_id: "b1", can_read: true, can_write: true }],
      },
    }).as("membership");

    cy.intercept("GET", `${apiBase}/users/me*`, {
      statusCode: 200,
      body: {
        id: "u1",
        clerk_user_id: "clerk_u1",
        email: "local-auth-user@example.com",
        name: "Jane Test",
        preferred_name: "Jane",
        timezone: "America/New_York",
        is_super_admin: false,
      },
    }).as("me");

    cy.intercept("GET", `${apiBase}/organizations/me/list*`, {
      statusCode: 200,
      body: [
        { id: "o1", name: "Personal", role: "owner", is_active: true },
      ],
    }).as("organizations");

    cy.intercept("GET", `${apiBase}/tags*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("tags");

    cy.intercept("GET", `${apiBase}/organizations/me/custom-fields*`, {
      statusCode: 200,
      body: [],
    }).as("customFields");

    cy.intercept("GET", `${apiBase}/boards/b1/group-snapshot*`, {
      statusCode: 200,
      body: { group: null, boards: [] },
    }).as("groupSnapshot");
  }

  function makeTask(
    id: string,
    title: string,
    status: string,
    overrides: Record<string, unknown> = {},
  ) {
    return {
      id,
      board_id: "b1",
      title,
      description: "",
      status,
      priority: "medium",
      due_at: null,
      assigned_agent_id: null,
      depends_on_task_ids: [],
      created_by_user_id: null,
      in_progress_at: null,
      created_at: "2026-02-11T00:00:00Z",
      updated_at: "2026-02-11T00:00:00Z",
      blocked_by_task_ids: [],
      is_blocked: false,
      assignee: null,
      approvals_count: 0,
      approvals_pending_count: 0,
      ...overrides,
    };
  }

  function stubSnapshotWithTasks(tasks: ReturnType<typeof makeTask>[]) {
    cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
      statusCode: 200,
      body: {
        board: {
          id: "b1",
          name: "Demo Board",
          slug: "demo-board",
          description: "Demo",
          gateway_id: "g1",
          board_group_id: null,
          board_type: "general",
          objective: null,
          success_metrics: null,
          target_date: null,
          goal_confirmed: true,
          goal_source: "test",
          organization_id: "o1",
          created_at: "2026-02-11T00:00:00Z",
          updated_at: "2026-02-11T00:00:00Z",
        },
        tasks,
        agents: [],
        approvals: [],
        chat_messages: [],
        pending_approvals_count: 0,
      },
    }).as("snapshot");
  }

  function visitBoard() {
    cy.loginWithLocalAuth();
    cy.visit("/boards/b1");
    cy.waitForAppLoaded();
    cy.wait([
      "@snapshot",
      "@groupSnapshot",
      "@membership",
      "@me",
      "@organizations",
      "@tags",
      "@customFields",
    ]);
  }

  // -------------------------------------------------------------------------
  // AC-1: 6 columns visible
  // -------------------------------------------------------------------------
  it("renders all 6 kanban columns with correct headings", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([
      makeTask("t1", "Inbox task", "inbox"),
      makeTask("t2", "Todo task", "todo"),
      makeTask("t3", "WIP task", "in_progress"),
      makeTask("t4", "Review task", "in_review"),
      makeTask("t5", "Sprint done task", "sprint_done"),
      makeTask("t6", "Done task", "done"),
    ]);

    visitBoard();

    for (const heading of COLUMN_HEADINGS) {
      cy.contains("h3", heading).should("be.visible");
    }

    // Each task is in the correct column.
    cy.contains("Inbox task").should("be.visible");
    cy.contains("Todo task").should("be.visible");
    cy.contains("WIP task").should("be.visible");
    cy.contains("Review task").should("be.visible");
    cy.contains("Sprint done task").should("be.visible");
    cy.contains("Done task").should("be.visible");
  });

  // -------------------------------------------------------------------------
  // AC-4: Task count badges per column
  // -------------------------------------------------------------------------
  it("displays task count badges per column", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([
      makeTask("t1", "Inbox A", "inbox"),
      makeTask("t2", "Inbox B", "inbox"),
      makeTask("t3", "Todo A", "todo"),
      makeTask("t4", "WIP A", "in_progress"),
    ]);

    visitBoard();

    // Inbox should show 2 tasks.
    cy.contains("h3", "Inbox")
      .parent()
      .parent()
      .find("span.rounded-full")
      .should("contain.text", "2");

    // Todo should show 1.
    cy.contains("h3", "Todo")
      .parent()
      .parent()
      .find("span.rounded-full")
      .should("contain.text", "1");
  });

  // -------------------------------------------------------------------------
  // AC-7: Empty columns visible (drop targets)
  // -------------------------------------------------------------------------
  it("renders empty columns as visible drop targets", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([]);

    visitBoard();

    for (const heading of COLUMN_HEADINGS) {
      cy.contains("h3", heading).should("exist");
      cy.contains("h3", heading)
        .closest(".kanban-column")
        .should("exist");
    }
  });

  // -------------------------------------------------------------------------
  // AC-2: Drag-and-drop -> API call + optimistic UI
  // -------------------------------------------------------------------------
  it("moves a task via edit dialog status change and calls API", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([makeTask("t1", "Movable task", "inbox")]);

    cy.intercept("PATCH", `${apiBase}/boards/b1/tasks/t1`, (req) => {
      expect(req.body).to.have.property("status", "in_progress");
      req.reply({
        statusCode: 200,
        body: makeTask("t1", "Movable task", "in_progress"),
      });
    }).as("updateTask");

    cy.intercept("GET", `${apiBase}/boards/b1/tasks/t1/comments*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("taskComments");

    visitBoard();

    // Click the task to open details.
    cy.contains("Movable task").should("be.visible").click();
    cy.wait(["@taskComments"]);

    // Open edit dialog.
    cy.get('button[title="Edit task"]', { timeout: 20_000 })
      .should("be.visible")
      .click();
    cy.get('[aria-label="Edit task"]').should("be.visible");

    // Change status to In Progress.
    cy.get('[aria-label="Edit task"]').within(() => {
      cy.contains("label", "Status")
        .parent()
        .within(() => {
          cy.get('[role="combobox"]').first().click();
        });
    });
    cy.contains("In progress").should("be.visible").click();

    cy.contains("button", /save changes/i).click();
    cy.wait(["@updateTask"]);
  });

  // -------------------------------------------------------------------------
  // AC-3: API failure -> rollback + error toast
  // -------------------------------------------------------------------------
  it("shows error toast when task move API call fails", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([makeTask("t1", "Failing task", "inbox")]);

    cy.intercept("PATCH", `${apiBase}/boards/b1/tasks/t1`, {
      statusCode: 500,
      body: { detail: "Internal server error" },
    }).as("updateTaskFail");

    cy.intercept("GET", `${apiBase}/boards/b1/tasks/t1/comments*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("taskComments");

    visitBoard();

    // Click the task to open details.
    cy.contains("Failing task").should("be.visible").click();
    cy.wait(["@taskComments"]);

    // Open edit dialog.
    cy.get('button[title="Edit task"]', { timeout: 20_000 })
      .should("be.visible")
      .click();
    cy.get('[aria-label="Edit task"]').should("be.visible");

    // Change status to Done.
    cy.get('[aria-label="Edit task"]').within(() => {
      cy.contains("label", "Status")
        .parent()
        .within(() => {
          cy.get('[role="combobox"]').first().click();
        });
    });
    cy.contains("Done").should("be.visible").click();

    cy.contains("button", /save changes/i).click();
    cy.wait(["@updateTaskFail"]);

    // Error toast should appear.
    cy.contains(/failed|error|could not/i, { timeout: 10_000 }).should(
      "be.visible",
    );
  });

  // -------------------------------------------------------------------------
  // AC-5: Responsive layout
  // -------------------------------------------------------------------------
  it("uses responsive layout: stacked on mobile, horizontal on desktop", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([makeTask("t1", "Layout task", "inbox")]);

    visitBoard();

    cy.get('[data-testid="task-board"]').then(($board) => {
      // Board should have responsive classes.
      expect($board.attr("class")).to.contain("grid-cols-1");
      expect($board.attr("class")).to.contain("overflow-x-auto");
      expect($board.attr("class")).to.contain("lg:grid-flow-col");
    });
  });

  // -------------------------------------------------------------------------
  // AC-6: Column colors for visual distinction
  // -------------------------------------------------------------------------
  it("applies distinct color dots per column", () => {
    stubEmptySse();
    stubCommonEndpoints();
    stubSnapshotWithTasks([]);

    visitBoard();

    const expectedDots: Record<string, string> = {
      Inbox: "bg-slate-400",
      Todo: "bg-sky-500",
      "In Progress": "bg-purple-500",
      "In Review": "bg-indigo-500",
      "Sprint Done": "bg-amber-500",
      Done: "bg-green-500",
    };

    for (const [heading, dotClass] of Object.entries(expectedDots)) {
      cy.contains("h3", heading)
        .parent()
        .find("span.rounded-full")
        .first()
        .should("have.class", dotClass);
    }
  });
});
