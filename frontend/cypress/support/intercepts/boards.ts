import { buildBoard } from "../factories";
import type { BoardEntity } from "../factories";

interface StubBoardsOptions {
  boards?: BoardEntity[];
  groups?: Array<Record<string, unknown>>;
}

export function stubBoards(apiBase: string, options: StubBoardsOptions = {}): void {
  const boards = options.boards ?? [buildBoard({ id: "board-1", name: "Testing" })];
  const groups = options.groups ?? [];

  cy.intercept("GET", `${apiBase}/boards*`, {
    statusCode: 200,
    body: {
      items: boards,
      total: boards.length,
      limit: 200,
      offset: 0,
    },
  }).as("boardsList");

  cy.intercept("GET", `${apiBase}/board-groups*`, {
    statusCode: 200,
    body: {
      items: groups,
      total: groups.length,
      limit: 200,
      offset: 0,
    },
  }).as("boardGroupsList");
}
