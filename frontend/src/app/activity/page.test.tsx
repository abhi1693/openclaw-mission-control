import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import ActivityPage from "./page";
import { AuthProvider } from "@/components/providers/AuthProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";

vi.mock("next/navigation", () => ({
  usePathname: () => "/activity",
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

describe("/activity auth boundary", () => {
  it("renders local auth login when no token is set", () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "local";
    window.sessionStorage.clear();

    try {
      render(
        <AuthProvider>
          <QueryProvider>
            <ActivityPage />
          </QueryProvider>
        </AuthProvider>,
      );

      expect(
        screen.getByRole("heading", { name: /local authentication/i }),
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/access token/i)).toBeInTheDocument();
    } finally {
      window.sessionStorage.clear();
    }
  });
});
