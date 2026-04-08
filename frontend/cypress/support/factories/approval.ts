import { nextId } from "./reset";

export interface ApprovalEntity {
  id: string;
  board_id: string;
  action_type: string;
  status: string;
  confidence: number;
  created_at: string;
  task_id: string | null;
  task_ids: string[];
  payload: Record<string, unknown> | null;
}

export function buildApproval(overrides?: Partial<ApprovalEntity>): ApprovalEntity {
  const id = overrides?.id ?? nextId("approval");
  return {
    id,
    board_id: "board-1",
    action_type: "task.closeout",
    status: "pending",
    confidence: 92,
    created_at: "2026-01-01T00:00:00.000Z",
    task_id: null,
    task_ids: [],
    payload: null,
    ...overrides,
  };
}
