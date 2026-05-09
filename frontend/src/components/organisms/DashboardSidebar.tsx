"use client";

import type { ComponentType, SVGProps } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Bot,
  Boxes,
  CheckCircle2,
  Folder,
  Building2,
  LayoutGrid,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Store,
  Tags,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@radix-ui/react-tooltip";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { useSidebarCollapsed } from "@/lib/use-sidebar-collapsed";
import {
  type healthzHealthzGetResponse,
  useHealthzHealthzGet,
} from "@/api/generated/default/default";
import { cn } from "@/lib/utils";

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

type NavLinkProps = {
  href: string;
  icon: IconComponent;
  label: string;
  active: boolean;
  collapsed: boolean;
};

function NavLink({ href, icon: Icon, label, active, collapsed }: NavLinkProps) {
  const link = (
    <Link
      href={href}
      aria-label={collapsed ? label : undefined}
      className={cn(
        "flex items-center rounded-lg py-2.5 text-slate-700 transition",
        collapsed ? "justify-center px-2" : "gap-3 px-3",
        active ? "bg-blue-100 text-blue-800 font-medium" : "hover:bg-slate-100",
      )}
    >
      <Icon className="h-4 w-4" />
      <span className={collapsed ? "sr-only" : ""}>{label}</span>
    </Link>
  );

  if (!collapsed) return link;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent
        side="right"
        sideOffset={6}
        className="z-50 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 shadow-md"
      >
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

function SectionHeader({
  children,
  collapsed,
}: {
  children: string;
  collapsed: boolean;
}) {
  return (
    <p
      className={cn(
        "px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400",
        collapsed && "sr-only",
      )}
    >
      {children}
    </p>
  );
}

export function DashboardSidebar() {
  const pathname = usePathname();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [collapsed, setCollapsed] = useSidebarCollapsed();
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

  return (
    <TooltipProvider delayDuration={150}>
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[280px] -translate-x-full flex-col border-r border-slate-200 bg-white pt-16 shadow-lg",
          "transition-[transform,width] duration-200 ease-in-out",
          "[[data-sidebar=open]_&]:translate-x-0",
          "md:relative md:inset-auto md:z-auto md:translate-x-0 md:pt-0 md:shadow-none",
          collapsed ? "md:w-[64px]" : "md:w-[260px]",
        )}
      >
        <div className={cn("flex-1 py-4", collapsed ? "px-1.5" : "px-3")}>
          <div className="flex items-center justify-between px-3">
            <p
              className={cn(
                "text-xs font-semibold uppercase tracking-wider text-slate-500",
                collapsed && "sr-only",
              )}
            >
              Navigation
            </p>
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!collapsed}
              data-cy="sidebar-collapse-toggle"
              className="hidden md:flex items-center justify-center rounded-md p-1 text-slate-500 transition hover:bg-slate-100"
            >
              {collapsed ? (
                <PanelLeftOpen className="h-4 w-4" />
              ) : (
                <PanelLeftClose className="h-4 w-4" />
              )}
            </button>
          </div>
          <nav className="mt-3 space-y-4 text-sm">
            <div>
              <SectionHeader collapsed={collapsed}>Overview</SectionHeader>
              <div className="mt-1 space-y-1">
                <NavLink
                  href="/dashboard"
                  icon={BarChart3}
                  label="Dashboard"
                  active={pathname === "/dashboard"}
                  collapsed={collapsed}
                />
                <NavLink
                  href="/activity"
                  icon={Activity}
                  label="Live feed"
                  active={pathname.startsWith("/activity")}
                  collapsed={collapsed}
                />
              </div>
            </div>

            <div>
              <SectionHeader collapsed={collapsed}>Boards</SectionHeader>
              <div className="mt-1 space-y-1">
                <NavLink
                  href="/board-groups"
                  icon={Folder}
                  label="Board groups"
                  active={pathname.startsWith("/board-groups")}
                  collapsed={collapsed}
                />
                <NavLink
                  href="/boards"
                  icon={LayoutGrid}
                  label="Boards"
                  active={pathname.startsWith("/boards")}
                  collapsed={collapsed}
                />
                <NavLink
                  href="/tags"
                  icon={Tags}
                  label="Tags"
                  active={pathname.startsWith("/tags")}
                  collapsed={collapsed}
                />
                <NavLink
                  href="/approvals"
                  icon={CheckCircle2}
                  label="Approvals"
                  active={pathname.startsWith("/approvals")}
                  collapsed={collapsed}
                />
                {isAdmin ? (
                  <NavLink
                    href="/custom-fields"
                    icon={Settings}
                    label="Custom fields"
                    active={pathname.startsWith("/custom-fields")}
                    collapsed={collapsed}
                  />
                ) : null}
              </div>
            </div>

            {isAdmin ? (
              <div>
                <SectionHeader collapsed={collapsed}>Skills</SectionHeader>
                <div className="mt-1 space-y-1">
                  <NavLink
                    href="/skills/marketplace"
                    icon={Store}
                    label="Marketplace"
                    active={
                      pathname === "/skills" ||
                      pathname.startsWith("/skills/marketplace")
                    }
                    collapsed={collapsed}
                  />
                  <NavLink
                    href="/skills/packs"
                    icon={Boxes}
                    label="Packs"
                    active={pathname.startsWith("/skills/packs")}
                    collapsed={collapsed}
                  />
                </div>
              </div>
            ) : null}

            <div>
              <SectionHeader collapsed={collapsed}>Administration</SectionHeader>
              <div className="mt-1 space-y-1">
                <NavLink
                  href="/organization"
                  icon={Building2}
                  label="Organization"
                  active={pathname.startsWith("/organization")}
                  collapsed={collapsed}
                />
                {isAdmin ? (
                  <NavLink
                    href="/gateways"
                    icon={Network}
                    label="Gateways"
                    active={pathname.startsWith("/gateways")}
                    collapsed={collapsed}
                  />
                ) : null}
                {isAdmin ? (
                  <NavLink
                    href="/agents"
                    icon={Bot}
                    label="Agents"
                    active={pathname.startsWith("/agents")}
                    collapsed={collapsed}
                  />
                ) : null}
              </div>
            </div>
          </nav>
        </div>
        <div
          className={cn(
            "border-t border-slate-200 p-4",
            collapsed && "flex justify-center px-2",
          )}
        >
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  aria-label={statusLabel}
                  className={cn(
                    "h-2 w-2 rounded-full",
                    systemStatus === "operational" && "bg-emerald-500",
                    systemStatus === "degraded" && "bg-rose-500",
                    systemStatus === "unknown" && "bg-slate-300",
                  )}
                />
              </TooltipTrigger>
              <TooltipContent
                side="right"
                sideOffset={6}
                className="z-50 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 shadow-md"
              >
                {statusLabel}
              </TooltipContent>
            </Tooltip>
          ) : (
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
          )}
        </div>
      </aside>
    </TooltipProvider>
  );
}
