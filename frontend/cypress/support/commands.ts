/// <reference types="cypress" />

const APP_LOAD_TIMEOUT_MS = 30_000;
const LOCAL_AUTH_STORAGE_KEY = "mc_local_auth_token";
const DEFAULT_LOCAL_AUTH_TOKEN =
  "cypress-local-auth-token-0123456789-0123456789-0123456789x";

Cypress.Commands.add("waitForAppLoaded", () => {
  cy.get("[data-cy='route-loader']", {
    timeout: APP_LOAD_TIMEOUT_MS,
  }).should("not.exist");

  cy.get("[data-cy='global-loader']", {
    timeout: APP_LOAD_TIMEOUT_MS,
  }).should("have.attr", "aria-hidden", "true");
});

Cypress.Commands.add("loginWithLocalAuth", (token = DEFAULT_LOCAL_AUTH_TOKEN) => {
  cy.visit("/", {
    onBeforeLoad(win) {
      win.sessionStorage.setItem(LOCAL_AUTH_STORAGE_KEY, token);
    },
  });
});

Cypress.Commands.add("logoutLocalAuth", () => {
  cy.visit("/", {
    onBeforeLoad(win) {
      win.sessionStorage.removeItem(LOCAL_AUTH_STORAGE_KEY);
    },
  });
});

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Cypress {
    interface Chainable {
      /**
       * Waits for route-level and global app loaders to disappear.
       */
      waitForAppLoaded(): Chainable<void>;

      /**
       * Seeds session storage with a local auth token for local-auth mode.
       */
      loginWithLocalAuth(token?: string): Chainable<void>;

      /**
       * Clears local auth token from session storage.
       */
      logoutLocalAuth(): Chainable<void>;
    }
  }
}

export {};
