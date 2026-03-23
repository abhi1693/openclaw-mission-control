"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/components/providers/ThemeProvider";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, toggleTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="h-10 w-10 rounded-full border border-[color:var(--border)] bg-[color:var(--surface)] p-0 hover:bg-[color:var(--surface-strong)]"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
