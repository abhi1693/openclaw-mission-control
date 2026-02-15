/// <reference types="cypress" />

describe("/boards", () => {
  const apiBase = "**/api/v1";
  const email = Cypress.env("CLERK_TEST_EMAIL") || "jane+clerk_test@example.com";

  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  it("auth negative: signed-out user is redirected to sign-in", () => {
    cy.visit("/boards");
    cy.location("pathname", { timeout: 30_000 }).should("match", /\/sign-in/);
  });

  it("happy path: signed-in user sees boards list", () => {
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

    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    cy.visit("/boards");
    cy.waitForAppLoaded();

    cy.wait(["@boards", "@boardGroups"]);

    cy.contains(/boards/i).should("be.visible");
    cy.contains("Demo Board").should("be.visible");
  });
});
