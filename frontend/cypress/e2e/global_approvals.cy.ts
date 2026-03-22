/// <reference types="cypress" />

import { buildBoard, buildApproval } from "../support/factories";
import { stubAuth, stubBoards } from "../support/intercepts";

describe("Global approvals", () => {
  const apiBase = "**/api/v1";

  it("can render a pending approval and approve it", () => {
    const board = buildBoard({ id: "b1", name: "Testing" });
    const approval = buildApproval({
      id: "a1",
      board_id: "b1",
      action_type: "task.closeout",
      status: "pending",
      confidence: 92,
      task_id: "t1",
      task_ids: ["t1"],
      payload: {
        task_id: "t1",
        title: "Close task",
        reason: "Merged and ready to close",
      },
    });

    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [board] });

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
      ["@usersMe", "@organizationsList", "@orgMeMember", "@boardsList", "@approvalsList"],
      { timeout: 20_000 },
    );

    cy.contains(/unapproved tasks/i).should("be.visible");
    cy.contains(/task\s*(?:·|\u00b7|\u2022)?\s*closeout/i).should("be.visible");

    cy.contains("button", /^approve$/i).click();
    cy.wait("@approvalUpdate", { timeout: 20_000 });

    cy.contains(/approved/i).should("be.visible");
  });
});
