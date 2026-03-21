import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ThemeProvider, useTheme, THEME_STORAGE_KEY } from "./ThemeProvider";

// ---------- helpers ----------

/** A small consumer component that exposes the context for assertions. */
function ThemeConsumer() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
      <button type="button" onClick={() => setTheme("light")}>
        set-light
      </button>
      <button type="button" onClick={() => setTheme("dark")}>
        set-dark
      </button>
      <button type="button" onClick={() => setTheme("system")}>
        set-system
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <ThemeProvider>
      <ThemeConsumer />
    </ThemeProvider>,
  );
}

// ---------- mocks ----------

let matchMediaListeners: Array<() => void> = [];
let prefersColorSchemeDark = false;

function createMatchMediaMock() {
  return vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" && prefersColorSchemeDark,
    media: query,
    addEventListener: (_event: string, handler: () => void) => {
      matchMediaListeners.push(handler);
    },
    removeEventListener: (_event: string, handler: () => void) => {
      matchMediaListeners = matchMediaListeners.filter((h) => h !== handler);
    },
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// ---------- suite ----------

describe("ThemeProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    prefersColorSchemeDark = false;
    matchMediaListeners = [];
    vi.stubGlobal("matchMedia", createMatchMediaMock());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to system theme and resolves to light when OS prefers light", () => {
    prefersColorSchemeDark = false;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();

    expect(screen.getByTestId("theme").textContent).toBe("system");
    expect(screen.getByTestId("resolved").textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("defaults to system theme and resolves to dark when OS prefers dark", () => {
    prefersColorSchemeDark = true;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();

    expect(screen.getByTestId("theme").textContent).toBe("system");
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("reads persisted theme from localStorage on mount", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");

    renderWithProvider();

    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("ignores invalid localStorage values and falls back to system", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "invalid-value");
    prefersColorSchemeDark = false;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();

    expect(screen.getByTestId("theme").textContent).toBe("system");
    expect(screen.getByTestId("resolved").textContent).toBe("light");
  });

  it("persists theme to localStorage when setTheme is called", async () => {
    const user = userEvent.setup();

    renderWithProvider();

    await user.click(screen.getByRole("button", { name: "set-dark" }));

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("toggles dark class correctly when switching between themes", async () => {
    const user = userEvent.setup();

    renderWithProvider();

    // Switch to dark
    await user.click(screen.getByRole("button", { name: "set-dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // Switch to light
    await user.click(screen.getByRole("button", { name: "set-light" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(screen.getByTestId("resolved").textContent).toBe("light");
  });

  it("responds to OS color scheme changes when set to system", async () => {
    prefersColorSchemeDark = false;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();
    expect(screen.getByTestId("resolved").textContent).toBe("light");

    // Simulate OS switching to dark mode
    prefersColorSchemeDark = true;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    act(() => {
      matchMediaListeners.forEach((fn) => fn());
    });

    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("does NOT respond to OS changes when theme is explicitly set to light", async () => {
    const user = userEvent.setup();
    prefersColorSchemeDark = false;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();

    await user.click(screen.getByRole("button", { name: "set-light" }));

    // Simulate OS switching to dark mode
    prefersColorSchemeDark = true;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    act(() => {
      matchMediaListeners.forEach((fn) => fn());
    });

    // Should remain light because user explicitly chose light
    expect(screen.getByTestId("resolved").textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("does NOT respond to OS changes when theme is explicitly set to dark", async () => {
    const user = userEvent.setup();
    prefersColorSchemeDark = true;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();

    await user.click(screen.getByRole("button", { name: "set-dark" }));

    // Simulate OS switching to light mode
    prefersColorSchemeDark = false;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    act(() => {
      matchMediaListeners.forEach((fn) => fn());
    });

    // Should remain dark because user explicitly chose dark
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("throws when useTheme is called outside of ThemeProvider", () => {
    // Suppress React error boundary console output for this test
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<ThemeConsumer />)).toThrow(
      "useTheme must be used within a <ThemeProvider>",
    );

    consoleSpy.mockRestore();
  });

  it("switches from explicit dark back to system and re-evaluates OS preference", async () => {
    const user = userEvent.setup();
    prefersColorSchemeDark = false;
    vi.stubGlobal("matchMedia", createMatchMediaMock());

    renderWithProvider();

    // Set to dark explicitly
    await user.click(screen.getByRole("button", { name: "set-dark" }));
    expect(screen.getByTestId("resolved").textContent).toBe("dark");

    // Switch back to system (OS is light)
    await user.click(screen.getByRole("button", { name: "set-system" }));
    expect(screen.getByTestId("theme").textContent).toBe("system");
    expect(screen.getByTestId("resolved").textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
  });
});
