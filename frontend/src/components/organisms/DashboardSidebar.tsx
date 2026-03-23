"use client";

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
  Settings,
  Store,
  Tags,
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

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-[280px] -translate-x-full flex-col border-r border-[color:var(--border)] bg-[color:var(--surface)] pt-16 shadow-lg transition-transform duration-200 ease-in-out [[data-sidebar=open]_&]:translate-x-0 md:relative md:inset-auto md:z-auto md:w-[260px] md:translate-x-0 md:pt-0 md:shadow-none md:transition-none">
      <div className="flex-1 px-3 py-4">
        <p className="px-3 text-xs font-semibold uppercase tracking-wider text-muted">
          Navigation
        </p>
        <nav className="mt-3 space-y-4 text-sm">
          <div>
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-quiet">
              Overview
            </p>
            <div className="mt-1 space-y-1">
              <Link
                href="/dashboard"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname === "/dashboard"
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <BarChart3 className="h-4 w-4" />
                Dashboard
              </Link>
              <Link
                href="/activity"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname.startsWith("/activity")
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <Activity className="h-4 w-4" />
                Live feed
              </Link>
            </div>
          </div>

          <div>
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-quiet">
              Boards
            </p>
            <div className="mt-1 space-y-1">
              <Link
                href="/board-groups"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname.startsWith("/board-groups")
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <Folder className="h-4 w-4" />
                Board groups
              </Link>
              <Link
                href="/boards"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname.startsWith("/boards")
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <LayoutGrid className="h-4 w-4" />
                Boards
              </Link>
              <Link
                href="/tags"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname.startsWith("/tags")
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <Tags className="h-4 w-4" />
                Tags
              </Link>
              <Link
                href="/approvals"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname.startsWith("/approvals")
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <CheckCircle2 className="h-4 w-4" />
                Approvals
              </Link>
              {isAdmin ? (
                <Link
                  href="/custom-fields"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                    pathname.startsWith("/custom-fields")
                      ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                      : "hover:bg-[color:var(--surface-muted)]",
                  )}
                >
                  <Settings className="h-4 w-4" />
                  Custom fields
                </Link>
              ) : null}
            </div>
          </div>

          <div>
            {isAdmin ? (
              <>
                <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-quiet">
                  Skills
                </p>
                <div className="mt-1 space-y-1">
                  <Link
                    href="/skills/marketplace"
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                      pathname === "/skills" ||
                        pathname.startsWith("/skills/marketplace")
                        ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                        : "hover:bg-[color:var(--surface-muted)]",
                    )}
                  >
                    <Store className="h-4 w-4" />
                    Marketplace
                  </Link>
                  <Link
                    href="/skills/packs"
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                      pathname.startsWith("/skills/packs")
                        ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                        : "hover:bg-[color:var(--surface-muted)]",
                    )}
                  >
                    <Boxes className="h-4 w-4" />
                    Packs
                  </Link>
                </div>
              </>
            ) : null}
          </div>

          <div>
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-quiet">
              Administration
            </p>
            <div className="mt-1 space-y-1">
              <Link
                href="/organization"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                  pathname.startsWith("/organization")
                    ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                    : "hover:bg-[color:var(--surface-muted)]",
                )}
              >
                <Building2 className="h-4 w-4" />
                Organization
              </Link>
              {isAdmin ? (
                <Link
                  href="/gateways"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                    pathname.startsWith("/gateways")
                      ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                      : "hover:bg-[color:var(--surface-muted)]",
                  )}
                >
                  <Network className="h-4 w-4" />
                  Gateways
                </Link>
              ) : null}
              {isAdmin ? (
                <Link
                  href="/agents"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-strong transition",
                    pathname.startsWith("/agents")
                      ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)] font-medium"
                      : "hover:bg-[color:var(--surface-muted)]",
                  )}
                >
                  <Bot className="h-4 w-4" />
                  Agents
                </Link>
              ) : null}
            </div>
          </div>
        </nav>
      </div>
      <div className="border-t border-[color:var(--border)] p-4">
        <div className="flex items-center gap-2 text-xs text-muted">
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              systemStatus === "operational" && "bg-emerald-500",
              systemStatus === "degraded" && "bg-rose-500",
              systemStatus === "unknown" && "bg-[color:var(--border-strong)]",
            )}
          />
          {statusLabel}
        </div>
      </div>
    </aside>
  );
}
