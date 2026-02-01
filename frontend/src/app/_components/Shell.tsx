"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./Shell.module.css";

const NAV = [
  { href: "/", label: "Mission Control" },
  { href: "/projects", label: "Projects" },
  { href: "/departments", label: "Departments" },
  { href: "/people", label: "People" },
  { href: "/hr", label: "HR" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
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
        <div className={styles.mono} style={{ marginTop: "auto" }}>
          Tip: use your machine IP + ports<br />
          <span className={styles.kbd}>:3000</span> UI &nbsp; <span className={styles.kbd}>:8000</span> API
        </div>
      </aside>
      <div className={styles.main}>{children}</div>
    </div>
  );
}
