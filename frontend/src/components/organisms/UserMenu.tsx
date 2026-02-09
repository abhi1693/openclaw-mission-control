"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { SignOutButton, useUser } from "@/auth/clerk";
import {
  Activity,
  Bot,
  ChevronDown,
  LayoutDashboard,
  LogOut,
  Plus,
  Server,
  Settings,
  Trello,
} from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type UserMenuProps = {
  className?: string;
  displayName?: string;
  displayEmail?: string;
};

export function UserMenu({
  className,
  displayName: displayNameFromDb,
  displayEmail: displayEmailFromDb,
}: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const { user } = useUser();
  const isLocalAuth = !!process.env.NEXT_PUBLIC_LOCAL_AUTH_TOKEN;

  // Show menu for local auth even without Clerk user
  if (!user && !isLocalAuth) return null;

  // Use generic display for local auth, Clerk user data otherwise
  const avatarUrl = isLocalAuth ? null : (user?.imageUrl ?? null);
  const avatarLabel = isLocalAuth
    ? "L"
    : (displayNameFromDb?.slice(0, 1).toUpperCase() ?? user?.firstName?.[0] ?? user?.username?.[0] ?? "U");
  const displayName = isLocalAuth
    ? "Local User"
    : (displayNameFromDb ?? user?.fullName ?? user?.firstName ?? user?.username ?? "Account");
  const displayEmail = isLocalAuth
    ? "local@mission-control"
    : (displayEmailFromDb ?? user?.primaryEmailAddress?.emailAddress ?? "");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "group inline-flex h-9 items-center gap-2 rounded-[10px] bg-transparent px-1 py-1 transition",
            "hover:bg-white/70",
            // Avoid the default browser focus outline (often bright blue) on click.
            // Keep a subtle, enterprise-looking focus ring for keyboard navigation.
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--neutral-300,var(--border-strong))] focus-visible:ring-offset-2 focus-visible:ring-offset-white",
            "data-[state=open]:bg-white",
            className,
          )}
          aria-label="Open user menu"
        >
          <span
            className={cn(
              "relative flex h-9 w-9 items-center justify-center overflow-hidden rounded-[10px] text-xs font-semibold text-white shadow-sm",
              avatarUrl
                ? "bg-[color:var(--neutral-200,var(--surface-muted))]"
                : "bg-gradient-to-br from-[color:var(--primary-navy,var(--accent))] to-[color:var(--secondary-navy,var(--accent-strong))]",
            )}
          >
            {avatarUrl ? (
              <Image
                src={avatarUrl}
                alt="User avatar"
                width={36}
                height={36}
                className="h-9 w-9 object-cover"
              />
            ) : (
              avatarLabel
            )}
          </span>
          <ChevronDown className="h-4 w-4 text-[color:var(--neutral-700,var(--text-quiet))] transition group-data-[state=open]:rotate-180" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={12}
        className="w-80 overflow-hidden rounded-2xl border border-[color:var(--neutral-200,var(--border))] bg-white/95 p-0 shadow-[0_8px_32px_rgba(10,22,40,0.08)] backdrop-blur"
      >
        <div className="border-b border-[color:var(--neutral-200,var(--border))] px-4 py-3">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "flex h-10 w-10 items-center justify-center overflow-hidden rounded-xl text-sm font-semibold text-white",
                avatarUrl
                  ? "bg-[color:var(--neutral-200,var(--surface-muted))]"
                  : "bg-gradient-to-br from-[color:var(--primary-navy,var(--accent))] to-[color:var(--secondary-navy,var(--accent-strong))]",
              )}
            >
              {avatarUrl ? (
                <Image
                  src={avatarUrl}
                  alt="User avatar"
                  width={40}
                  height={40}
                  className="h-10 w-10 object-cover"
                />
              ) : (
                avatarLabel
              )}
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-[color:var(--primary-navy,var(--text))]">
                {displayName}
              </div>
              {displayEmail ? (
                <div className="truncate text-xs text-[color:var(--neutral-700,var(--text-muted))]">
                  {displayEmail}
                </div>
              ) : null}
            </div>
          </div>
        </div>
        <div className="p-2">
          <div className="grid grid-cols-2 gap-2">
            <Link
              href="/boards"
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-[color:var(--neutral-300,var(--border-strong))] bg-white px-3 py-2 text-sm font-semibold text-[color:var(--neutral-800,var(--text))] transition hover:border-[color:var(--primary-navy,var(--accent-strong))] hover:bg-[color:var(--neutral-100,var(--surface-muted))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent-teal,var(--accent))] focus-visible:ring-offset-2"
              onClick={() => setOpen(false)}
            >
              <Trello className="h-4 w-4 text-[color:var(--neutral-700,var(--text-quiet))]" />
              Open boards
            </Link>
            <Link
              href="/boards/new"
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-[color:var(--primary-navy,var(--accent))] px-3 py-2 text-sm font-semibold text-white shadow-[0_2px_8px_rgba(10,22,40,0.15)] transition hover:bg-[color:var(--secondary-navy,var(--accent-strong))] hover:translate-y-[-1px] hover:shadow-[0_4px_12px_rgba(10,22,40,0.20)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent-teal,var(--accent))] focus-visible:ring-offset-2"
              onClick={() => setOpen(false)}
            >
              <Plus className="h-4 w-4 opacity-90" />
              Create board
            </Link>
          </div>

          <div className="my-2 h-px bg-[color:var(--neutral-200,var(--border))]" />

          {(
            [
              { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
              { href: "/activity", label: "Activity", icon: Activity },
              { href: "/agents", label: "Agents", icon: Bot },
              { href: "/gateways", label: "Gateways", icon: Server },
              { href: "/settings", label: "Settings", icon: Settings },
            ] as const
          ).map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-[color:var(--neutral-800,var(--text))] transition hover:bg-[color:var(--neutral-100,var(--surface-muted))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent-teal,var(--accent))] focus-visible:ring-offset-2"
              onClick={() => setOpen(false)}
            >
              <item.icon className="h-4 w-4 text-[color:var(--neutral-700,var(--text-quiet))]" />
              {item.label}
            </Link>
          ))}

          <div className="my-2 h-px bg-[color:var(--neutral-200,var(--border))]" />

          {!isLocalAuth ? (
            <SignOutButton>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-[color:var(--neutral-800,var(--text))] transition hover:bg-[color:var(--neutral-100,var(--surface-muted))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent-teal,var(--accent))] focus-visible:ring-offset-2"
                onClick={() => setOpen(false)}
              >
                <LogOut className="h-4 w-4 text-[color:var(--neutral-700,var(--text-quiet))]" />
                Sign out
              </button>
            </SignOutButton>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
