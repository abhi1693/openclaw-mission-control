"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Theme = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";

type ThemeContextValue = {
  /** The user-selected preference: light, dark, or system. */
  theme: Theme;
  /** The actual applied theme after resolving "system" to light or dark. */
  resolvedTheme: ResolvedTheme;
  /** Update the theme preference. Persists to localStorage. */
  setTheme: (theme: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export const THEME_STORAGE_KEY = "mc-theme";

function isValidTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

function getSystemPreference(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function resolveTheme(preference: Theme): ResolvedTheme {
  if (preference === "system") {
    return getSystemPreference();
  }
  return preference;
}

function applyClassToDocument(resolved: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isValidTheme(stored)) return stored;
  } catch {
    // localStorage may be unavailable (e.g. private browsing quota exceeded).
  }
  return "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Lazy initializer: read persisted preference on first render without
  // triggering a cascading setState inside an effect.
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);

  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => {
    const initial = readStoredTheme();
    return resolveTheme(initial);
  });

  // Sync the `dark` class on <html> whenever the resolved theme changes.
  useEffect(() => {
    applyClassToDocument(resolvedTheme);
  }, [resolvedTheme]);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, newTheme);
    } catch {
      // localStorage may be unavailable.
    }
    const resolved = resolveTheme(newTheme);
    setResolvedTheme(resolved);
    applyClassToDocument(resolved);
  }, []);

  // Listen for OS-level color scheme changes when preference is "system".
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      let current: string | null = null;
      try {
        current = localStorage.getItem(THEME_STORAGE_KEY);
      } catch {
        // Ignore.
      }
      if (!current || current === "system") {
        const resolved = resolveTheme("system");
        setResolvedTheme(resolved);
        applyClassToDocument(resolved);
      }
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

/**
 * Access the current theme context.
 * Must be used within a `<ThemeProvider>`.
 */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a <ThemeProvider>");
  }
  return ctx;
}
