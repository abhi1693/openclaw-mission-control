import { cn } from "@/lib/utils"
import type { ReactNode } from "react"

type Accent = "blue" | "green" | "violet" | "amber" | "rose"

const accentStyles: Record<Accent, string> = {
  blue: "bg-blue-50 text-blue-600",
  green: "bg-emerald-50 text-emerald-600",
  violet: "bg-violet-50 text-violet-600",
  amber: "bg-amber-50 text-amber-600",
  rose: "bg-rose-50 text-rose-600",
}

interface KpiCardProps {
  title?: string
  label?: string
  value: string | number
  subtitle?: string
  sub?: string
  icon?: ReactNode
  accent?: Accent
  highlight?: boolean
  className?: string
}

export function KpiCard({ title, label, value, subtitle, sub, icon, accent, highlight, className }: KpiCardProps) {
  const resolvedAccent = accent ?? (highlight ? "green" : "blue")
  return (
    <section className={cn(
      "rounded-xl border border-slate-200 bg-white p-4 md:p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md",
      className,
    )}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{title ?? label}</p>
          <div className="mt-2 flex items-end gap-2">
            <p className="font-heading text-3xl font-bold text-slate-900">{value}</p>
            {(subtitle ?? sub) && <p className="pb-1 text-xs text-slate-500">{subtitle ?? sub}</p>}
          </div>
        </div>
        {icon && <div className={cn("rounded-lg p-2", accentStyles[resolvedAccent])}>{icon}</div>}
      </div>
    </section>
  )
}
