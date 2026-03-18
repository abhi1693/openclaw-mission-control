"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Bot,
  Boxes,
  BookOpen,
  Brain,
  Calendar,
  Clock,
  CheckCircle2,
  FileText,
  Folder,
  Building2,
  LayoutGrid,
  Monitor,
  Network,
  Settings,
  Store,
  Tags,
  Users,
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

  const linkClass = (active: boolean) =>
    cn(
      "flex items-center gap-3 rounded-lg px-3 py-2 text-slate-700 transition text-[13px]",
      active ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-50",
    );

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-[280px] -translate-x-full flex-col border-r border-slate-200 bg-white pt-16 transition-transform duration-200 ease-in-out [[data-sidebar=open]_&]:translate-x-0 md:relative md:inset-auto md:z-auto md:w-[240px] md:translate-x-0 md:pt-0 md:transition-none">
      <div className="flex-1 overflow-y-auto px-3 py-4">
        <nav className="space-y-5 text-sm">
          {/* Overview */}
          <div>
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Overview
            </p>
            <div className="space-y-0.5">
              <Link href="/dashboard" className={linkClass(pathname === "/dashboard")}>
                <BarChart3 className="h-4 w-4" /> Dashboard
              </Link>
              <Link href="/activity" className={linkClass(pathname.startsWith("/activity"))}>
                <Activity className="h-4 w-4" /> Live feed
              </Link>
              <Link href="/calendar" className={linkClass(pathname.startsWith("/calendar"))}>
                <Calendar className="h-4 w-4" /> Calendar
              </Link>
              <Link href="/office" className={linkClass(pathname.startsWith("/office"))}>
                <Monitor className="h-4 w-4" /> Office
              </Link>
            </div>
          </div>

          {/* Work */}
          <div>
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Work
            </p>
            <div className="space-y-0.5">
              <Link href="/boards" className={linkClass(pathname.startsWith("/boards"))}>
                <LayoutGrid className="h-4 w-4" /> Boards
              </Link>
              <Link href="/projects" className={linkClass(pathname.startsWith("/projects"))}>
                <Folder className="h-4 w-4" /> Projects
              </Link>
              <Link href="/board-groups" className={linkClass(pathname.startsWith("/board-groups"))}>
                <Boxes className="h-4 w-4" /> Board groups
              </Link>
              <Link href="/approvals" className={linkClass(pathname.startsWith("/approvals"))}>
                <CheckCircle2 className="h-4 w-4" /> Approvals
              </Link>
              <Link href="/tags" className={linkClass(pathname.startsWith("/tags"))}>
                <Tags className="h-4 w-4" /> Tags
              </Link>
            </div>
          </div>

          {/* Knowledge */}
          <div>
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Knowledge
            </p>
            <div className="space-y-0.5">
              <Link href="/memories" className={linkClass(pathname.startsWith("/memories"))}>
                <Brain className="h-4 w-4" /> Memories
              </Link>
              <Link href="/docs" className={linkClass(pathname.startsWith("/docs"))}>
                <FileText className="h-4 w-4" /> Docs
              </Link>
            </div>
          </div>

          {/* Learning */}
          <div>
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Learning
            </p>
            <div className="space-y-0.5">
              <Link href="/reading-list" className={linkClass(pathname.startsWith("/reading-list"))}>
                <BookOpen className="h-4 w-4" /> Reading List
              </Link>
              <Link href="/study-log" className={linkClass(pathname.startsWith("/study-log"))}>
                <Clock className="h-4 w-4" /> Study Log
              </Link>
            </div>
          </div>

          {/* Team */}
          <div>
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Organization
            </p>
            <div className="space-y-0.5">
              <Link href="/team" className={linkClass(pathname.startsWith("/team"))}>
                <Users className="h-4 w-4" /> Team
              </Link>
              <Link href="/agents" className={linkClass(pathname.startsWith("/agents"))}>
                <Bot className="h-4 w-4" /> Agents
              </Link>
              <Link href="/gateways" className={linkClass(pathname.startsWith("/gateways"))}>
                <Network className="h-4 w-4" /> Gateways
              </Link>
            </div>
          </div>

          {/* Skills */}
          {isAdmin ? (
            <div>
              <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Skills
              </p>
              <div className="space-y-0.5">
                <Link href="/skills/marketplace" className={linkClass(pathname.startsWith("/skills/marketplace") || pathname === "/skills")}>
                  <Store className="h-4 w-4" /> Marketplace
                </Link>
                <Link href="/skills/packs" className={linkClass(pathname.startsWith("/skills/packs"))}>
                  <BookOpen className="h-4 w-4" /> Packs
                </Link>
              </div>
            </div>
          ) : null}

          {/* Settings */}
          <div>
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Settings
            </p>
            <div className="space-y-0.5">
              <Link href="/organization" className={linkClass(pathname.startsWith("/organization"))}>
                <Building2 className="h-4 w-4" /> Organization
              </Link>
              <Link href="/custom-fields" className={linkClass(pathname.startsWith("/custom-fields"))}>
                <Settings className="h-4 w-4" /> Custom fields
              </Link>
            </div>
          </div>
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
