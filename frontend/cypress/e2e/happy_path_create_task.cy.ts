// Happy-path UI journey that remains CI-stable even when the backend is not running.
// Notes:
// - This spec stubs all backend HTTP/SSE calls the board page makes.
// - Auth uses `cy.loginWithClerkOtp()` (requires CYPRESS_CLERK_TEST_EMAIL/OTP or defaults).

describe("Happy path: create a task", () => {
  const apiBase = "**/api/v1";

  const now = "2026-02-11T00:00:00.000Z";
  const boardId = "b1";

  function stubEventStream(pathGlob: string) {
    cy.intercept("GET", pathGlob, {
      statusCode: 200,
      headers: { "content-type": "text/event-stream" },
      body: "",
    });
  }

  function stubBoardSnapshotEmpty() {
    cy.intercept("GET", `${apiBase}/boards/${boardId}/snapshot`, {
      statusCode: 200,
      body: {
        board: {
          id: boardId,
          organization_id: "org1",
          name: "Test Board",
          slug: "test-board",
          gateway_id: null,
          board_group_id: null,
          board_type: "goal",
          objective: null,
          success_metrics: null,
          target_date: null,
          goal_confirmed: true,
          goal_source: "test",
          created_at: now,
          updated_at: now,
        },
        tasks: [],
        agents: [],
        approvals: [],
        chat_messages: [],
        pending_approvals_count: 0,
      },
    }).as("boardSnapshot");

    // The board page also attempts to load a board-group snapshot; in CI E2E we don't run the backend,
    // so stub this to a deterministic empty response.
    cy.intercept("GET", `${apiBase}/boards/${boardId}/group-snapshot*`, {
      statusCode: 200,
      body: { boards: [] },
    }).as("groupSnapshot");
  }

  function stubMembershipWriteAccess() {
    cy.intercept("GET", `${apiBase}/organizations/me/member`, {
      statusCode: 200,
      body: {
        id: "m1",
        organization_id: "org1",
        user_id: "u1",
        role: "owner",
        all_boards_read: true,
        all_boards_write: true,
        created_at: now,
        updated_at: now,
        user: null,
        board_access: [],
      },
    }).as("membership");
  }

  it("signed-in user can create a task from the board page", () => {
    // Streams: the board page connects to multiple SSE endpoints.
    stubEventStream(`${apiBase}/boards/${boardId}/tasks/stream*`);
    stubEventStream(`${apiBase}/boards/${boardId}/approvals/stream*`);
    stubEventStream(`${apiBase}/boards/${boardId}/memory/stream*`);
    stubEventStream(`${apiBase}/agents/stream*`);
    stubEventStream(`${apiBase}/activity/task-comments/stream*`);

    stubMembershipWriteAccess();
    stubBoardSnapshotEmpty();

    const createdTask = {
      id: "t1",
      board_id: boardId,
      created_by_user_id: null,
      assigned_agent_id: null,
      title: "First E2E task",
      description: null,
      status: "inbox",
      priority: "medium",
      due_at: null,
      depends_on_task_ids: [],
      blocked_by_task_ids: [],
      is_blocked: false,
      in_progress_at: null,
      created_at: now,
      updated_at: now,
    };

    cy.intercept("POST", `${apiBase}/boards/${boardId}/tasks`, {
      statusCode: 200,
      body: createdTask,
    }).as("createTask");

    // Auth: prefer the repo's deterministic OTP-based helper (avoids driving Clerk iframes/modals).
    cy.loginWithClerkOtp();

    cy.visit(`/boards/${boardId}`);
    cy.wait("@membership");
    cy.wait("@boardSnapshot");
    cy.wait("@groupSnapshot");

    // Use list view for simpler assertions.
    cy.contains("button", "List").click();

    // Prefer explicit aria-label selector (defined in boards page).
    cy.get('button[aria-label="New task"]').click();
    cy.get("input").first().type("First E2E task");
    cy.contains("button", /create task/i).click();

    cy.wait("@createTask");

    // Assert new task shows up in UI.
    cy.contains("First E2E task").should("be.visible");
  });
});
