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

  const linkBase =
    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-[var(--text)] transition";
  const linkActive =
    "bg-[var(--accent-soft)] text-[var(--accent-strong)] font-medium";
  const linkInactive = "hover:bg-[var(--surface-muted)]";

  const sectionLabel =
    "px-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-quiet)]";

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-[280px] -translate-x-full flex-col overflow-y-auto border-r border-[var(--border)] bg-[var(--surface)] pt-16 shadow-[var(--shadow-panel)] transition-transform duration-200 ease-in-out [[data-sidebar=open]_&]:translate-x-0 md:relative md:inset-auto md:z-auto md:w-[260px] md:translate-x-0 md:pt-0 md:shadow-none md:transition-none">
      <div className="flex-1 px-3 py-4">
        <p className="px-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Navigation
        </p>
        <nav className="mt-3 space-y-4 text-sm">
          <div>
            <p className={sectionLabel}>Overview</p>
            <div className="mt-1 space-y-1">
              <Link
                href="/dashboard"
                className={cn(
                  linkBase,
                  pathname === "/dashboard" ? linkActive : linkInactive,
                )}
              >
                <BarChart3 className="h-4 w-4" />
                Dashboard
              </Link>
              <Link
                href="/activity"
                className={cn(
                  linkBase,
                  pathname.startsWith("/activity") ? linkActive : linkInactive,
                )}
              >
                <Activity className="h-4 w-4" />
                Live feed
              </Link>
            </div>
          </div>

          <div>
            <p className={sectionLabel}>Boards</p>
            <div className="mt-1 space-y-1">
              <Link
                href="/board-groups"
                className={cn(
                  linkBase,
                  pathname.startsWith("/board-groups")
                    ? linkActive
                    : linkInactive,
                )}
              >
                <Folder className="h-4 w-4" />
                Board groups
              </Link>
              <Link
                href="/boards"
                className={cn(
                  linkBase,
                  pathname.startsWith("/boards") ? linkActive : linkInactive,
                )}
              >
                <LayoutGrid className="h-4 w-4" />
                Boards
              </Link>
              <Link
                href="/tags"
                className={cn(
                  linkBase,
                  pathname.startsWith("/tags") ? linkActive : linkInactive,
                )}
              >
                <Tags className="h-4 w-4" />
                Tags
              </Link>
              <Link
                href="/approvals"
                className={cn(
                  linkBase,
                  pathname.startsWith("/approvals") ? linkActive : linkInactive,
                )}
              >
                <CheckCircle2 className="h-4 w-4" />
                Approvals
              </Link>
              {isAdmin ? (
                <Link
                  href="/custom-fields"
                  className={cn(
                    linkBase,
                    pathname.startsWith("/custom-fields")
                      ? linkActive
                      : linkInactive,
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
                <p className={sectionLabel}>Skills</p>
                <div className="mt-1 space-y-1">
                  <Link
                    href="/skills/marketplace"
                    className={cn(
                      linkBase,
                      pathname === "/skills" ||
                        pathname.startsWith("/skills/marketplace")
                        ? linkActive
                        : linkInactive,
                    )}
                  >
                    <Store className="h-4 w-4" />
                    Marketplace
                  </Link>
                  <Link
                    href="/skills/packs"
                    className={cn(
                      linkBase,
                      pathname.startsWith("/skills/packs")
                        ? linkActive
                        : linkInactive,
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
            <p className={sectionLabel}>Administration</p>
            <div className="mt-1 space-y-1">
              <Link
                href="/organization"
                className={cn(
                  linkBase,
                  pathname.startsWith("/organization")
                    ? linkActive
                    : linkInactive,
                )}
              >
                <Building2 className="h-4 w-4" />
                Organization
              </Link>
              {isAdmin ? (
                <Link
                  href="/gateways"
                  className={cn(
                    linkBase,
                    pathname.startsWith("/gateways")
                      ? linkActive
                      : linkInactive,
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
                    linkBase,
                    pathname.startsWith("/agents") ? linkActive : linkInactive,
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
      <div className="border-t border-[var(--border)] p-4">
        <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              systemStatus === "operational" && "bg-[var(--success)]",
              systemStatus === "degraded" && "bg-[var(--danger)]",
              systemStatus === "unknown" && "bg-[var(--text-quiet)]",
            )}
          />
          {statusLabel}
        </div>
      </div>
    </aside>
  );
}
