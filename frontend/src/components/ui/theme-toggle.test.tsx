import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ThemeToggle } from "./theme-toggle";

// ---------- mocks ----------

const setThemeMock = vi.hoisted(() => vi.fn());
const useThemeMock = vi.hoisted(() =>
  vi.fn().mockReturnValue({
    theme: "system",
    resolvedTheme: "light",
    setTheme: setThemeMock,
  }),
);

vi.mock("@/components/providers/ThemeProvider", () => ({
  useTheme: useThemeMock,
}));

// ---------- suite ----------

describe("ThemeToggle", () => {
  beforeEach(() => {
    setThemeMock.mockReset();
    useThemeMock.mockReturnValue({
      theme: "system",
      resolvedTheme: "light",
      setTheme: setThemeMock,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders all three theme options", () => {
    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: /light theme/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dark theme/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /system theme/i })).toBeInTheDocument();
  });

  it("renders a container with accessible label", () => {
    render(<ThemeToggle />);

    expect(screen.getByLabelText(/theme selection/i)).toBeInTheDocument();
  });

  it("marks the current theme as checked via aria-pressed", () => {
    useThemeMock.mockReturnValue({
      theme: "system",
      resolvedTheme: "light",
      setTheme: setThemeMock,
    });

    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: /system theme/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /light theme/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: /dark theme/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("marks dark as checked when theme is dark", () => {
    useThemeMock.mockReturnValue({
      theme: "dark",
      resolvedTheme: "dark",
      setTheme: setThemeMock,
    });

    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: /dark theme/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /light theme/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: /system theme/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("marks light as checked when theme is light", () => {
    useThemeMock.mockReturnValue({
      theme: "light",
      resolvedTheme: "light",
      setTheme: setThemeMock,
    });

    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: /light theme/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("calls setTheme with 'dark' when dark option is clicked", async () => {
    const user = userEvent.setup();

    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: /dark theme/i }));

    expect(setThemeMock).toHaveBeenCalledTimes(1);
    expect(setThemeMock).toHaveBeenCalledWith("dark");
  });

  it("calls setTheme with 'light' when light option is clicked", async () => {
    const user = userEvent.setup();
    useThemeMock.mockReturnValue({
      theme: "dark",
      resolvedTheme: "dark",
      setTheme: setThemeMock,
    });

    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: /light theme/i }));

    expect(setThemeMock).toHaveBeenCalledTimes(1);
    expect(setThemeMock).toHaveBeenCalledWith("light");
  });

  it("calls setTheme with 'system' when system option is clicked", async () => {
    const user = userEvent.setup();
    useThemeMock.mockReturnValue({
      theme: "dark",
      resolvedTheme: "dark",
      setTheme: setThemeMock,
    });

    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: /system theme/i }));

    expect(setThemeMock).toHaveBeenCalledTimes(1);
    expect(setThemeMock).toHaveBeenCalledWith("system");
  });

  it("displays text labels for each option", () => {
    render(<ThemeToggle />);

    expect(screen.getByText("Light")).toBeInTheDocument();
    expect(screen.getByText("Dark")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
  });

  it("applies custom className when provided", () => {
    const { container } = render(<ThemeToggle className="custom-class" />);

    expect(container.firstChild).toHaveClass("custom-class");
  });

  it("does not call setTheme when clicking the already-active option", async () => {
    const user = userEvent.setup();
    useThemeMock.mockReturnValue({
      theme: "system",
      resolvedTheme: "light",
      setTheme: setThemeMock,
    });

    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: /system theme/i }));

    expect(setThemeMock).not.toHaveBeenCalled();
  });
});
