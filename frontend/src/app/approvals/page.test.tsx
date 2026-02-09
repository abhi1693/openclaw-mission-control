import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import GlobalApprovalsPage from "./page";
import { AuthProvider } from "@/components/providers/AuthProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";

vi.mock("next/navigation", () => ({
  usePathname: () => "/approvals",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("next/link", () => {
  type LinkProps = React.PropsWithChildren<{
    href: string | { pathname?: string };
  }> &
    Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

  return {
    default: ({ href, children, ...props }: LinkProps) => (
      <a href={typeof href === "string" ? href : "#"} {...props}>
        {children}
      </a>
    ),
  };
});

vi.mock("@clerk/nextjs", () => {
  return {
    ClerkProvider: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    SignedIn: () => {
      throw new Error(
        "@clerk/nextjs SignedIn rendered (unexpected in secretless mode)",
      );
    },
    SignedOut: () => {
      throw new Error("@clerk/nextjs SignedOut rendered without ClerkProvider");
    },
    SignInButton: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    SignOutButton: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    useAuth: () => ({ isLoaded: true, isSignedIn: false }),
    useUser: () => ({ isLoaded: true, isSignedIn: false, user: null }),
  };
});

describe("/approvals auth boundary", () => {
  it("renders without ClerkProvider runtime errors when publishable key is a placeholder", () => {
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY = "placeholder";

    render(
      <AuthProvider>
        <QueryProvider>
          <GlobalApprovalsPage />
        </QueryProvider>
      </AuthProvider>,
    );

    expect(screen.getByText(/sign in to view approvals/i)).toBeInTheDocument();
  });
});
