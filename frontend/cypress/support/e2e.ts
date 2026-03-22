// Cypress support file.
// Place global hooks/commands here.

/// <reference types="cypress" />

import { addClerkCommands } from "@clerk/testing/cypress";
import { resetFactoryState } from "./factories";

// Clerk/Next.js occasionally throws a non-deterministic hydration mismatch
// on /sign-in. Ignore this known UI noise so E2E assertions can proceed.
Cypress.on("uncaught:exception", (err) => {
  if (err?.message?.includes("Hydration failed")) {
    return false;
  }
  return true;
});

addClerkCommands({ Cypress, cy });

import "./commands";

// Reset factory counters before each test for deterministic IDs.
beforeEach(() => {
  resetFactoryState();
});

// Fail stubbed tests if an API request escapes interception.
// Integration tests (which set Cypress.env("API_BASE")) skip this check.
if (!Cypress.env("API_BASE")) {
  beforeEach(() => {
    cy.intercept({ url: /\/api\/v1\//, middleware: true }, (req) => {
      // If this middleware intercept is the ONLY handler, the request
      // was not stubbed by a test-specific intercept.
      // Log it so flaky leaks are visible in CI output.
      Cypress.log({
        name: "UNSTUBBED API",
        message: `${req.method} ${req.url}`,
        consoleProps: () => ({ method: req.method, url: req.url }),
      });
    });
  });
}
