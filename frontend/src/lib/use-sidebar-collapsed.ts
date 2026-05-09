import { useCallback, useSyncExternalStore } from "react";

export const SIDEBAR_COLLAPSED_STORAGE_KEY = "mc.sidebar.collapsed";
const SIDEBAR_COLLAPSED_EVENT = "mc:sidebar-collapsed-change";

const getSnapshot = (): boolean => {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
};

// SSR returns the same default as the first client paint to avoid a
// hydration mismatch. The actual stored value is applied after mount.
const getServerSnapshot = (): boolean => false;

const subscribe = (callback: () => void): (() => void) => {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(SIDEBAR_COLLAPSED_EVENT, callback);
  // Cross-tab sync via the standard storage event.
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(SIDEBAR_COLLAPSED_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
};

export function useSidebarCollapsed(): [boolean, (next: boolean) => void] {
  const collapsed = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const setCollapsed = useCallback((next: boolean) => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      SIDEBAR_COLLAPSED_STORAGE_KEY,
      next ? "true" : "false",
    );
    window.dispatchEvent(
      new CustomEvent<boolean>(SIDEBAR_COLLAPSED_EVENT, { detail: next }),
    );
  }, []);

  return [collapsed, setCollapsed];
}
