/// <reference types="cypress" />

import {
  buildBoard,
  buildBoardSnapshot,
  buildTask,
  buildOrgMember,
} from "../support/factories";
import { stubAuth, stubBoards, stubEmptySSEStreams } from "../support/intercepts";

describe("/boards/:id task board", () => {
  const apiBase = "**/api/v1";
  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

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
    const board = buildBoard({
      id: "b1",
      name: "Demo Board",
      slug: "demo-board",
      description: "Demo",
      gateway_id: "g1",
      goal_source: "test",
      organization_id: "o1",
    });

    const existingTask = buildTask({
      id: "t1",
      board_id: "b1",
      title: "Inbox task",
      status: "inbox",
    });

    stubEmptySSEStreams(apiBase);

    stubAuth(apiBase, {
      user: { id: "u1", clerk_user_id: "clerk_u1", email: "local-auth-user@example.com", name: "Jane Test", preferred_name: "Jane", timezone: "America/New_York", is_super_admin: false },
      org: { id: "o1", name: "Personal" },
      member: buildOrgMember({
        id: "m1",
        organization_id: "o1",
        user_id: "u1",
        board_access: [{ board_id: "b1", can_read: true, can_write: true }],
      }),
    });

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
      body: buildBoardSnapshot(board, { tasks: [existingTask] }),
    }).as("snapshot");

    cy.intercept("GET", `${apiBase}/boards/b1/group-snapshot*`, {
      statusCode: 200,
      body: { group: null, boards: [] },
    }).as("groupSnapshot");

    cy.intercept("POST", `${apiBase}/boards/b1/tasks`, (req) => {
      expect(req.body).to.have.property("title");
      const newTask = buildTask({
        id: "t2",
        board_id: "b1",
        title: req.body.title,
        description: req.body.description ?? "",
        priority: req.body.priority ?? "medium",
      });
      req.reply({ statusCode: 200, body: newTask });
    }).as("createTask");

    cy.intercept("PATCH", `${apiBase}/boards/b1/tasks/t1`, (req) => {
      expect(req.body).to.have.property("status");
      const updated = buildTask({
        ...existingTask,
        status: req.body.status,
        updated_at: "2026-01-01T00:00:01.000Z",
      });
      req.reply({ statusCode: 200, body: updated });
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
      "@orgMeMember",
      "@usersMe",
      "@organizationsList",
      "@tags",
      "@customFields",
    ]);

    // Existing task visible.
    cy.contains("Inbox task").should("be.visible");

    // Create task flow.
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

    // Reopen and delete.
    cy.contains(/task detail/i).should("be.visible");
    openEditTaskDialog();

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
