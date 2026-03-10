"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type DashboardViewMode = "basic" | "advanced";

type DashboardViewContextValue = {
  mode: DashboardViewMode;
  setMode: (mode: DashboardViewMode) => void;
  isBasic: boolean;
  isAdvanced: boolean;
};

const STORAGE_KEY = "openclaw_dashboard_view_mode";

const DashboardViewContext = createContext<DashboardViewContextValue | null>(null);

export function DashboardViewProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<DashboardViewMode>("basic");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "basic" || stored === "advanced") {
      setModeState(stored);
    }
  }, []);

  const setMode = (nextMode: DashboardViewMode) => {
    setModeState(nextMode);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, nextMode);
    }
  };

  const value = useMemo(
    () => ({
      mode,
      setMode,
      isBasic: mode === "basic",
      isAdvanced: mode === "advanced",
    }),
    [mode],
  );

  return (
    <DashboardViewContext.Provider value={value}>
      {children}
    </DashboardViewContext.Provider>
  );
}

export function useDashboardView() {
  const context = useContext(DashboardViewContext);
  if (!context) {
    throw new Error("useDashboardView must be used within a DashboardViewProvider");
  }
  return context;
}
