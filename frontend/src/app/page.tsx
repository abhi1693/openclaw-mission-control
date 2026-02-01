"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

import { useCreateProjectProjectsPost, useListProjectsProjectsGet } from "@/api/generated/projects/projects";
import { useCreateDepartmentDepartmentsPost, useListDepartmentsDepartmentsGet } from "@/api/generated/org/org";
import { useCreateEmployeeEmployeesPost, useListEmployeesEmployeesGet } from "@/api/generated/org/org";
import { useListActivitiesActivitiesGet } from "@/api/generated/activities/activities";

export default function Home() {
  const projects = useListProjectsProjectsGet();
  const departments = useListDepartmentsDepartmentsGet();
  const employees = useListEmployeesEmployeesGet();
  const activities = useListActivitiesActivitiesGet({ limit: 20 });

  const [projectName, setProjectName] = useState("");
  const [deptName, setDeptName] = useState("");
  const [personName, setPersonName] = useState("");
  const [personType, setPersonType] = useState<"human" | "agent">("human");

  const createProject = useCreateProjectProjectsPost({
    mutation: { onSuccess: () => { setProjectName(""); projects.refetch(); } },
  });
  const createDepartment = useCreateDepartmentDepartmentsPost({
    mutation: { onSuccess: () => { setDeptName(""); departments.refetch(); } },
  });
  const createEmployee = useCreateEmployeeEmployeesPost({
    mutation: { onSuccess: () => { setPersonName(""); employees.refetch(); } },
  });

  return (
    <main className="mx-auto max-w-6xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Company Mission Control</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Dashboard overview + quick create. No-auth v1.
          </p>
        </div>
        <Button variant="outline" onClick={() => { projects.refetch(); departments.refetch(); employees.refetch(); activities.refetch(); }}>
          Refresh
        </Button>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Quick create project</CardTitle>
            <CardDescription>Projects drive all tasks</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Project name" value={projectName} onChange={(e) => setProjectName(e.target.value)} />
            <Button
              onClick={() => createProject.mutate({ data: { name: projectName, status: "active" } })}
              disabled={!projectName.trim() || createProject.isPending}
            >
              Create
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Quick create department</CardTitle>
            <CardDescription>Organization structure</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Department name" value={deptName} onChange={(e) => setDeptName(e.target.value)} />
            <Button
              onClick={() => createDepartment.mutate({ data: { name: deptName } })}
              disabled={!deptName.trim() || createDepartment.isPending}
            >
              Create
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Quick add person</CardTitle>
            <CardDescription>Employees & agents</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Name" value={personName} onChange={(e) => setPersonName(e.target.value)} />
            <Select value={personType} onChange={(e) => setPersonType(e.target.value === "agent" ? "agent" : "human")}
            >
              <option value="human">human</option>
              <option value="agent">agent</option>
            </Select>
            <Button
              onClick={() => createEmployee.mutate({ data: { name: personName, employee_type: personType, status: "active" } })}
              disabled={!personName.trim() || createEmployee.isPending}
            >
              Create
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Projects</CardTitle>
            <CardDescription>{(projects.data ?? []).length} total</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {(projects.data ?? []).slice(0, 8).map((p) => (
                <li key={p.id ?? p.name} className="flex items-center justify-between rounded-md border p-2 text-sm">
                  <span>{p.name}</span>
                  <span className="text-xs text-muted-foreground">{p.status}</span>
                </li>
              ))}
              {(projects.data ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">No projects yet.</li>
              ) : null}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Departments</CardTitle>
            <CardDescription>{(departments.data ?? []).length} total</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {(departments.data ?? []).slice(0, 8).map((d) => (
                <li key={d.id ?? d.name} className="flex items-center justify-between rounded-md border p-2 text-sm">
                  <span>{d.name}</span>
                  <span className="text-xs text-muted-foreground">id {d.id}</span>
                </li>
              ))}
              {(departments.data ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">No departments yet.</li>
              ) : null}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Activity</CardTitle>
            <CardDescription>Latest actions</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {(activities.data ?? []).map((a) => (
                <li key={String(a.id)} className="rounded-md border p-2 text-xs">
                  <div className="font-medium">{a.entity_type} · {a.verb}</div>
                  <div className="text-muted-foreground">id {a.entity_id ?? "—"}</div>
                </li>
              ))}
              {(activities.data ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">No activity yet.</li>
              ) : null}
            </ul>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
