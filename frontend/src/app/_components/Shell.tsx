"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import styles from "./Shell.module.css";

const NAV = [
  { href: "/", label: "Mission Control" },
  { href: "/projects", label: "Projects" },
  { href: "/kanban", label: "Kanban" },
  { href: "/departments", label: "Departments" },
  { href: "/people", label: "People" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [actorId, setActorId] = useState(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.localStorage.getItem("actor_employee_id") ?? "";
    } catch {
      return "";
    }
  });
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandTitle}>OpenClaw Agency</div>
          <div className={styles.brandSub}>Company Mission Control (no-auth v1)</div>
        </div>
        <nav className={styles.nav}>
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={path === n.href ? styles.active : undefined}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className={styles.mono} style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Actor ID</div>
          <input
            value={actorId}
            onChange={(e) => {
              const v = e.target.value;
              setActorId(v);
              try {
                if (v) window.localStorage.setItem("actor_employee_id", v);
                else window.localStorage.removeItem("actor_employee_id");
              } catch {
                // ignore
              }
            }}
            placeholder="e.g. 1"
            style={{ width: "100%", padding: "6px 8px", borderRadius: 6, border: "1px solid #333", background: "transparent" }}
          />
        </div>

        <div className={styles.mono} style={{ marginTop: "auto" }}>
          Tip: use your machine IP + ports<br />
          <span className={styles.kbd}>:3000</span> UI &nbsp; <span className={styles.kbd}>:8000</span> API
        </div>
      </aside>
      <div className={styles.main}>{children}</div>
    </div>
  );
}
