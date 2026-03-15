/// <reference types="cypress" />

import { buildBoard, buildBoardSnapshot } from "../support/factories";
import { stubAuth, stubBoards } from "../support/intercepts";

describe("Local auth login", () => {
  it("user with local auth token can access protected route", () => {
    const apiBase = "**/api/v1";
    const board = buildBoard({ id: "b1", name: "Testing" });

    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [board] });

    cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
      statusCode: 200,
      body: buildBoardSnapshot(board),
    }).as("boardSnapshot");

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    cy.waitForAppLoaded();
    cy.contains(/live feed/i).should("be.visible");
  });
});
