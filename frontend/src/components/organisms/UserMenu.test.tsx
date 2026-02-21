import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { UserMenu } from "./UserMenu";

const useUserMock = vi.hoisted(() => vi.fn());
const clearLocalAuthTokenMock = vi.hoisted(() => vi.fn());
const isLocalAuthModeMock = vi.hoisted(() => vi.fn());

vi.mock("next/image", () => ({
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img {...props} alt={props.alt ?? ""} />
  ),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href?: string;
    [key: string]: unknown;
  }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/auth/clerk", () => ({
  useUser: useUserMock,
  SignOutButton: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/auth/localAuth", () => ({
  clearLocalAuthToken: clearLocalAuthTokenMock,
  isLocalAuthMode: isLocalAuthModeMock,
}));

describe("UserMenu", () => {
  it("renders and opens local-mode menu actions", async () => {
    const user = userEvent.setup();
    useUserMock.mockReturnValue({ user: null });
    isLocalAuthModeMock.mockReturnValue(true);

    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /open user menu/i }));

    expect(screen.getByRole("link", { name: /open boards/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /create board/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });
});
