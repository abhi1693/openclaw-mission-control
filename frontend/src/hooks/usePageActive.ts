"use client";

import { useEffect, useState } from "react";

const computeIsActive = () => {
  if (typeof document === "undefined") return true;
  const visible =
    document.visibilityState === "visible" &&
    // `hidden` is a more widely-supported signal; keep both for safety.
    !document.hidden;
  const focused =
    typeof document.hasFocus === "function" ? document.hasFocus() : true;
  return visible && focused;
};

/**
 * Returns true when this tab/window is both visible and focused.
 *
 * Rationale: background tabs/windows should not keep long-lived connections
 * (SSE/polling), otherwise opening multiple tabs can exhaust per-origin
 * connection limits and make the app feel "hung".
 */
export function usePageActive(): boolean {
  const [active, setActive] = useState<boolean>(() => computeIsActive());

  useEffect(() => {
    const update = () => setActive(computeIsActive());

    update();
    document.addEventListener("visibilitychange", update);
    window.addEventListener("focus", update);
    window.addEventListener("blur", update);

    return () => {
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("focus", update);
      window.removeEventListener("blur", update);
    };
  }, []);

  return active;
}
