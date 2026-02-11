/// <reference types="cypress" />

describe("/activity feed", () => {
  const apiBase = "**/api/v1";
  const email = Cypress.env("CLERK_TEST_EMAIL") || "jane+clerk_test@example.com";

  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    // Clerk's Cypress helpers perform async work inside `cy.then()`.
    // CI can be slow enough that the default 4s command timeout flakes.
    Cypress.config("defaultCommandTimeout", 20_000);
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  function stubStreamEmpty() {
    cy.intercept(
      "GET",
      `${apiBase}/activity/task-comments/stream*`,
      {
        statusCode: 200,
        headers: {
          "content-type": "text/event-stream",
        },
        body: "",
      },
    ).as("activityStream");
  }

  function assertSignedInAndLanded() {
    cy.contains(/live feed/i, { timeout: 30_000 }).should("be.visible");
  }

  it("auth negative: signed-out user cannot access /activity", () => {
    // Story: signed-out user tries to visit /activity and is redirected to sign-in.
    cy.visit("/activity");
    cy.location("pathname", { timeout: 20_000 }).should("match", /\/sign-in/);
  });

  it("happy path: renders task comment cards", () => {
    cy.intercept("GET", `${apiBase}/activity/task-comments*`, {
      statusCode: 200,
      body: {
        items: [
          {
            id: "c1",
            message: "Hello world",
            agent_name: "Kunal",
            agent_role: "QA 2",
            board_id: "b1",
            board_name: "Testing",
            task_id: "t1",
            task_title: "CI hardening",
            created_at: "2026-02-07T00:00:00Z",
          },
        ],
      },
    }).as("activityList");

    stubStreamEmpty();

    // Story: user signs in, then visits /activity and sees the live feed.
    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    cy.visit("/activity");
    assertSignedInAndLanded();

    cy.wait("@activityList");
    cy.contains("CI hardening").should("be.visible");
    cy.contains("Hello world").should("be.visible");
  });

  it("empty state: shows waiting message when no items", () => {
    cy.intercept("GET", `${apiBase}/activity/task-comments*`, {
      statusCode: 200,
      body: { items: [] },
    }).as("activityList");

    stubStreamEmpty();

    // Story: user signs in, then visits /activity and sees an empty-state message.
    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    cy.visit("/activity");
    assertSignedInAndLanded();

    cy.wait("@activityList");
    cy.contains(/waiting for new comments/i).should("be.visible");
  });

  it("error state: shows failure UI when API errors", () => {
    cy.intercept("GET", `${apiBase}/activity/task-comments*`, {
      statusCode: 500,
      body: { detail: "boom" },
    }).as("activityList");

    stubStreamEmpty();

    // Story: user signs in, then visits /activity; API fails and user sees an error.
    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    cy.visit("/activity");
    assertSignedInAndLanded();

    cy.wait("@activityList");
    cy.contains(/unable to load feed|boom/i).should("be.visible");
  });
});
