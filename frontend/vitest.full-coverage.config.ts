import path from "node:path";

import { defineConfig } from "vitest/config";

// Broader coverage config used for gap analysis.
// - Does NOT enforce 100% thresholds.
// - Includes most source files (excluding generated artifacts and types).
// Keep the default vitest.config.ts as the scoped coverage gate.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    globals: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      reportsDirectory: "./coverage-full",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "**/*.d.ts",
        "src/**/__generated__/**",
        "src/**/generated/**",
      ],
      thresholds: {
        lines: 0,
        statements: 0,
        functions: 0,
        branches: 0,
      },
    },
  },
});
