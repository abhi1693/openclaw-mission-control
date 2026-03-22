import { defineConfig } from "cypress";

export default defineConfig({
  e2e: {
    baseUrl: "http://localhost:3000",
    specPattern: "cypress/e2e-integration/**/*.cy.ts",
    supportFile: "cypress/support/e2e.ts",
    defaultCommandTimeout: 30_000,
    retries: {
      runMode: 2,
      openMode: 0,
    },
    env: {
      API_BASE: "http://localhost:8001",
      AUTH_TOKEN:
        "e2e-local-auth-token-0123456789-0123456789-0123456789x",
    },
  },
});
