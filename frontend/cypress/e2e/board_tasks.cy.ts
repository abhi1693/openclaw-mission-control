/// <reference types="cypress" />

describe("/boards/:id task board", () => {
  const apiBase = "**/api/v1";
  const email = "local-auth-user@example.com";

  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  function stubEmptySse() {
    // Keep known board-related SSE endpoints quiet in tests.
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
    cy.intercept("GET", `${apiBase}/agents/stream*`, emptySse).as("agentsStream");
  }

  function openEditTaskDialog() {
    cy.get('button[title="Edit task"]', { timeout: 20_000 })
      .should("be.visible")
      .and("not.be.disabled")
      .click();
    cy.get('[aria-label="Edit task"]', { timeout: 20_000 }).should("be.visible");
  }

  it("auth negative: signed-out user is shown local auth login", () => {
    cy.visit("/boards/b1");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("happy path: renders tasks from snapshot and supports create + status update + delete (stubbed)", () => {
    stubEmptySse();

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
        email,
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
        tasks: [
          {
            id: "t1",
            board_id: "b1",
            title: "Inbox task",
            description: "",
            status: "inbox",
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
          },
        ],
        agents: [],
        approvals: [],
        chat_messages: [],
        pending_approvals_count: 0,
      },
    }).as("snapshot");

    cy.intercept("GET", `${apiBase}/boards/b1/group-snapshot*`, {
      statusCode: 200,
      body: { group: null, boards: [] },
    }).as("groupSnapshot");

    cy.intercept("POST", `${apiBase}/boards/b1/tasks`, (req) => {
      // Minimal assertion the UI sends expected fields.
      expect(req.body).to.have.property("title");
      req.reply({
        statusCode: 200,
        body: {
          id: "t2",
          board_id: "b1",
          title: req.body.title,
          description: req.body.description ?? "",
          status: "inbox",
          priority: req.body.priority ?? "medium",
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
        },
      });
    }).as("createTask");

    cy.intercept("PATCH", `${apiBase}/boards/b1/tasks/t1`, (req) => {
      expect(req.body).to.have.property("status");
      req.reply({
        statusCode: 200,
        body: {
          id: "t1",
          board_id: "b1",
          title: "Inbox task",
          description: "",
          status: req.body.status,
          priority: "medium",
          due_at: null,
          assigned_agent_id: null,
          depends_on_task_ids: [],
          created_by_user_id: null,
          in_progress_at: null,
          created_at: "2026-02-11T00:00:00Z",
          updated_at: "2026-02-11T00:00:01Z",
          blocked_by_task_ids: [],
          is_blocked: false,
          assignee: null,
          approvals_count: 0,
          approvals_pending_count: 0,
        },
      });
    }).as("updateTask");

    cy.intercept("DELETE", `${apiBase}/boards/b1/tasks/t1`, {
      statusCode: 200,
      body: { ok: true },
    }).as("deleteTask");

    cy.intercept("GET", `${apiBase}/boards/b1/tasks/t1/comments*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("taskComments");

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

    // Existing task visible.
    cy.contains("Inbox task").should("be.visible");

    // Open create task flow.
    // Board page uses an icon-only button with aria-label="New task".
    cy.get('button[aria-label="New task"]')
      .should("be.visible")
      .and("not.be.disabled")
      .click();

    cy.contains('[role="dialog"]', "New task")
      .should("be.visible")
      .within(() => {
        cy.contains("label", "Title").parent().find("input").type("New task");
        cy.contains("button", /^Create task$/)
          .should("be.visible")
          .and("not.be.disabled")
          .click();
      });
    cy.wait(["@createTask"]);

    cy.contains("New task").should("be.visible");

    // Open edit task dialog.
    cy.contains("Inbox task").scrollIntoView().should("be.visible").click();
    cy.wait(["@taskComments"]);
    cy.contains(/task detail/i).should("be.visible");
    openEditTaskDialog();

    // Change status via Status select.
    cy.get('[aria-label="Edit task"]').within(() => {
      cy.contains("label", "Status")
        .parent()
        .within(() => {
          cy.get('[role="combobox"]').first().should("be.visible").click();
        });
    });

    cy.contains("In progress").should("be.visible").click();

    cy.contains("button", /save changes/i)
      .should("be.visible")
      .and("not.be.disabled")
      .click();
    cy.wait(["@updateTask"]);
    cy.get('[aria-label="Edit task"]').should("not.exist");

    // Save closes the edit dialog; reopen it from task detail.
    cy.contains(/task detail/i).should("be.visible");
    openEditTaskDialog();

    // Delete task via delete dialog.
    cy.get('[aria-label="Edit task"]').within(() => {
      cy.contains("button", /^Delete task$/)
        .scrollIntoView()
        .should("be.visible")
        .and("not.be.disabled")
        .click();
    });
    cy.get('[aria-label="Delete task"]').should("be.visible");
    cy.get('[aria-label="Delete task"]').within(() => {
      cy.contains("button", /^Delete task$/)
        .scrollIntoView()
        .should("be.visible")
        .and("not.be.disabled")
        .click();
    });
    cy.wait(["@deleteTask"]);

    cy.contains("Inbox task").should("not.exist");
  });
});
