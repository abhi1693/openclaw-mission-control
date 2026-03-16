/// <reference types="cypress" />

type CommonPageTestHooksOptions = {
  timeoutMs?: number;
  orgMemberRole?: string;
  organizationId?: string;
  organizationName?: string;
  userId?: string;
  userEmail?: string;
  userName?: string;
};

export function setupCommonPageTestHooks(
  apiBase: string,
  options: CommonPageTestHooksOptions = {},
): void {
  const {
    timeoutMs = 20_000,
    orgMemberRole = "owner",
    organizationId = "org1",
    organizationName = "Testing Org",
    userId = "u1",
    userEmail = "local-auth-user@example.com",
    userName = "Local User",
  } = options;
  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", timeoutMs);

    cy.intercept("GET", "**/healthz", {
      statusCode: 200,
      body: { ok: true },
    }).as("healthz");

    cy.intercept("GET", `${apiBase}/users/me*`, {
      statusCode: 200,
      body: {
        id: userId,
        clerk_user_id: "local-auth-user",
        email: userEmail,
        name: userName,
        preferred_name: userName,
        timezone: "UTC",
      },
    }).as("usersMe");

    cy.intercept("GET", `${apiBase}/organizations/me/list*`, {
      statusCode: 200,
      body: [
        {
          id: organizationId,
          name: organizationName,
          is_active: true,
          role: orgMemberRole,
        },
      ],
    }).as("organizationsList");

    cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
      statusCode: 200,
      body: {
        id: "membership-1",
        organization_id: organizationId,
        user_id: userId,
        role: orgMemberRole,
        all_boards_read: true,
        all_boards_write: true,
        board_access: [],
      },
    }).as("orgMeMember");
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });
}
