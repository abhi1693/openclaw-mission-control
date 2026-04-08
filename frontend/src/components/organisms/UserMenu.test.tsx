import type {
  AnchorHTMLAttributes,
  ImgHTMLAttributes,
  PropsWithChildren,
  ReactNode,
} from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { UserMenu } from "./UserMenu";

const useUserMock = vi.hoisted(() => vi.fn());
const clearLocalAuthTokenMock = vi.hoisted(() => vi.fn());
const isLocalAuthModeMock = vi.hoisted(() => vi.fn());
type LinkProps = PropsWithChildren<{
  href: string | { pathname?: string };
}> &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

vi.mock("next/image", () => ({
  default: (props: ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img {...props} alt={props.alt ?? ""} />
  ),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: LinkProps) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/auth/clerk", () => ({
  useUser: useUserMock,
  SignOutButton: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@/auth/localAuth", () => ({
  clearLocalAuthToken: clearLocalAuthTokenMock,
  isLocalAuthMode: isLocalAuthModeMock,
}));

describe("UserMenu", () => {
  beforeEach(() => {
    useUserMock.mockReset();
    clearLocalAuthTokenMock.mockReset();
    isLocalAuthModeMock.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders and opens local-mode menu actions", async () => {
    const user = userEvent.setup();
    useUserMock.mockReturnValue({ user: null });
    isLocalAuthModeMock.mockReturnValue(true);

    render(
      <ThemeProvider>
        <UserMenu />
      </ThemeProvider>,
    );

    await user.click(screen.getByRole("button", { name: /open user menu/i }));

    expect(
      screen.getByRole("link", { name: /open boards/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /create board/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign out/i }),
    ).toBeInTheDocument();
  });

  it("clears local auth token and reloads on local sign out", async () => {
    const user = userEvent.setup();
    useUserMock.mockReturnValue({ user: null });
    isLocalAuthModeMock.mockReturnValue(true);
    const reloadSpy = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      reload: reloadSpy,
    } as Location);

    render(
      <ThemeProvider>
        <UserMenu />
      </ThemeProvider>,
    );

    await user.click(screen.getByRole("button", { name: /open user menu/i }));
    await user.click(screen.getByRole("button", { name: /sign out/i }));

    expect(clearLocalAuthTokenMock).toHaveBeenCalledTimes(1);
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });
});
