/**
 * Generated manually to match backend workflow summary payload.
 */
export interface WorkflowRunSummary {
  id: string;
  title: string;
  status:
    | "pending"
    | "running"
    | "blocked"
    | "waiting_human"
    | "waiting_approval"
    | "completed"
    | "failed"
    | "canceled";
  current_step_key?: string | null;
  source_task_id?: string | null;
  waiting_step_count?: number;
  approval_step_count?: number;
  human_step_count?: number;
  created_at: string;
  updated_at: string;
}
