/// <reference types="cypress" />

const apiBase = "**/api/v1";
const email = "local-auth-user@example.com";
const BOARD_PATH = "/boards/b1";

function stubCommonAuth() {
  cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
    statusCode: 200,
    body: {
      id: "m1",
      organization_id: "o1",
      user_id: "u1",
      role: "owner",
      all_boards_read: true,
      all_boards_write: true,
      created_at: "2026-02-11T00:00:00Z",
      updated_at: "2026-02-11T00:00:00Z",
      board_access: [{ board_id: "b1", can_read: true, can_write: true }],
    },
  }).as("membership");

  cy.intercept("GET", `${apiBase}/users/me*`, {
    statusCode: 200,
    body: {
      id: "u1",
      clerk_user_id: "clerk_u1",
      email,
      name: "Jane Test",
      preferred_name: "Jane",
      timezone: "America/New_York",
      is_super_admin: false,
    },
  }).as("me");

  cy.intercept("GET", `${apiBase}/organizations/me/list*`, {
    statusCode: 200,
    body: [{ id: "o1", name: "Personal", role: "owner", is_active: true }],
  }).as("organizations");
}

function stubBoardsIndex() {
  cy.intercept("GET", `${apiBase}/boards*`, {
    statusCode: 200,
    body: {
      items: [
        {
          id: "b1",
          name: "Demo Board",
          slug: "demo-board",
          description: "Demo",
          gateway_id: "g1",
          board_group_id: null,
          board_type: "general",
          objective: null,
          success_metrics: null,
          target_date: null,
          goal_confirmed: true,
          goal_source: "test",
          organization_id: "o1",
          created_at: "2026-02-11T00:00:00Z",
          updated_at: "2026-02-11T00:00:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
    },
  }).as("boards");

  cy.intercept("GET", `${apiBase}/board-groups*`, {
    statusCode: 200,
    body: { items: [], total: 0, limit: 200, offset: 0 },
  }).as("boardGroups");
}

function stubBoardPage() {
  const emptySse = {
    statusCode: 200,
    headers: { "content-type": "text/event-stream" },
    body: "",
  };

  cy.intercept("GET", `${apiBase}/boards/*/tasks/stream*`, emptySse);
  cy.intercept("GET", `${apiBase}/boards/*/approvals/stream*`, emptySse);
  cy.intercept("GET", `${apiBase}/boards/*/memory/stream*`, emptySse);
  cy.intercept("GET", `${apiBase}/agents/stream*`, emptySse);

  cy.intercept("GET", `${apiBase}/boards/b1/snapshot*`, {
    statusCode: 200,
    body: {
      board: {
        id: "b1",
        name: "Demo Board",
        slug: "demo-board",
        description: "Demo",
        gateway_id: "g1",
        board_group_id: null,
        board_type: "general",
        objective: null,
        success_metrics: null,
        target_date: null,
        goal_confirmed: true,
        goal_source: "test",
        organization_id: "o1",
        created_at: "2026-02-11T00:00:00Z",
        updated_at: "2026-02-11T00:00:00Z",
      },
      tasks: [
        {
          id: "t1",
          board_id: "b1",
          title: "Inbox task",
          description: "",
          status: "inbox",
          priority: "medium",
          due_at: null,
          assigned_agent_id: null,
          depends_on_task_ids: [],
          created_by_user_id: null,
          in_progress_at: null,
          created_at: "2026-02-11T00:00:00Z",
          updated_at: "2026-02-11T00:00:00Z",
          blocked_by_task_ids: [],
          is_blocked: false,
          assignee: null,
          approvals_count: 0,
          approvals_pending_count: 0,
        },
      ],
      agents: [],
      approvals: [],
      chat_messages: [],
      pending_approvals_count: 0,
    },
  }).as("snapshot");

  cy.intercept("GET", `${apiBase}/boards/b1/group-snapshot*`, {
    statusCode: 200,
    body: { group: null, boards: [] },
  }).as("groupSnapshot");

  cy.intercept("GET", `${apiBase}/tags*`, {
    statusCode: 200,
    body: { items: [], total: 0, limit: 200, offset: 0 },
  }).as("tags");

  cy.intercept("GET", `${apiBase}/organizations/me/custom-fields*`, {
    statusCode: 200,
    body: [],
  }).as("customFields");
}

function assertNoHorizontalOverflow(label: string) {
  cy.document().then((doc) => {
    const htmlOverflow =
      doc.documentElement.scrollWidth - doc.documentElement.clientWidth;
    const bodyOverflow = doc.body.scrollWidth - doc.body.clientWidth;

    expect(htmlOverflow, `${label}: html horizontal overflow px`).to.be.lte(1);
    expect(bodyOverflow, `${label}: body horizontal overflow px`).to.be.lte(1);
  });
}

describe("mobile overflow + navigation CI gate", () => {
  beforeEach(() => {
    cy.viewport(390, 844);
    stubCommonAuth();
    stubBoardsIndex();
    stubBoardPage();
    cy.loginWithLocalAuth();
  });

  it("keeps boards list mobile-safe and board navigation usable", () => {
    cy.visit("/boards");
    cy.waitForAppLoaded();
    cy.wait(["@membership", "@me", "@organizations", "@boards", "@boardGroups"]);

    cy.contains("Demo Board").should("be.visible");
    cy.contains("a", /^Boards$/).should("be.visible");
    assertNoHorizontalOverflow("/boards");

    cy.contains('a[href="/boards/b1"]', "Demo Board")
      .should("be.visible")
      .click();

    cy.url().should("include", BOARD_PATH);
    cy.wait(["@snapshot", "@groupSnapshot", "@tags", "@customFields"]);

    cy.contains("h1", "Demo Board").should("exist");
    cy.contains("Inbox task").should("exist");

    cy.get("main").scrollIntoView();
    cy.get('button[aria-label="New task"]').should("exist");
    assertNoHorizontalOverflow("/boards/:id");
  });
});
