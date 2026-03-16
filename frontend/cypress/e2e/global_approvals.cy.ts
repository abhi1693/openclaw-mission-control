/// <reference types="cypress" />

import { setupCommonPageTestHooks } from "../support/testHooks";

describe("Global approvals", () => {
  const apiBase = "**/api/v1";

  setupCommonPageTestHooks(apiBase);

  it("can render a pending approval and approve it", () => {
    const approval = {
      id: "a1",
      board_id: "b1",
      action_type: "task.closeout",
      status: "pending",
      confidence: 92,
      created_at: "2026-02-14T00:00:00Z",
      task_id: "t1",
      task_ids: ["t1"],
      payload: {
        task_id: "t1",
        title: "Close task",
        reason: "Merged and ready to close",
      },
    };

    cy.intercept("GET", `${apiBase}/boards*`, {
      statusCode: 200,
      body: {
        items: [
          {
            id: "b1",
            name: "Testing",
            group_id: null,
            objective: null,
            success_metrics: null,
            target_date: null,
            updated_at: "2026-02-14T00:00:00Z",
            created_at: "2026-02-10T00:00:00Z",
          },
        ],
      },
    }).as("boardsList");

    cy.intercept("GET", `${apiBase}/boards/b1/approvals*`, {
      statusCode: 200,
      body: { items: [approval] },
    }).as("approvalsList");

    cy.intercept("PATCH", `${apiBase}/boards/b1/approvals/a1`, {
      statusCode: 200,
      body: { ...approval, status: "approved" },
    }).as("approvalUpdate");

    cy.loginWithLocalAuth();
    cy.visit("/approvals");
    cy.waitForAppLoaded();

    cy.wait(
      [
        "@usersMe",
        "@organizationsList",
        "@orgMeMember",
        "@boardsList",
        "@approvalsList",
      ],
      { timeout: 20_000 },
    );

    // Pending approval should be visible in the list.
    cy.contains(/unapproved tasks/i).should("be.visible");
    // Action type is humanized as "Task · Closeout" in the UI.
    cy.contains(/task\s*(?:·|\u00b7|\u2022)?\s*closeout/i).should("be.visible");

    cy.contains("button", /^approve$/i).click();
    cy.wait("@approvalUpdate", { timeout: 20_000 });

    // Status badge should flip to approved.
    cy.contains(/approved/i).should("be.visible");
  });
});
