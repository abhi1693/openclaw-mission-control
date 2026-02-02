"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";

import { useListProjectsProjectsGet } from "@/api/generated/projects/projects";
import { useListEmployeesEmployeesGet } from "@/api/generated/org/org";
import { useListTasksTasksGet, useUpdateTaskTasksTaskIdPatch } from "@/api/generated/work/work";

const STATUSES = ["backlog", "ready", "in_progress", "review", "blocked", "done"] as const;

export default function KanbanPage() {
  const projects = useListProjectsProjectsGet();
  const projectList = projects.data ?? [];

  const employees = useListEmployeesEmployeesGet();
  const employeeList = useMemo(() => employees.data ?? [], [employees.data]);

  const [projectId, setProjectId] = useState<string>("");
  const [assigneeId, setAssigneeId] = useState<string>("");
  const [live, setLive] = useState(false);

  const tasks = useListTasksTasksGet(
    {
      ...(projectId ? { project_id: Number(projectId) } : {}),
    },
    {
      query: {
        enabled: true,
        refetchInterval: live ? 5000 : false,
        refetchIntervalInBackground: false,
      },
    },
  );
  const taskList = useMemo(() => tasks.data ?? [], [tasks.data]);

  const updateTask = useUpdateTaskTasksTaskIdPatch({
    mutation: {
      onSuccess: () => tasks.refetch(),
    },
  });

  const employeeNameById = useMemo(() => {
    const m = new Map<number, string>();
    for (const e of employeeList) {
      if (e.id != null) m.set(e.id, e.name);
    }
    return m;
  }, [employeeList]);

  const filtered = useMemo(() => {
    return taskList.filter((t) => {
      if (assigneeId && String(t.assignee_employee_id ?? "") !== assigneeId) return false;
      return true;
    });
  }, [taskList, assigneeId]);

  const tasksByStatus = useMemo(() => {
    const map = new Map<(typeof STATUSES)[number], typeof filtered>();
    for (const s of STATUSES) map.set(s, []);
    for (const t of filtered) {
      const s = (t.status ?? "backlog") as (typeof STATUSES)[number];
      (map.get(s) ?? map.get("backlog"))?.push(t);
    }
    // stable sort inside each column
    for (const s of STATUSES) {
      const arr = map.get(s) ?? [];
      arr.sort((a, b) => String(a.id ?? 0).localeCompare(String(b.id ?? 0)));
    }
    return map;
  }, [filtered]);

  return (
    <main className="mx-auto max-w-screen-2xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Kanban</h1>
          <p className="mt-1 text-sm text-muted-foreground">Board view for tasks (quick triage + status moves).</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            tasks.refetch();
            projects.refetch();
            employees.refetch();
          }}
          disabled={tasks.isFetching || projects.isFetching || employees.isFetching}
        >
          Refresh
        </Button>
      </div>

      {tasks.error ? (
        <div className="mt-4 text-sm text-destructive">{(tasks.error as Error).message}</div>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Filters</CardTitle>
            <CardDescription>Scope the board.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">All projects</option>
              {projectList.map((p) => (
                <option key={p.id ?? p.name} value={p.id ?? ""}>
                  {p.name}
                </option>
              ))}
            </Select>

            <Select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
              <option value="">All assignees</option>
              {employeeList.map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>
                  {e.name}
                </option>
              ))}
            </Select>

            <div className="flex items-center justify-between gap-2 rounded-md border p-2 text-sm">
              <div>
                <div className="font-medium">Live updates</div>
                <div className="text-xs text-muted-foreground">Auto-refresh tasks every 5s on this page.</div>
              </div>
              <Button variant="outline" size="sm" onClick={() => setLive((v) => !v)}>
                {live ? "On" : "Off"}
              </Button>
            </div>

            <div className="text-xs text-muted-foreground">
              Showing {filtered.length} / {taskList.length} tasks
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4" style={{ gridTemplateColumns: `repeat(${STATUSES.length}, minmax(260px, 1fr))` }}>
        {STATUSES.map((status) => (
          <Card key={status} className="min-w-[260px]">
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-wide">{status.replaceAll("_", " ")}</CardTitle>
              <CardDescription>{tasksByStatus.get(status)?.length ?? 0} tasks</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {(tasksByStatus.get(status) ?? []).map((t) => (
                <div key={t.id ?? t.title} className="rounded-md border p-2 text-sm">
                  <div className="font-medium">{t.title}</div>
                  {t.description ? (
                    <div className="mt-1 text-xs text-muted-foreground line-clamp-3">{t.description}</div>
                  ) : null}
                  <div className="mt-2 text-xs text-muted-foreground">
                    #{t.id} · {t.project_id ? `proj ${t.project_id}` : "no project"}
                    {t.assignee_employee_id != null ? ` · assignee ${employeeNameById.get(t.assignee_employee_id) ?? t.assignee_employee_id}` : ""}
                  </div>

                  <div className="mt-2 flex gap-2">
                    <Select
                      value={t.status ?? "backlog"}
                      onChange={(e) =>
                        updateTask.mutate({
                          taskId: Number(t.id),
                          data: {
                            status: e.target.value,
                          },
                        })
                      }
                      disabled={!t.id || updateTask.isPending}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </Select>

                    <Button
                      variant="outline"
                      onClick={() => {
                        // quick move right
                        const idx = STATUSES.indexOf(status);
                        const next = STATUSES[Math.min(STATUSES.length - 1, idx + 1)];
                        if (!t.id) return;
                        updateTask.mutate({ taskId: Number(t.id), data: { status: next } });
                      }}
                      disabled={!t.id || updateTask.isPending}
                    >
                      →
                    </Button>
                  </div>
                </div>
              ))}

              {(tasksByStatus.get(status) ?? []).length === 0 ? (
                <div className="text-xs text-muted-foreground">No tasks</div>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-4 text-xs text-muted-foreground">
        Tip: set Actor ID in the left sidebar so changes are attributed correctly.
      </div>
    </main>
  );
}
