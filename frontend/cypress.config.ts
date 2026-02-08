import { defineConfig } from "cypress";
import { clerkSetup } from "@clerk/testing/cypress";

export default defineConfig({
  env: {
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:
      process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    // Optional overrides.
    CLERK_ORIGIN: process.env.CYPRESS_CLERK_ORIGIN,
    CLERK_TEST_EMAIL: process.env.CYPRESS_CLERK_TEST_EMAIL,
    CLERK_TEST_OTP: process.env.CYPRESS_CLERK_TEST_OTP,
  },
  e2e: {
    baseUrl: "http://localhost:3000",
    specPattern: "cypress/e2e/**/*.cy.{js,jsx,ts,tsx}",
    supportFile: "cypress/support/e2e.ts",
    setupNodeEvents(on, config) {
      return clerkSetup({ config });
    },
  },
});
