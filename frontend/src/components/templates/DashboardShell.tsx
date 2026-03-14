"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";

import { SignedIn, useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type getMeApiV1UsersMeGetResponse,
  useGetMeApiV1UsersMeGet,
} from "@/api/generated/users/users";
import { BrandMark } from "@/components/atoms/BrandMark";
import { OrgSwitcher } from "@/components/organisms/OrgSwitcher";
import { UserMenu } from "@/components/organisms/UserMenu";
import { isOnboardingComplete } from "@/lib/onboarding";

export function DashboardShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { isSignedIn } = useAuth();
  const isOnboardingPath = pathname === "/onboarding";
  const [sidebarState, setSidebarState] = useState({ open: false, path: pathname });
  // Close sidebar on navigation using React's "store info from previous
  // renders" pattern — conditional setState during render resets immediately
  // without extra commits, avoiding both set-state-in-effect and refs rules.
  if (sidebarState.path !== pathname) {
    setSidebarState({ open: false, path: pathname });
  }
  const sidebarOpen = sidebarState.open;

  const meQuery = useGetMeApiV1UsersMeGet<
    getMeApiV1UsersMeGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn) && !isOnboardingPath,
      retry: false,
      refetchOnMount: "always",
    },
  });
  const profile = meQuery.data?.status === 200 ? meQuery.data.data : null;
  const displayName = profile?.name ?? profile?.preferred_name ?? "Operator";
  const displayEmail = profile?.email ?? "";

  useEffect(() => {
    if (!isSignedIn || isOnboardingPath) return;
    if (!profile) return;
    if (!isOnboardingComplete(profile)) {
      router.replace("/onboarding");
    }
  }, [isOnboardingPath, isSignedIn, profile, router]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== "openclaw_org_switch" || !event.newValue) return;
      // 使用客户端路由刷新替代全页刷新，提升性能
      router.refresh();
    };

    window.addEventListener("storage", handleStorage);

    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel("org-switch");
      channel.onmessage = () => {
        // 使用客户端路由刷新替代全页刷新，提升性能
        router.refresh();
      };
    }

    return () => {
      window.removeEventListener("storage", handleStorage);
      channel?.close();
    };
  }, [router]);

  const toggleSidebar = useCallback(
    () => setSidebarState((prev) => ({ open: !prev.open, path: pathname })),
    [pathname],
  );

  // Dismiss sidebar on Escape
  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSidebarState((prev) => ({ ...prev, open: false }));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sidebarOpen]);

  return (
    <div className="min-h-screen bg-app text-strong" data-sidebar={sidebarOpen ? "open" : "closed"}>
      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white shadow-sm">
        <div className="flex items-center py-3">
          <div className="flex items-center px-4 md:px-6 md:w-[260px]">
            {isSignedIn ? (
              <button
                type="button"
                className="mr-2 rounded-lg p-2 text-slate-600 hover:bg-slate-100 active:bg-slate-200 md:hidden touch-manipulation"
                onClick={toggleSidebar}
                aria-label="Toggle navigation"
                aria-expanded={sidebarOpen}
              >
                {sidebarOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
              </button>
            ) : null}
            <BrandMark />
          </div>
          <SignedIn>
            {/* 移动端使用更紧凑的 OrgSwitcher 样式 */}
            <div className="flex flex-1 items-center overflow-hidden md:block">
              <div className="min-w-0 max-w-[120px] md:max-w-[220px]">
                <OrgSwitcher />
              </div>
            </div>
          </SignedIn>
          <SignedIn>
            <div className="ml-auto flex items-center gap-3 px-4 md:px-6">
              <div className="hidden text-right lg:block">
                <p className="text-sm font-semibold text-slate-900">
                  {displayName}
                </p>
                <p className="text-xs text-slate-500">Operator</p>
              </div>
              <UserMenu displayName={displayName} displayEmail={displayEmail} />
            </div>
          </SignedIn>
        </div>
      </header>

      {/* Mobile sidebar overlay */}
      {sidebarOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          onClick={toggleSidebar}
          aria-hidden="true"
          data-cy="sidebar-backdrop"
        />
      ) : null}

      <div className="grid min-h-[calc(100vh-64px)] grid-cols-1 md:grid-cols-[260px_1fr] bg-slate-50">
        {children}
      </div>
    </div>
  );
}
