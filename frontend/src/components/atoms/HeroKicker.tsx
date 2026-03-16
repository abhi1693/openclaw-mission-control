import type { ReactNode } from "react";

export function HeroKicker({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full bg-[color:var(--accent-soft)] px-4 py-1 text-[11px] font-semibold uppercase tracking-[0.35em] text-[color:var(--accent-strong)]">
      {children}
    </span>
  );
}
