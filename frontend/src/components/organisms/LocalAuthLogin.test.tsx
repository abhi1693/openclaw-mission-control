import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LocalAuthLogin } from "./LocalAuthLogin";

const setLocalAuthTokenMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/auth/localAuth", async () => {
  const actual =
    await vi.importActual<typeof import("@/auth/localAuth")>(
      "@/auth/localAuth",
    );
  return {
    ...actual,
    setLocalAuthToken: setLocalAuthTokenMock,
  };
});

describe("LocalAuthLogin", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    setLocalAuthTokenMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000/");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("requires a non-empty token", async () => {
    const user = userEvent.setup();
    render(<LocalAuthLogin />);

    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText("Bearer token is required.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(setLocalAuthTokenMock).not.toHaveBeenCalled();
  });

  it("requires token length of at least 50 characters", async () => {
    const user = userEvent.setup();
    render(<LocalAuthLogin />);

    await user.type(screen.getByPlaceholderText("Paste token"), "x".repeat(49));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(
      screen.getByText("Bearer token must be at least 50 characters."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(setLocalAuthTokenMock).not.toHaveBeenCalled();
  });

  it("rejects invalid token values", async () => {
    const onAuthenticatedMock = vi.fn();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    const user = userEvent.setup();
    render(<LocalAuthLogin onAuthenticated={onAuthenticatedMock} />);

    await user.type(screen.getByPlaceholderText("Paste token"), "x".repeat(50));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(screen.getByText("Token is invalid.")).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/users/me",
      expect.objectContaining({
        method: "GET",
        headers: { Authorization: `Bearer ${"x".repeat(50)}` },
      }),
    );
    expect(setLocalAuthTokenMock).not.toHaveBeenCalled();
    expect(onAuthenticatedMock).not.toHaveBeenCalled();
  });

  it("saves token only after successful backend validation", async () => {
    const onAuthenticatedMock = vi.fn();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 200 }));
    const user = userEvent.setup();
    render(<LocalAuthLogin onAuthenticated={onAuthenticatedMock} />);

    const token = `  ${"g".repeat(50)} `;
    await user.type(screen.getByPlaceholderText("Paste token"), token);
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(setLocalAuthTokenMock).toHaveBeenCalledWith("g".repeat(50)),
    );
    expect(onAuthenticatedMock).toHaveBeenCalledTimes(1);
  });

  it("shows a clear error when backend is unreachable", async () => {
    const onAuthenticatedMock = vi.fn();
    fetchMock.mockRejectedValueOnce(new TypeError("network error"));
    const user = userEvent.setup();
    render(<LocalAuthLogin onAuthenticated={onAuthenticatedMock} />);

    await user.type(screen.getByPlaceholderText("Paste token"), "t".repeat(50));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(
        screen.getByText("Unable to reach backend to validate token."),
      ).toBeInTheDocument(),
    );
    expect(setLocalAuthTokenMock).not.toHaveBeenCalled();
    expect(onAuthenticatedMock).not.toHaveBeenCalled();
  });
});
