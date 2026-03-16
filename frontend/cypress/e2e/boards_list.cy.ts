/// <reference types="cypress" />

import { setupCommonPageTestHooks } from "../support/testHooks";

describe("/boards", () => {
  const apiBase = "**/api/v1";
  const email = "local-auth-user@example.com";

  setupCommonPageTestHooks(apiBase);

  it("auth negative: signed-out user is shown local auth login", () => {
    cy.visit("/boards");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("happy path: signed-in user sees boards list and create button", () => {
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
        board_access: [],
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
      body: [{ id: "o1", name: "Personal", role: "owner", is_active: true }],
    }).as("organizations");

    cy.intercept("GET", `${apiBase}/boards*`, {
      statusCode: 200,
      body: {
        items: [
          {
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
        ],
        total: 1,
        limit: 200,
        offset: 0,
      },
    }).as("boards");

    cy.intercept("GET", `${apiBase}/board-groups*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("boardGroups");

    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    cy.wait(["@membership", "@me", "@organizations", "@boards", "@boardGroups"]);

    cy.contains(/boards/i).should("be.visible");
    cy.contains("Demo Board").should("be.visible");
    cy.contains("a", /create board/i).should("be.visible");
  });
});
