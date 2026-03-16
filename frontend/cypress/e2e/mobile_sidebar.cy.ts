/// <reference types="cypress" />

import { setupCommonPageTestHooks } from "../support/testHooks";

describe("/dashboard - mobile sidebar", () => {
  const apiBase = "**/api/v1";

  setupCommonPageTestHooks(apiBase);

  const emptySeries = {
    primary: { range: "7d", bucket: "day", points: [] },
    comparison: { range: "7d", bucket: "day", points: [] },
  };

  function stubDashboardApis() {
    cy.intercept("GET", `${apiBase}/metrics/dashboard*`, {
      statusCode: 200,
      body: {
        generated_at: new Date().toISOString(),
        range: "7d",
        kpis: {
          inbox_tasks: 0,
          in_progress_tasks: 0,
          review_tasks: 0,
          done_tasks: 0,
          tasks_in_progress: 0,
          active_agents: 0,
          error_rate_pct: 0,
          median_cycle_time_hours_7d: null,
        },
        throughput: emptySeries,
        cycle_time: emptySeries,
        error_rate: emptySeries,
        wip: emptySeries,
        pending_approvals: { items: [], total: 0 },
      },
    }).as("dashboardMetrics");

    cy.intercept("GET", `${apiBase}/boards*`, {
      statusCode: 200,
      body: { items: [], total: 0 },
    }).as("boardsList");

    cy.intercept("GET", `${apiBase}/agents*`, {
      statusCode: 200,
      body: { items: [], total: 0 },
    }).as("agentsList");

    cy.intercept("GET", `${apiBase}/activity*`, {
      statusCode: 200,
      body: { items: [], total: 0 },
    }).as("activityList");

    cy.intercept("GET", `${apiBase}/gateways/status*`, {
      statusCode: 200,
      body: { gateways: [] },
    }).as("gatewaysStatus");

    cy.intercept("GET", `${apiBase}/board-groups*`, {
      statusCode: 200,
      body: { items: [], total: 0 },
    }).as("boardGroupsList");
  }

  function visitDashboardAuthenticated() {
    stubDashboardApis();
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

    // Open sidebar first
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");

    // Click the backdrop overlay
    cy.get('[data-cy="sidebar-backdrop"]').click({ force: true });

    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });

  it("mobile: clicking a nav link closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();

    // Open sidebar
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");
    cy.get("aside").should("be.visible");

    // Click a navigation link inside the sidebar
    cy.get("aside").within(() => {
      cy.contains("a", "Boards").click();
    });

    // Sidebar should close after navigation
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
  });

  it("mobile: pressing Escape closes sidebar", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();

    // Open sidebar
    cy.get('[aria-label="Toggle navigation"]').click();
    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "open");

    // Press Escape
    cy.get("body").type("{esc}");

    cy.get("[data-sidebar]").should("have.attr", "data-sidebar", "closed");
    cy.get("aside").should("not.be.visible");
  });
});
