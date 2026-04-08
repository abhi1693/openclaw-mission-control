/// <reference types="cypress" />

import { api } from "../support/integration/api";

describe("Board lifecycle (integration)", () => {
  const boardName = `E2E Board ${Date.now()}`;
  const boardSlug = `e2e-board-${Date.now()}`;

  it("create a board through the UI and verify it persists", () => {
    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    // Click create board.
    cy.contains("a", /create board/i).click();

    // Fill out the create board form.
    cy.get('input[name="name"], input[placeholder*="name" i]', { timeout: 10_000 })
      .should("be.visible")
      .clear()
      .type(boardName);

    cy.get('input[name="slug"], input[placeholder*="slug" i]')
      .should("be.visible")
      .clear()
      .type(boardSlug);

    // Submit the form.
    cy.contains("button", /create/i)
      .should("be.visible")
      .and("not.be.disabled")
      .click();

    // Should navigate to the new board or show success.
    cy.url({ timeout: 15_000 }).should("include", "/boards/");

    // Verify via API that the board was persisted.
    api.getBoards().then((res) => {
      expect(res.status).to.eq(200);
      const boards = res.body.items || res.body;
      const created = boards.find(
        (b: { name: string }) => b.name === boardName,
      );
      expect(created, `Board "${boardName}" should exist in API response`).to.not
        .be.undefined;
    });
  });
});
