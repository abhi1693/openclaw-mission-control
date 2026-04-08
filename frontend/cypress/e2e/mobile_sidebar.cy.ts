/// <reference types="cypress" />

import { stubAuth, stubBoards, stubDashboard } from "../support/intercepts";

describe("/dashboard - mobile sidebar", () => {
  const apiBase = "**/api/v1";

  function visitDashboardAuthenticated() {
    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [] });
    stubDashboard(apiBase);
    cy.loginWithLocalAuth();
    cy.visit("/dashboard");
    cy.waitForAppLoaded();
  }

  it("auth negative: signed-out user does not see hamburger button", () => {
    cy.visit("/dashboard");
    cy.contains("h1", /local authentication/i, { timeout: 30_000 }).should(
      "be.visible",
    );
    cy.get('[aria-label="Toggle navigation"]').should("not.exist");
  });

  it("mobile: hamburger button visible and sidebar hidden by default", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').should("be.visible");
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });

  it("desktop: hamburger button hidden and sidebar always visible", () => {
    cy.viewport(1280, 800);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').should("not.be.visible");
    cy.get("aside").should("be.visible");
  });

  it("mobile: click hamburger opens sidebar and shows backdrop", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("aside").should("be.visible");
    cy.get('[data-cy="sidebar-backdrop"]').should("exist");
  });

  it("mobile: click backdrop closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get('[data-cy="sidebar-backdrop"]').click({ force: true });
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });

  it("mobile: clicking a nav link closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("aside").should("be.visible");
    cy.get("aside").within(() => {
      cy.contains("a", "Boards").click();
    });
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
  });

  it("mobile: pressing Escape closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("body").type("{esc}");
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });
});
