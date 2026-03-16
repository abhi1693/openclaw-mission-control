/// <reference types="cypress" />

import { setupCommonPageTestHooks } from "../support/testHooks";

describe("Skill packs", () => {
  const apiBase = "**/api/v1";

  setupCommonPageTestHooks(apiBase);

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

    cy.loginWithLocalAuth();
    cy.visit("/skills/packs");
    cy.waitForAppLoaded();

    cy.wait(["@usersMe", "@organizationsList", "@orgMeMember", "@packsList"], {
      timeout: 20_000,
    });
    cy.contains(/openclaw skills/i).should("be.visible");

    cy.contains("button", /^sync$/i).click();
    cy.wait("@packSync", { timeout: 20_000 });

    cy.contains(/skill skipped/i).should("be.visible");
  });
});
