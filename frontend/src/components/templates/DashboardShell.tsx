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
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

  // Close sidebar on navigation
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

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
      window.location.reload();
    };

    window.addEventListener("storage", handleStorage);

    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel("org-switch");
      channel.onmessage = () => {
        window.location.reload();
      };
    }

    return () => {
      window.removeEventListener("storage", handleStorage);
      channel?.close();
    };
  }, []);

  const toggleSidebar = useCallback(() => setSidebarOpen((v) => !v), []);

  return (
    <div className="min-h-screen bg-app text-strong" data-sidebar={sidebarOpen ? "open" : "closed"}>
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white shadow-sm">
        <div className="flex items-center py-3">
          <div className="flex items-center px-4 md:px-6 md:w-[260px]">
            <button
              type="button"
              className="mr-3 rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden"
              onClick={toggleSidebar}
              aria-label="Toggle navigation"
            >
              {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <BrandMark />
          </div>
          <SignedIn>
            <div className="hidden md:flex flex-1 items-center">
              <div className="max-w-[220px]">
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
          className="fixed inset-0 z-30 bg-black/30 md:hidden"
          onClick={toggleSidebar}
          onKeyDown={(e) => e.key === "Escape" && toggleSidebar()}
          role="button"
          tabIndex={-1}
          aria-label="Close navigation"
        />
      ) : null}

      <div className="grid min-h-[calc(100vh-64px)] grid-cols-1 md:grid-cols-[260px_1fr] bg-slate-50">
        {children}
      </div>
    </div>
  );
}
