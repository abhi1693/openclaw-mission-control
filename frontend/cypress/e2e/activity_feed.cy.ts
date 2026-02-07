/// <reference types="cypress" />

describe("/activity feed", () => {
  const apiBase = "**/api/v1";

  const loginEmail = "jane+clerk_test@example.com";
  const loginOtp = "424242";

  function signInViaClerk() {
    // Triggers our Clerk modal.
    cy.get('[data-testid="sign-in-trigger"]').click();

    // Clerk modal: email/identifier step.
    // (Selectors may need adjustment if Clerk changes markup; we keep them broad.)
    cy.get('input[name="identifier"], input[type="email"]').first().type(loginEmail);
    cy.contains('button', /continue|sign in/i).click();

    // OTP step.
    cy.get('input[name="code"], input[inputmode="numeric"]').first().type(loginOtp);
    cy.contains('button', /verify|continue|sign in/i).click();

    // Wait for the app to show signed-in UI.
    cy.contains(/live feed/i).should("be.visible");
  }

  function stubStreamEmpty() {
    // Return a minimal SSE response that ends immediately.
    cy.intercept("GET", `${apiBase}/activity/task-comments/stream*`, {
      statusCode: 200,
      headers: {
        "content-type": "text/event-stream",
      },
      body: "",
    }).as("activityStream");
  }

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
          {
            id: "c2",
            message: "Second comment",
            agent_name: "Riya",
            agent_role: "QA",
            board_id: "b1",
            board_name: "Testing",
            task_id: "t2",
            task_title: "Coverage policy",
            created_at: "2026-02-07T00:01:00Z",
          },
        ],
      },
    }).as("activityList");

    stubStreamEmpty();

    cy.visit("/activity", {
      onBeforeLoad(win: Window) {
        win.localStorage.clear();
      },
    });

    // Signed-out state should show our sign-in trigger.
    cy.contains(/sign in to view the feed/i).should("be.visible");
    signInViaClerk();

    cy.wait("@activityList");

    cy.contains(/live feed/i).should("be.visible");
    cy.contains("CI hardening").should("be.visible");
    cy.contains("Coverage policy").should("be.visible");
    cy.contains("Hello world").should("be.visible");
  });

  it("empty state: shows waiting message when no items", () => {
    cy.intercept("GET", `${apiBase}/activity/task-comments*`, {
      statusCode: 200,
      body: { items: [] },
    }).as("activityList");

    stubStreamEmpty();

    cy.visit("/activity");
    cy.contains(/sign in to view the feed/i).should("be.visible");
    signInViaClerk();

    cy.wait("@activityList");

    cy.contains(/waiting for new comments/i).should("be.visible");
  });

  it("error state: shows failure UI when API errors", () => {
    cy.intercept("GET", `${apiBase}/activity/task-comments*`, {
      statusCode: 500,
      body: { detail: "boom" },
    }).as("activityList");

    stubStreamEmpty();

    cy.visit("/activity");
    cy.contains(/sign in to view the feed/i).should("be.visible");
    signInViaClerk();

    cy.wait("@activityList");

    // UI uses query.error.message or fallback.
    cy.contains(/unable to load feed|boom/i).should("be.visible");
  });
});
