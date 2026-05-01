import Link from "next/link";
import {
  Bot,
  CheckCircle2,
  LayoutGrid,
  MessageCircle,
  Rocket,
  Sparkles,
} from "lucide-react";

import { cn } from "@/lib/utils";

type Action = {
  id: string;
  label: string;
  description: string;
  href: string;
  icon: React.ElementType;
  accent: string;
};

const ACTIONS: Action[] = [
  {
    id: "talk-belle",
    label: "Talk to Belle",
    description: "Voice + chat command line",
    href: "/dashboard",
    icon: MessageCircle,
    accent: "from-fuchsia-500 to-purple-600",
  },
  {
    id: "review-approvals",
    label: "Review approvals",
    description: "Pending agent decisions",
    href: "/approvals",
    icon: CheckCircle2,
    accent: "from-emerald-500 to-teal-500",
  },
  {
    id: "ship-deploy",
    label: "Ship a deploy",
    description: "Promote canary to prod",
    href: "/dashboard",
    icon: Rocket,
    accent: "from-blue-500 to-sky-500",
  },
  {
    id: "open-board",
    label: "Open a board",
    description: "Hop into team workspace",
    href: "/boards",
    icon: LayoutGrid,
    accent: "from-amber-500 to-orange-500",
  },
  {
    id: "manage-agents",
    label: "Manage agents",
    description: "Tune the AI team roster",
    href: "/agents",
    icon: Bot,
    accent: "from-indigo-500 to-violet-500",
  },
  {
    id: "ask-insight",
    label: "Generate insight",
    description: "Ask Belle for a summary",
    href: "/dashboard",
    icon: Sparkles,
    accent: "from-pink-500 to-rose-500",
  },
];

export function QuickActions() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Quick Actions</h3>
          <p className="text-xs text-slate-500">Shortcuts into the most common workflows.</p>
        </div>
      </header>
      <div className="grid grid-cols-2 gap-2 p-4">
        {ACTIONS.map((action) => {
          const Icon = action.icon;
          return (
            <Link
              key={action.id}
              href={action.href}
              className="group flex items-start gap-3 rounded-xl border border-slate-100 bg-slate-50/60 p-3 transition hover:-translate-y-0.5 hover:border-slate-200 hover:bg-white hover:shadow-sm"
            >
              <span
                className={cn(
                  "grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white shadow-sm",
                  action.accent,
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">{action.label}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">{action.description}</p>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
