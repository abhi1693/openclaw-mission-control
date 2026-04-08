/// <reference types="cypress" />

// API_BASE is a real URL host (e.g. "http://localhost:8001"), NOT a Cypress
// glob pattern like "**/api/v1". It does NOT include the /api/v1 prefix.
const apiBase = (): string => Cypress.env("API_BASE") as string;
const authToken = (): string => Cypress.env("AUTH_TOKEN") as string;

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${authToken()}` };
}

/**
 * Thin API client for integration E2E test setup and verification.
 *
 * Setup helpers create prerequisites (boards, tasks).
 * Verification helpers confirm persisted state after UI actions.
 *
 * The behavior under test should always go through the UI.
 */
export const api = {
  // ── Setup helpers ──────────────────────────────────────────────

  createBoard(input: { name: string; slug: string; description: string; board_type?: string }) {
    return cy.request({
      method: "POST",
      url: `${apiBase()}/api/v1/boards`,
      headers: authHeaders(),
      body: input,
    });
  },

  createTask(boardId: string, input: { title: string; description?: string; priority?: string }) {
    return cy.request({
      method: "POST",
      url: `${apiBase()}/api/v1/boards/${boardId}/tasks`,
      headers: authHeaders(),
      body: input,
    });
  },

  // ── Verification helpers ───────────────────────────────────────

  getBoards() {
    return cy.request({
      method: "GET",
      url: `${apiBase()}/api/v1/boards`,
      headers: authHeaders(),
    });
  },

  getBoard(boardId: string) {
    return cy.request({
      method: "GET",
      url: `${apiBase()}/api/v1/boards/${boardId}/snapshot`,
      headers: authHeaders(),
    });
  },

  getTasks(boardId: string) {
    return cy.request({
      method: "GET",
      url: `${apiBase()}/api/v1/boards/${boardId}/snapshot`,
      headers: authHeaders(),
    });
  },
};
