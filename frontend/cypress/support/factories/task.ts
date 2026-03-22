import { nextId } from "./reset";

export interface TaskEntity {
  id: string;
  board_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  due_at: string | null;
  assigned_agent_id: string | null;
  depends_on_task_ids: string[];
  created_by_user_id: string | null;
  in_progress_at: string | null;
  created_at: string;
  updated_at: string;
  blocked_by_task_ids: string[];
  is_blocked: boolean;
  assignee: null;
  approvals_count: number;
  approvals_pending_count: number;
}

export function buildTask(overrides?: Partial<TaskEntity>): TaskEntity {
  const id = overrides?.id ?? nextId("task");
  return {
    id,
    board_id: "board-1",
    title: `Test Task ${id}`,
    description: "",
    status: "inbox",
    priority: "medium",
    due_at: null,
    assigned_agent_id: null,
    depends_on_task_ids: [],
    created_by_user_id: null,
    in_progress_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    blocked_by_task_ids: [],
    is_blocked: false,
    assignee: null,
    approvals_count: 0,
    approvals_pending_count: 0,
    ...overrides,
  };
}

export interface CreateTaskInput {
  title: string;
  description?: string;
  priority?: string;
  status?: string;
}

export function buildCreateTaskInput(overrides?: Partial<CreateTaskInput>): CreateTaskInput {
  return {
    title: `New Task ${Date.now()}`,
    ...overrides,
  };
}

export interface TaskCommentEntity {
  id: string;
  task_id: string;
  body: string;
  author_type: string;
  created_at: string;
}

export function buildTaskComment(overrides?: Partial<TaskCommentEntity>): TaskCommentEntity {
  const id = overrides?.id ?? nextId("comment");
  return {
    id,
    task_id: "task-1",
    body: "Test comment",
    author_type: "user",
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}
