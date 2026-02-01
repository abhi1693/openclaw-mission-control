"use client";

import { useState } from "react";
import { useParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { useListProjectsProjectsGet } from "@/api/generated/projects/projects";
import { useListEmployeesEmployeesGet } from "@/api/generated/org/org";
import {
  useCreateTaskTasksPost,
  useListTasksTasksGet,
  useUpdateTaskTasksTaskIdPatch,
  useDeleteTaskTasksTaskIdDelete,
  useCreateTaskCommentTaskCommentsPost,
  useListTaskCommentsTaskCommentsGet,
} from "@/api/generated/work/work";
import {
  useListProjectMembersProjectsProjectIdMembersGet,
  useAddProjectMemberProjectsProjectIdMembersPost,
  useRemoveProjectMemberProjectsProjectIdMembersMemberIdDelete,
  useUpdateProjectMemberProjectsProjectIdMembersMemberIdPatch,
} from "@/api/generated/projects/projects";

const STATUSES = ["backlog", "ready", "in_progress", "review", "done", "blocked"] as const;

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = Number(params?.id);

  const projects = useListProjectsProjectsGet();
  const project = (projects.data ?? []).find((p) => p.id === projectId);

  const employees = useListEmployeesEmployeesGet();

  const members = useListProjectMembersProjectsProjectIdMembersGet(projectId);
  const addMember = useAddProjectMemberProjectsProjectIdMembersPost({
    mutation: { onSuccess: () => members.refetch() },
  });
  const removeMember = useRemoveProjectMemberProjectsProjectIdMembersMemberIdDelete({
    mutation: { onSuccess: () => members.refetch() },
  });
  const updateMember = useUpdateProjectMemberProjectsProjectIdMembersMemberIdPatch({
    mutation: { onSuccess: () => members.refetch() },
  });

  const tasks = useListTasksTasksGet({ projectId });
  const createTask = useCreateTaskTasksPost({
    mutation: { onSuccess: () => tasks.refetch() },
  });
  const updateTask = useUpdateTaskTasksTaskIdPatch({
    mutation: { onSuccess: () => tasks.refetch() },
  });
  const deleteTask = useDeleteTaskTasksTaskIdDelete({
    mutation: { onSuccess: () => tasks.refetch() },
  });

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assigneeId, setAssigneeId] = useState<string>("");
  const [reviewerId, setReviewerId] = useState<string>("");

  const [commentTaskId, setCommentTaskId] = useState<number | null>(null);
  const [commentBody, setCommentBody] = useState("");

  const comments = useListTaskCommentsTaskCommentsGet(
    { taskId: commentTaskId ?? 0 },
    { query: { enabled: Boolean(commentTaskId) } },
  );
  const addComment = useCreateTaskCommentTaskCommentsPost({
    mutation: {
      onSuccess: () => {
        comments.refetch();
        setCommentBody("");
      },
    },
  });

  const tasksByStatus = (() => {
    const map = new Map<string, typeof tasks.data>();
    for (const s of STATUSES) map.set(s, []);
    for (const t of tasks.data ?? []) {
      map.get(t.status)?.push(t);
    }
    return map;
  })();

  const employeeName = (id: number | null | undefined) =>
    employees.data?.find((e) => e.id === id)?.name ?? "—";

  const projectMembers = members.data ?? [];

  return (
    <main className="mx-auto max-w-6xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{project?.name ?? `Project #${projectId}`}</h1>
          <p className="mt-1 text-sm text-muted-foreground">Project detail: staffing + tasks.</p>
        </div>
        <Button variant="outline" onClick={() => { tasks.refetch(); members.refetch(); }}>
          Refresh
        </Button>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Create task</CardTitle>
            <CardDescription>Project-scoped tasks</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Textarea placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <Select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
                <option value="">Assignee</option>
                {(employees.data ?? []).map((e) => (
                  <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
                ))}
              </Select>
              <Select value={reviewerId} onChange={(e) => setReviewerId(e.target.value)}>
                <option value="">Reviewer</option>
                {(employees.data ?? []).map((e) => (
                  <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
                ))}
              </Select>
            </div>
            <Button
              onClick={() =>
                createTask.mutate({
                  data: {
                    project_id: projectId,
                    title,
                    description: description.trim() ? description : null,
                    status: "backlog",
                    assignee_employee_id: assigneeId ? Number(assigneeId) : null,
                    reviewer_employee_id: reviewerId ? Number(reviewerId) : null,
                  },
                })
              }
              disabled={!title.trim() || createTask.isPending}
            >
              Add task
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Staffing</CardTitle>
            <CardDescription>Project members</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Select onChange={(e) => {
              const empId = e.target.value;
              if (!empId) return;
              addMember.mutate({ projectId, data: { project_id: projectId, employee_id: Number(empId), role: "member" } });
              e.currentTarget.value = "";
            }}>
              <option value="">Add member…</option>
              {(employees.data ?? []).map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
              ))}
            </Select>
            <ul className="space-y-2">
              {projectMembers.map((m) => (
                <li key={m.id ?? `${m.project_id}-${m.employee_id}`} className="rounded-md border p-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <div>{employeeName(m.employee_id)}</div>
                    <Button
                      variant="outline"
                      onClick={() => removeMember.mutate({ projectId, memberId: Number(m.id) })}
                    >
                      Remove
                    </Button>
                  </div>
                  <div className="mt-2">
                    <Input
                      placeholder="Role (e.g., PM, QA, Dev)"
                      defaultValue={m.role ?? ""}
                      onBlur={(e) =>
                        updateMember.mutate({
                          projectId,
                          memberId: Number(m.id),
                          data: { project_id: projectId, employee_id: m.employee_id, role: e.currentTarget.value || null },
                        })
                      }
                    />
                  </div>
                </li>
              ))}
              {projectMembers.length === 0 ? <li className="text-sm text-muted-foreground">No members yet.</li> : null}
            </ul>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4">
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
          {STATUSES.map((s) => (
            <Card key={s}>
              <CardHeader>
                <CardTitle className="text-sm uppercase tracking-wide">{s.replace("_", " ")}</CardTitle>
                <CardDescription>{tasksByStatus.get(s)?.length ?? 0} tasks</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {(tasksByStatus.get(s) ?? []).map((t) => (
                  <div key={t.id ?? t.title} className="rounded-md border p-2 text-sm">
                    <div className="font-medium">{t.title}</div>
                    <div className="text-xs text-muted-foreground">Assignee: {employeeName(t.assignee_employee_id)}</div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {STATUSES.filter((x) => x !== s).map((x) => (
                        <Button
                          key={x}
                          variant="outline"
                          size="sm"
                          onClick={() => updateTask.mutate({ taskId: Number(t.id), data: { status: x } })}
                        >
                          {x}
                        </Button>
                      ))}
                    </div>
                    <div className="mt-2 flex gap-2">
                      <Button variant="outline" size="sm" onClick={() => setCommentTaskId(Number(t.id))}>
                        Comments
                      </Button>
                      <Button variant="destructive" size="sm" onClick={() => deleteTask.mutate({ taskId: Number(t.id) })}>
                        Delete
                      </Button>
                    </div>
                  </div>
                ))}
                {(tasksByStatus.get(s) ?? []).length === 0 ? (
                  <div className="text-xs text-muted-foreground">No tasks</div>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <div className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Task comments</CardTitle>
            <CardDescription>{commentTaskId ? `Task #${commentTaskId}` : "Select a task"}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              placeholder="Write a comment"
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              disabled={!commentTaskId}
            />
            <Button
              onClick={() =>
                addComment.mutate({
                  data: {
                    task_id: Number(commentTaskId),
                    author_employee_id: null,
                    body: commentBody,
                  },
                })
              }
              disabled={!commentTaskId || !commentBody.trim() || addComment.isPending}
            >
              Add comment
            </Button>
            <ul className="space-y-2">
              {(comments.data ?? []).map((c) => (
                <li key={String(c.id)} className="rounded-md border p-2 text-sm">
                  {c.body}
                </li>
              ))}
              {(comments.data ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">No comments yet.</li>
              ) : null}
            </ul>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
