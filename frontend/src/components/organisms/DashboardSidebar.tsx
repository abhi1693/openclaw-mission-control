"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  CheckCircle2,
  Network,
  Settings,
  Search,
  Target,
  TrendingUp,
} from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import {
  type healthzHealthzGetResponse,
  useHealthzHealthzGet,
} from "@/api/generated/default/default";
import { cn } from "@/lib/utils";

export function DashboardSidebar() {
  const pathname = usePathname();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const healthQuery = useHealthzHealthzGet<healthzHealthzGetResponse, ApiError>(
    {
      query: {
        refetchInterval: 30_000,
        refetchOnMount: "always",
        retry: false,
      },
      request: { cache: "no-store" },
    },
  );

  const okValue = healthQuery.data?.data?.ok;
  const systemStatus: "unknown" | "operational" | "degraded" =
    okValue === true
      ? "operational"
      : okValue === false
        ? "degraded"
        : healthQuery.isError
          ? "degraded"
          : "unknown";
  const statusLabel =
    systemStatus === "operational"
      ? "All systems operational"
      : systemStatus === "unknown"
        ? "System status unavailable"
        : "System degraded";

  const MAIN_BOARD_ID = "77ac2212-d23f-4405-b395-5459994d1ffa";
  const SALES_BOARD_ID = "50c2b7fc-92c1-4b02-a9e3-5f782d642ab5";
  const COMPETITOR_BOARD_ID = "42745e83-4afe-406e-91da-b8960e76f71f";

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-[280px] -translate-x-full flex-col border-r border-slate-200 bg-white pt-16 shadow-lg transition-transform duration-200 ease-in-out [[data-sidebar=open]_&]:translate-x-0 md:relative md:inset-auto md:z-auto md:w-[260px] md:translate-x-0 md:pt-0 md:shadow-none md:transition-none">
      <div className="flex-1 px-3 py-4">
        <nav className="space-y-4 text-sm">
          <div>
            <div className="space-y-1">
              <Link
                href="/dashboard"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname === "/dashboard"
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <BarChart3 className="h-4 w-4" />
                Dashboard
              </Link>
            </div>
          </div>

          <div>
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Boards
            </p>
            <div className="mt-1 space-y-1">
              <Link
                href={`/boards/${MAIN_BOARD_ID}`}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname === `/boards/${MAIN_BOARD_ID}`
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <Target className="h-4 w-4" />
                Operations
              </Link>
              <Link
                href={`/boards/${SALES_BOARD_ID}`}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname === `/boards/${SALES_BOARD_ID}`
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <TrendingUp className="h-4 w-4" />
                Sales Pipeline
              </Link>
              <Link
                href={`/boards/${COMPETITOR_BOARD_ID}`}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname === `/boards/${COMPETITOR_BOARD_ID}`
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <Search className="h-4 w-4" />
                Competitor Intel
              </Link>
            </div>
          </div>

          <div>
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Knowledge
            </p>
            <div className="mt-1 space-y-1">
              <Link
                href="/wiki"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname.startsWith("/wiki")
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <BookOpen className="h-4 w-4" />
                Wiki
              </Link>
            </div>
          </div>

          <div>
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Activity
            </p>
            <div className="mt-1 space-y-1">
              <Link
                href="/activity"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname.startsWith("/activity")
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <Activity className="h-4 w-4" />
                Live Feed
              </Link>
              <Link
                href="/approvals"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                  pathname.startsWith("/approvals")
                    ? "bg-blue-100 text-blue-800 font-medium"
                    : "hover:bg-slate-100",
                )}
              >
                <CheckCircle2 className="h-4 w-4" />
                Approvals
              </Link>
            </div>
          </div>

          {isAdmin ? (
            <div>
              <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Admin
              </p>
              <div className="mt-1 space-y-1">
                <Link
                  href="/agents"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                    pathname.startsWith("/agents")
                      ? "bg-blue-100 text-blue-800 font-medium"
                      : "hover:bg-slate-100",
                  )}
                >
                  <Bot className="h-4 w-4" />
                  Agents
                </Link>
                <Link
                  href="/gateways"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                    pathname.startsWith("/gateways")
                      ? "bg-blue-100 text-blue-800 font-medium"
                      : "hover:bg-slate-100",
                  )}
                >
                  <Network className="h-4 w-4" />
                  Gateways
                </Link>
                <Link
                  href="/boards"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-slate-700 transition",
                    pathname === "/boards"
                      ? "bg-blue-100 text-blue-800 font-medium"
                      : "hover:bg-slate-100",
                  )}
                >
                  <Settings className="h-4 w-4" />
                  All Boards
                </Link>
              </div>
            </div>
          ) : null}
        </nav>
      </div>
      <div className="border-t border-slate-200 p-4">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              systemStatus === "operational" && "bg-emerald-500",
              systemStatus === "degraded" && "bg-rose-500",
              systemStatus === "unknown" && "bg-slate-300",
            )}
          />
          {statusLabel}
        </div>
      </div>
    </aside>
  );
}
