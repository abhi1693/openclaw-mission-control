/// <reference types="cypress" />

import { setupCommonPageTestHooks } from "../support/testHooks";

describe("/dashboard - desktop sidebar collapse", () => {
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

  it("desktop: collapse toggle is visible and sidebar starts expanded", () => {
    cy.viewport(1280, 800);
    visitDashboardAuthenticated();

    cy.get('[data-cy="sidebar-collapse-toggle"]').should("be.visible");
    cy.get("[data-sidebar-collapsed]").should(
      "have.attr",
      "data-sidebar-collapsed",
      "false",
    );
    cy.get("aside").contains("Dashboard").should("be.visible");
  });

  it("desktop: clicking toggle collapses sidebar to icon-only", () => {
    cy.viewport(1280, 800);
    visitDashboardAuthenticated();

    cy.get('[data-cy="sidebar-collapse-toggle"]').click();

    cy.get("[data-sidebar-collapsed]").should(
      "have.attr",
      "data-sidebar-collapsed",
      "true",
    );
    // Label "Dashboard" is now sr-only, not visible to sighted users
    cy.get("aside")
      .contains("a", "Dashboard")
      .should(
        "have.attr",
        "aria-label",
        "Dashboard",
      );
    cy.get("aside")
      .contains("a", "Dashboard")
      .find("span")
      .should("have.class", "sr-only");
  });

  it("desktop: collapsed state persists across page reload", () => {
    cy.viewport(1280, 800);
    visitDashboardAuthenticated();

    cy.get('[data-cy="sidebar-collapse-toggle"]').click();
    cy.get("[data-sidebar-collapsed]").should(
      "have.attr",
      "data-sidebar-collapsed",
      "true",
    );

    cy.reload();
    cy.waitForAppLoaded();

    cy.get("[data-sidebar-collapsed]").should(
      "have.attr",
      "data-sidebar-collapsed",
      "true",
    );
  });

  it("desktop: clicking toggle again expands sidebar", () => {
    cy.viewport(1280, 800);
    visitDashboardAuthenticated();

    cy.get('[data-cy="sidebar-collapse-toggle"]').click();
    cy.get("[data-sidebar-collapsed]").should(
      "have.attr",
      "data-sidebar-collapsed",
      "true",
    );

    cy.get('[data-cy="sidebar-collapse-toggle"]').click();
    cy.get("[data-sidebar-collapsed]").should(
      "have.attr",
      "data-sidebar-collapsed",
      "false",
    );
    cy.get("aside").contains("Dashboard").should("be.visible");
  });

  it("mobile: collapse toggle is hidden", () => {
    cy.viewport(375, 812);
    visitDashboardAuthenticated();

    cy.get('[data-cy="sidebar-collapse-toggle"]').should("not.be.visible");
  });
});
