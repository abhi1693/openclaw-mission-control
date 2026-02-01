"use client";

import { useEffect, useState } from "react";
import styles from "./_components/Shell.module.css";
import { apiGet } from "../lib/api";

type Activity = {
  id: number;
  actor_employee_id: number | null;
  entity_type: string;
  entity_id: number | null;
  verb: string;
  payload: any;
  created_at: string;
};

type Project = { id: number; name: string; status: string };

type Department = { id: number; name: string; head_employee_id: number | null };

type Employee = {
  id: number;
  name: string;
  employee_type: string;
  department_id: number | null;
  manager_id: number | null;
  title: string | null;
  status: string;
};

type Task = {
  id: number;
  project_id: number;
  title: string;
  status: string;
  assignee_employee_id: number | null;
  reviewer_employee_id: number | null;
  created_at: string;
  updated_at: string;
};

export default function MissionControlHome() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [a, p, d, e, t] = await Promise.all([
        apiGet<Activity[]>("/activities?limit=20"),
        apiGet<Project[]>("/projects"),
        apiGet<Department[]>("/departments"),
        apiGet<Employee[]>("/employees"),
        apiGet<Task[]>("/tasks"),
      ]);
      setActivities(a);
      setProjects(p);
      setDepartments(d);
      setEmployees(e);
      setTasks(t);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const activeProjects = projects.filter((x) => x.status === "active").length;
  const activeEmployees = employees.filter((x) => x.status === "active").length;
  const blockedTasks = tasks.filter((t) => t.status === "blocked").length;
  const reviewQueue = tasks.filter((t) => t.status === "review").length;

  return (
    <main>
      <div className={styles.topbar}>
        <div>
          <h1 className={styles.h1}>Mission Control</h1>
          <p className={styles.p}>
            Company dashboard: departments, employees/agents, projects, and work — designed to run like a real org.
          </p>
        </div>
        <button className={styles.btn} onClick={load}>
          Refresh
        </button>
      </div>

      {error ? (
        <div className={styles.card} style={{ borderColor: "rgba(176,0,32,0.25)" }}>
          <div className={styles.cardTitle}>Error</div>
          <div style={{ color: "#b00020" }}>{error}</div>
        </div>
      ) : null}

      <div className={styles.grid2} style={{ marginTop: 16 }}>
        <section className={styles.card}>
          <div className={styles.cardTitle}>Company Snapshot</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <span className={styles.badge}>Projects: {activeProjects}</span>
            <span className={styles.badge}>Departments: {departments.length}</span>
            <span className={styles.badge}>Active people: {activeEmployees}</span>
            <span className={styles.badge}>In review: {reviewQueue}</span>
            <span className={styles.badge}>Blocked: {blockedTasks}</span>
          </div>
          <div className={styles.list} style={{ marginTop: 12 }}>
            {projects.slice(0, 6).map((p) => (
              <div key={p.id} className={styles.item}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ fontWeight: 650 }}>{p.name}</div>
                  <span className={styles.badge}>{p.status}</span>
                </div>
                <div className={styles.mono} style={{ marginTop: 6 }}>
                  Project ID: {p.id}
                </div>
              </div>
            ))}
            {projects.length === 0 ? <div className={styles.mono}>No projects yet. Create one in Projects.</div> : null}
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.cardTitle}>Activity Feed</div>
          <div className={styles.list}>
            {activities.map((a) => (
              <div key={a.id} className={styles.item}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <span style={{ fontWeight: 650 }}>{a.entity_type}</span> · {a.verb}
                    {a.entity_id != null ? ` #${a.entity_id}` : ""}
                  </div>
                  <span className={styles.mono}>{new Date(a.created_at).toLocaleString()}</span>
                </div>
                {a.payload ? <div className={styles.mono} style={{ marginTop: 6 }}>{JSON.stringify(a.payload)}</div> : null}
              </div>
            ))}
            {activities.length === 0 ? <div className={styles.mono}>No activity yet.</div> : null}
          </div>
        </section>
      </div>
    </main>
  );
}
