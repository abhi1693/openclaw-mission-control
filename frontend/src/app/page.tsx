"use client";

import { useState } from "react";
import Link from "next/link";
import styles from "@/app/_components/Shell.module.css";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { normalizeActivities } from "@/lib/normalize";
import { Select } from "@/components/ui/select";

import { useCreateProjectProjectsPost, useListProjectsProjectsGet } from "@/api/generated/projects/projects";
import { useCreateDepartmentDepartmentsPost, useListDepartmentsDepartmentsGet } from "@/api/generated/org/org";
import { useCreateEmployeeEmployeesPost, useListEmployeesEmployeesGet } from "@/api/generated/org/org";
import { useListActivitiesActivitiesGet } from "@/api/generated/activities/activities";

export default function Home() {
  const projects = useListProjectsProjectsGet();
  const projectList = projects.data?.status === 200 ? projects.data.data : [];
  const departments = useListDepartmentsDepartmentsGet();
  const departmentList = departments.data?.status === 200 ? departments.data.data : [];
  const employees = useListEmployeesEmployeesGet();
  const activities = useListActivitiesActivitiesGet({ limit: 20 });
  const employeeList = employees.data?.status === 200 ? employees.data.data : [];
  const activityList = normalizeActivities(activities.data);

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
    <main>
      <div className={styles.topbar}>
        <div>
          <h1 className={styles.h1}>Company Mission Control</h1>
          <p className={styles.p}>Command center for projects, people, and operations. No‑auth v1.</p>
        </div>
        <Button variant="outline" onClick={() => { projects.refetch(); departments.refetch(); employees.refetch(); activities.refetch(); }} disabled={projects.isFetching || departments.isFetching || employees.isFetching || activities.isFetching}>
          Refresh
        </Button>
      </div>

      <div className={styles.grid2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>Quick create</div>
          <div className={styles.list}>
            <div className={styles.item}>
              <div style={{ marginBottom: 8, fontWeight: 600 }}>Project</div>
              <div style={{ display: "grid", gap: 8 }}>
                <Input placeholder="Project name" value={projectName} onChange={(e) => setProjectName(e.target.value)} />
                <Button onClick={() => createProject.mutate({ data: { name: projectName, status: "active" } })} disabled={!projectName.trim() || createProject.isPending}>Create</Button>
                {createProject.error ? <div className={styles.mono}>{(createProject.error as Error).message}</div> : null}
              </div>
            </div>
            <div className={styles.item}>
              <div style={{ marginBottom: 8, fontWeight: 600 }}>Department</div>
              <div style={{ display: "grid", gap: 8 }}>
                <Input placeholder="Department name" value={deptName} onChange={(e) => setDeptName(e.target.value)} />
                <Button onClick={() => createDepartment.mutate({ data: { name: deptName } })} disabled={!deptName.trim() || createDepartment.isPending}>Create</Button>
                {createDepartment.error ? <div className={styles.mono}>{(createDepartment.error as Error).message}</div> : null}
              </div>
            </div>
            <div className={styles.item}>
              <div style={{ marginBottom: 8, fontWeight: 600 }}>Person</div>
              <div style={{ display: "grid", gap: 8 }}>
                <Input placeholder="Name" value={personName} onChange={(e) => setPersonName(e.target.value)} />
                <Select value={personType} onChange={(e) => setPersonType(e.target.value === "agent" ? "agent" : "human")}>
                  <option value="human">human</option>
                  <option value="agent">agent</option>
                </Select>
                <Button onClick={() => createEmployee.mutate({ data: { name: personName, employee_type: personType, status: "active" } })} disabled={!personName.trim() || createEmployee.isPending}>Create</Button>
                {createEmployee.error ? <div className={styles.mono}>{(createEmployee.error as Error).message}</div> : null}
              </div>
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>Live activity</div>
          <div className={styles.list}>
            {activityList.map((a) => (
              <div key={String(a.id)} className={styles.item}>
                <div style={{ fontWeight: 600 }}>{a.entity_type} · {a.verb}</div>
                <div className={styles.mono}>id {a.entity_id ?? "—"}</div>
              </div>
            ))}
            {activityList.length === 0 ? (
              <div className={styles.mono}>No activity yet.</div>
            ) : null}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 18, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
        <Card>
          <CardHeader>
            <CardTitle>Projects</CardTitle>
            <CardDescription>{projectList.length} total</CardDescription>
          </CardHeader>
          <CardContent>
            <div className={styles.list}>
              {projectList.slice(0, 8).map((p) => (
                <div key={p.id ?? p.name} className={styles.item}>
                  <div style={{ fontWeight: 600 }}>{p.name}</div>
                  <div className={styles.mono} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span>{p.status}</span>
                    {p.id ? (
                      <Link href={
                        "/projects/" + p.id
                      } className={styles.badge}>Open</Link>
                    ) : null}
                  </div>
                </div>
              ))}
              {projectList.length === 0 ? <div className={styles.mono}>No projects yet.</div> : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Departments</CardTitle>
            <CardDescription>{departmentList.length} total</CardDescription>
          </CardHeader>
          <CardContent>
            <div className={styles.list}>
              {departmentList.slice(0, 8).map((d) => (
                <div key={d.id ?? d.name} className={styles.item}>
                  <div style={{ fontWeight: 600 }}>{d.name}</div>
                  <div className={styles.mono}>id {d.id}</div>
                </div>
              ))}
              {departmentList.length === 0 ? <div className={styles.mono}>No departments yet.</div> : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>People</CardTitle>
            <CardDescription>{employeeList.length} total</CardDescription>
          </CardHeader>
          <CardContent>
            <div className={styles.list}>
              {employeeList.slice(0, 8).map((e) => (
                <div key={e.id ?? e.name} className={styles.item}>
                  <div style={{ fontWeight: 600 }}>{e.name}</div>
                  <div className={styles.mono}>{e.employee_type}</div>
                </div>
              ))}
              {employeeList.length === 0 ? <div className={styles.mono}>No people yet.</div> : null}
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
