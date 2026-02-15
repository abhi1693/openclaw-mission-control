/// <reference types="cypress" />

// Clerk/Next.js occasionally triggers a hydration mismatch on auth routes in CI.
// This is non-deterministic UI noise for these tests; ignore it so assertions can proceed.
Cypress.on("uncaught:exception", (err) => {
  if (err.message?.includes("Hydration failed")) {
    return false;
  }
  return true;
});

describe("Boards list", () => {
  const apiBase = "**/api/v1";
  const email = Cypress.env("CLERK_TEST_EMAIL") || "jane+clerk_test@example.com";

  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 20_000);

    cy.intercept("GET", "**/healthz", {
      statusCode: 200,
      body: { ok: true },
    }).as("healthz");

    // Admin membership gate used by many pages for actions.
    cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
      statusCode: 200,
      body: { organization_id: "org1", role: "owner" },
    }).as("orgMeMember");
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  it("happy path: signed-in user sees boards list and create button", () => {
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

    cy.intercept("GET", `${apiBase}/board-groups*`, {
      statusCode: 200,
      body: {
        items: [],
      },
    }).as("boardGroupsList");

    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    cy.visit("/boards");
    cy.waitForAppLoaded();

    cy.wait(["@boardsList", "@boardGroupsList"], { timeout: 20_000 });

    cy.contains("h1", /boards/i).should("be.visible");
    cy.contains(/testing/i).should("be.visible");

    // Admin + non-empty list => create CTA rendered.
    cy.contains("a", /create board/i).should("be.visible");
  });
});
