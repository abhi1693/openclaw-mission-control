/// <reference types="cypress" />

import { buildBoard, buildBoardSnapshot } from "../support/factories";
import { stubAuth, stubBoards, stubEmptySSEStreams } from "../support/intercepts";

describe("/activity feed", () => {
  const apiBase = "**/api/v1";

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  function stubBoardBootstrap() {
    const board = buildBoard({ id: "b1", name: "Testing" });
    stubAuth(apiBase);
    stubBoards(apiBase, { boards: [board] });

    cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
      statusCode: 200,
      body: buildBoardSnapshot(board, {
        tasks: [{ id: "t1", title: "CI hardening" }],
      }),
    }).as("boardSnapshot");
  }

  function assertSignedInAndLanded() {
    cy.waitForAppLoaded();
    cy.contains(/live feed/i).should("be.visible");
  }

  it("auth negative: signed-out user sees auth prompt", () => {
    cy.visit("/activity");
    cy.contains(/sign in to view the feed|local authentication/i, {
      timeout: 20_000,
    }).should("be.visible");
  });

  it("happy path: renders task comment cards", () => {
    stubBoardBootstrap();

    cy.intercept("GET", "**/api/v1/activity**", {
      statusCode: 200,
      body: {
        items: [
          {
            id: "e1",
            event_type: "task.comment",
            message: "Hello world",
            agent_id: null,
            agent_name: "Kunal",
            created_at: "2026-02-07T00:00:00Z",
            task_id: "t1",
            task_title: "CI hardening",
            agent_role: "QA 2",
          },
        ],
      },
    }).as("activityList");

    stubEmptySSEStreams(apiBase);

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    assertSignedInAndLanded();
    cy.wait("@activityList", { timeout: 20_000 });

    cy.contains(/ci hardening|unknown task/i).should("be.visible");
    cy.contains(/hello world/i).should("be.visible");
  });

  it("empty state: shows waiting message when no items", () => {
    stubBoardBootstrap();

    cy.intercept("GET", "**/api/v1/activity**", {
      statusCode: 200,
      body: { items: [] },
    }).as("activityList");

    stubEmptySSEStreams(apiBase);

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    assertSignedInAndLanded();
    cy.wait("@activityList", { timeout: 20_000 });

    cy.contains(/waiting for new activity/i).should("be.visible");
  });

  it("error state: shows failure UI when API errors", () => {
    stubBoardBootstrap();

    cy.intercept("GET", "**/api/v1/activity**", {
      statusCode: 500,
      body: { detail: "boom" },
    }).as("activityList");

    stubEmptySSEStreams(apiBase);

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    assertSignedInAndLanded();
    cy.wait("@activityList", { timeout: 20_000 });

    cy.contains(/unable to load activity feed|unable to load feed|boom/i).should(
      "be.visible",
    );
  });
});
