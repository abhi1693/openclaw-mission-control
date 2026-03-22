/// <reference types="cypress" />

import { api } from "../support/integration/api";

describe("Task lifecycle (integration)", () => {
  const boardName = `Task Test Board ${Date.now()}`;
  const boardSlug = `task-test-${Date.now()}`;
  let boardId: string;

  before(() => {
    // Seed a board via API — the board is a prerequisite, not the behavior under test.
    api.createBoard({
      name: boardName,
      slug: boardSlug,
      description: "Created by E2E integration test",
      board_type: "general",
    }).then((res) => {
      expect(res.status).to.eq(200);
      boardId = res.body.id;
    });
  });

  it("create a task through the UI and verify it persists", () => {
    cy.loginWithLocalAuth();
    cy.visit(`/boards/${boardId}`);
    cy.waitForAppLoaded();

    const taskTitle = `E2E Task ${Date.now()}`;

    // Open create task dialog.
    cy.get('button[aria-label="New task"]', { timeout: 15_000 })
      .should("be.visible")
      .click();

    cy.contains('[role="dialog"]', "New task")
      .should("be.visible")
      .within(() => {
        cy.contains("label", "Title").parent().find("input").type(taskTitle);
        cy.contains("button", /^Create task$/)
          .should("be.visible")
          .and("not.be.disabled")
          .click();
      });

    // Task should appear in the board.
    cy.contains(taskTitle, { timeout: 10_000 }).should("be.visible");

    // Verify via API that the task was persisted.
    api.getTasks(boardId).then((res) => {
      expect(res.status).to.eq(200);
      const tasks = res.body.tasks || [];
      const created = tasks.find(
        (t: { title: string }) => t.title === taskTitle,
      );
      expect(created, `Task "${taskTitle}" should exist`).to.not.be.undefined;
    });
  });
});
