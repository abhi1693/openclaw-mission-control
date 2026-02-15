/// <reference types="cypress" />

// Clerk/Next.js occasionally triggers a hydration mismatch on auth routes in CI.
// This is non-deterministic UI noise for these tests; ignore it so assertions can proceed.
Cypress.on("uncaught:exception", (err) => {
  if (err.message?.includes("Hydration failed")) {
    return false;
  }
  return true;
});

describe("Skill packs", () => {
  const apiBase = "**/api/v1";
  const email = Cypress.env("CLERK_TEST_EMAIL") || "jane+clerk_test@example.com";

  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 20_000);

    cy.intercept("GET", "**/healthz", {
      statusCode: 200,
      body: { ok: true },
    }).as("healthz");

    cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
      statusCode: 200,
      body: { organization_id: "org1", role: "owner" },
    }).as("orgMeMember");
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  it("can sync a pack and surface warnings", () => {
    cy.intercept("GET", `${apiBase}/skills/packs*`, {
      statusCode: 200,
      body: [
        {
          id: "p1",
          name: "OpenClaw Skills",
          description: "Test pack",
          source_url: "https://github.com/openclaw/skills",
          branch: "main",
          skill_count: 12,
          updated_at: "2026-02-14T00:00:00Z",
          created_at: "2026-02-10T00:00:00Z",
        },
      ],
    }).as("packsList");

    cy.intercept("POST", `${apiBase}/skills/packs/p1/sync*`, {
      statusCode: 200,
      body: {
        warnings: ["1 skill skipped (missing SKILL.md)"],
      },
    }).as("packSync");

    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    cy.visit("/skills/packs");
    cy.waitForAppLoaded();

    cy.wait("@packsList", { timeout: 20_000 });
    cy.contains(/openclaw skills/i).should("be.visible");

    cy.contains("button", /^sync$/i).click();
    cy.wait("@packSync", { timeout: 20_000 });

    cy.contains(/skill skipped/i).should("be.visible");
  });
});
