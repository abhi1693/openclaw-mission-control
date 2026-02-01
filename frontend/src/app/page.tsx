"use client";

import {useEffect, useMemo, useState} from "react";

type TaskStatus = "todo" | "doing" | "done";

type Task = {
  id: number;
  title: string;
  description: string | null;
  status: TaskStatus;
  assignee: string | null;
  created_at: string;
  updated_at: string | null;
};

const STATUSES: Array<{key: TaskStatus; label: string}> = [
  {key: "todo", label: "To do"},
  {key: "doing", label: "Doing"},
  {key: "done", label: "Done"},
];

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) throw new Error("NEXT_PUBLIC_API_URL is not set");
  return `${base}${path}`;
}

export default function Home() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState("");
  const [description, setDescription] = useState("");

  const byStatus = useMemo(() => {
    const map: Record<TaskStatus, Task[]> = {todo: [], doing: [], done: []};
    for (const t of tasks) map[t.status].push(t);
    return map;
  }, [tasks]);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(apiUrl("/tasks"), {cache: "no-store"});
      if (!res.ok) throw new Error(`Failed to load tasks (${res.status})`);
      setTasks(await res.json());
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function createTask() {
    if (!title.trim()) return;
    setError(null);
    const payload = {
      title,
      description: description.trim() ? description : null,
      assignee: assignee.trim() ? assignee : null,
      status: "todo" as const,
    };

    const res = await fetch(apiUrl("/tasks"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      setError(`Failed to create task (${res.status})`);
      return;
    }

    setTitle("");
    setAssignee("");
    setDescription("");
    await refresh();
  }

  async function move(task: Task, status: TaskStatus) {
    const res = await fetch(apiUrl(`/tasks/${task.id}`), {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({status}),
    });
    if (!res.ok) {
      setError(`Failed to update task (${res.status})`);
      return;
    }
    await refresh();
  }

  async function remove(task: Task) {
    const res = await fetch(apiUrl(`/tasks/${task.id}`), {method: "DELETE"});
    if (!res.ok) {
      setError(`Failed to delete task (${res.status})`);
      return;
    }
    await refresh();
  }

  return (
    <main style={{padding: 24, fontFamily: "ui-sans-serif, system-ui"}}>
      <header style={{display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 16}}>
        <div>
          <h1 style={{fontSize: 28, fontWeight: 700, margin: 0}}>OpenClaw Agency Board</h1>
          <p style={{marginTop: 8, color: "#555"}}>
            Simple Kanban (no auth). Everyone can see who owns what.
          </p>
        </div>
        <button onClick={refresh} disabled={loading} style={btn()}>Refresh</button>
      </header>

      <section style={{marginTop: 18, padding: 16, border: "1px solid #eee", borderRadius: 12}}>
        <h2 style={{margin: 0, fontSize: 16}}>Create task</h2>
        <div style={{display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12, marginTop: 12}}>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Task title"
            style={input()}
          />
          <input
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            placeholder="Assignee (e.g. Head: Design)"
            style={input()}
          />
        </div>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional)"
          style={{...input(), marginTop: 12, minHeight: 80}}
        />
        <div style={{display: "flex", gap: 12, marginTop: 12, alignItems: "center"}}>
          <button onClick={createTask} style={btn("primary")}>Add</button>
          {error ? <span style={{color: "#b00020"}}>{error}</span> : null}
        </div>
      </section>

      <section style={{marginTop: 18}}>
        <div style={{display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14}}>
          {STATUSES.map((s) => (
            <div key={s.key} style={{border: "1px solid #eee", borderRadius: 12, padding: 12, background: "#fafafa"}}>
              <h3 style={{marginTop: 0}}>{s.label} ({byStatus[s.key].length})</h3>
              <div style={{display: "flex", flexDirection: "column", gap: 10}}>
                {byStatus[s.key].map((t) => (
                  <div key={t.id} style={{border: "1px solid #e5e5e5", background: "white", borderRadius: 12, padding: 12}}>
                    <div style={{display: "flex", justifyContent: "space-between", gap: 12}}>
                      <div>
                        <div style={{fontWeight: 650}}>{t.title}</div>
                        <div style={{fontSize: 13, color: "#666", marginTop: 6}}>
                          {t.assignee ? <>Owner: <strong>{t.assignee}</strong></> : "Unassigned"}
                        </div>
                      </div>
                      <button onClick={() => remove(t)} style={btn("danger")}>Delete</button>
                    </div>

                    {t.description ? <p style={{marginTop: 10, color: "#333"}}>{t.description}</p> : null}

                    <div style={{display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap"}}>
                      {STATUSES.filter((x) => x.key !== t.status).map((x) => (
                        <button key={x.key} onClick={() => move(t, x.key)} style={btn()}>
                          Move → {x.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                {byStatus[s.key].length === 0 ? <div style={{color: "#777", fontSize: 13}}>No tasks</div> : null}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function input(): React.CSSProperties {
  return {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: "1px solid #ddd",
    outline: "none",
  };
}

function btn(kind: "primary" | "danger" | "default" = "default"): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "9px 12px",
    borderRadius: 10,
    border: "1px solid #ddd",
    background: "white",
    cursor: "pointer",
  };
  if (kind === "primary") return {...base, background: "#111", color: "white", borderColor: "#111"};
  if (kind === "danger") return {...base, background: "#fff", borderColor: "#f2b8b5", color: "#b00020"};
  return base;
}
