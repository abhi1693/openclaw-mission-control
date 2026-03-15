import { nextId } from "./reset";

export interface BoardEntity {
  id: string;
  name: string;
  slug: string;
  description: string;
  gateway_id: string | null;
  board_group_id: string | null;
  board_type: string;
  objective: string | null;
  success_metrics: null;
  target_date: string | null;
  goal_confirmed: boolean;
  goal_source: string | null;
  organization_id: string;
  created_at: string;
  updated_at: string;
}

export function buildBoard(overrides?: Partial<BoardEntity>): BoardEntity {
  const id = overrides?.id ?? nextId("board");
  return {
    id,
    name: `Test Board ${id}`,
    slug: `test-board-${id}`,
    description: "",
    gateway_id: null,
    board_group_id: null,
    board_type: "general",
    objective: null,
    success_metrics: null,
    target_date: null,
    goal_confirmed: true,
    goal_source: null,
    organization_id: "org-1",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

export interface CreateBoardInput {
  name: string;
  slug: string;
  description: string;
  board_type?: string;
  gateway_id?: string | null;
  objective?: string | null;
  goal_confirmed?: boolean;
}

export function buildCreateBoardInput(overrides?: Partial<CreateBoardInput>): CreateBoardInput {
  const slug = overrides?.slug ?? `board-${Date.now()}`;
  return {
    name: overrides?.name ?? `New Board ${slug}`,
    slug,
    description: "",
    board_type: "general",
    ...overrides,
  };
}

export interface BoardSnapshotEntity {
  board: BoardEntity;
  tasks: unknown[];
  agents: unknown[];
  approvals: unknown[];
  chat_messages: unknown[];
  pending_approvals_count?: number;
}

export function buildBoardSnapshot(
  board: BoardEntity,
  options?: { tasks?: unknown[] },
): BoardSnapshotEntity {
  return {
    board,
    tasks: options?.tasks ?? [],
    agents: [],
    approvals: [],
    chat_messages: [],
    pending_approvals_count: 0,
  };
}
