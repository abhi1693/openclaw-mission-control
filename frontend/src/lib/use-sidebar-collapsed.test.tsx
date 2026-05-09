import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { SIDEBAR_COLLAPSED_STORAGE_KEY, useSidebarCollapsed } from "./use-sidebar-collapsed";

describe("useSidebarCollapsed", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("defaults to expanded (false) when no stored value", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(false);
  });

  it("hydrates from localStorage when stored value is 'true'", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(true);
  });

  it("hydrates from localStorage when stored value is 'false'", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "false");
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(false);
  });

  it("ignores malformed stored value and stays expanded", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "garbage");
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(false);
  });

  it("setter updates state and writes to localStorage", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe("true");
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe("false");
  });

  it("synchronizes across hook instances in the same tab", () => {
    const a = renderHook(() => useSidebarCollapsed());
    const b = renderHook(() => useSidebarCollapsed());
    expect(a.result.current[0]).toBe(false);
    expect(b.result.current[0]).toBe(false);
    act(() => a.result.current[1](true));
    expect(a.result.current[0]).toBe(true);
    expect(b.result.current[0]).toBe(true);
  });
});
