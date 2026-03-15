/// <reference types="cypress" />

describe("Auth: protected route access (integration)", () => {
  it("unauthenticated user is redirected to sign-in", () => {
    // Visit without setting auth token in session storage.
    cy.visit("/boards");
    cy.contains(/local authentication|sign in/i, { timeout: 30_000 }).should(
      "be.visible",
    );
  });

  it("authenticated user can access boards with real API data", () => {
    cy.loginWithLocalAuth();
    cy.visit("/boards");
    cy.waitForAppLoaded();

    // The seeded org should be visible (real data from backend-e2e).
    // The boards list may be empty (no boards seeded) but the page should render.
    cy.contains(/boards/i).should("be.visible");
    cy.contains("a", /create board/i).should("be.visible");
  });
});
