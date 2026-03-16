describe("Local auth login", () => {
  it("user with local auth token can access protected route", () => {
    cy.intercept("GET", "**/api/v1/users/me*", {
      statusCode: 200,
      body: {
        id: "u1",
        clerk_user_id: "local-auth-user",
        email: "local@example.com",
        name: "Local User",
        preferred_name: "Local User",
        timezone: "UTC",
      },
    }).as("usersMe");

    cy.intercept("GET", "**/api/v1/organizations/me/list*", {
      statusCode: 200,
      body: [
        {
          id: "org1",
          name: "Testing Org",
          is_active: true,
          role: "owner",
        },
      ],
    }).as("orgsList");

    cy.intercept("GET", "**/api/v1/organizations/me/member*", {
      statusCode: 200,
      body: { organization_id: "org1", role: "owner" },
    }).as("orgMeMember");

    cy.intercept("GET", "**/api/v1/boards*", {
      statusCode: 200,
      body: {
        items: [{ id: "b1", name: "Testing", updated_at: "2026-02-07T00:00:00Z" }],
      },
    }).as("boardsList");

    cy.intercept("GET", "**/api/v1/boards/b1/snapshot*", {
      statusCode: 200,
      body: { tasks: [], agents: [], approvals: [], chat_messages: [] },
    }).as("boardSnapshot");

    cy.loginWithLocalAuth();
    cy.visit("/activity");
    cy.waitForAppLoaded();
    cy.contains(/live feed/i).should("be.visible");
  });
});
