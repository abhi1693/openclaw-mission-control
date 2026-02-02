// NOTE:
// Orval-generated hooks already return strongly-typed arrays for most endpoints.
// We keep only the Activity type + a tiny normalizer here because Activity is not
// currently generated as a model.

export type Activity = {
  id?: number;
  actor_employee_id?: number | null;
  entity_type?: string;
  entity_id?: number | null;
  verb?: string;
  payload?: unknown;
  created_at?: string;
};

export function normalizeActivities(data: unknown): Activity[] {
  if (Array.isArray(data)) return data as Activity[];
  if (data && typeof data === "object" && "data" in data) {
    const maybe = (data as { data?: unknown }).data;
    if (Array.isArray(maybe)) return maybe as Activity[];
  }
  return [];
}
