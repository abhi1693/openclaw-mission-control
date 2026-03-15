/// <reference types="cypress" />

import { stubAuth } from "../support/intercepts";

describe("Organizations (PR #61)", () => {
  const apiBase = "**/api/v1";

  it("negative: signed-out user sees auth prompt when opening /organization", () => {
    cy.visit("/organization");
    cy.contains(/sign in to manage your organization|local authentication/i, {
      timeout: 30_000,
    }).should("be.visible");
  });

  it("positive: signed-in user can view /organization and sees correct invite permissions", () => {
    // Semantically important: role is "member" (not default "owner")
    // because invite button should be disabled for non-admins.
    stubAuth(apiBase, {
      org: { id: "org1", name: "Testing Org" },
      member: { role: "member", organization_id: "org1", user_id: "u1" },
    });

    cy.intercept("GET", `${apiBase}/organizations/me`, {
      statusCode: 200,
      body: { id: "org1", name: "Testing Org" },
    }).as("orgMe");

    cy.intercept("GET", `${apiBase}/organizations/me/members*`, {
      statusCode: 200,
      body: {
        items: [
          {
            id: "membership-1",
            user_id: "u1",
            role: "member",
            user: {
              id: "u1",
              email: "local@example.com",
              name: "Local User",
              preferred_name: "Local User",
            },
          },
        ],
      },
    }).as("orgMembers");

    cy.intercept("GET", `${apiBase}/boards*`, {
      statusCode: 200,
      body: { items: [] },
    }).as("boardsList");

    cy.loginWithLocalAuth();
    cy.visit("/organization");
    cy.waitForAppLoaded();
    cy.contains(/members\s*&\s*invites/i).should("be.visible");
    cy.contains("button", /invite member/i)
      .should("be.visible")
      .should("be.disabled")
      .and("have.attr", "title")
      .and("match", /only organization admins can invite/i);
  });
});
