/// <reference types="cypress" />

import { buildBoard } from "../support/factories";
import { stubAuth, stubBoards } from "../support/intercepts";

describe("/boards", () => {
  const apiBase = "**/api/v1";

  it("auth negative: signed-out user is shown local auth login", () => {
    cy.visit("/boards");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("happy path: signed-in user sees boards list and create button", () => {
    const board = buildBoard({
      id: "b1",
      name: "Demo Board",
      slug: "demo-board",
      description: "Demo",
      gateway_id: "g1",
      goal_source: "test",
      organization_id: "o1",
    });

    stubAuth(apiBase, {
      user: { id: "u1", clerk_user_id: "clerk_u1", email: "local-auth-user@example.com", name: "Jane Test", preferred_name: "Jane", timezone: "America/New_York", is_super_admin: false },
      org: { id: "o1", name: "Personal" },
      member: { id: "m1", organization_id: "o1", user_id: "u1" },
    });
    stubBoards(apiBase, { boards: [board] });

    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    cy.wait(["@orgMeMember", "@usersMe", "@organizationsList", "@boardsList", "@boardGroupsList"]);

    cy.contains(/boards/i).should("be.visible");
    cy.contains("Demo Board").should("be.visible");
    cy.contains("a", /create board/i).should("be.visible");
  });
});
