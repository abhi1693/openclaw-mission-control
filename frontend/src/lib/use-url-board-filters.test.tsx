import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { useUrlBoardFilters } from "./use-url-board-filters";

const replaceMock = vi.fn();
let mockPathname = "/boards/abc";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: replaceMock,
  }),
  usePathname: () => mockPathname,
}));

describe("useUrlBoardFilters", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    mockPathname = "/boards/abc";
    window.history.replaceState({}, "", "/boards/abc");
  });

  it("returns empty filters when no URL params are present", () => {
    const { result } = renderHook(() => useUrlBoardFilters());
    expect(result.current.filters).toEqual({});
  });

  it("reads filter values from URL params (AC-2)", () => {
    window.history.replaceState({}, "", "/boards/abc?sprint=33&type=feature");

    const { result } = renderHook(() => useUrlBoardFilters());
    expect(result.current.filters).toEqual({ sprint: "33", type: "feature" });
  });

  it("writes filter changes to URL and preserves unrelated params (AC-1)", () => {
    window.history.replaceState({}, "", "/boards/abc?taskId=t1");

    const { result } = renderHook(() => useUrlBoardFilters());

    act(() => {
      result.current.setFilters({ sprint: "33", type: "feature" });
    });

    expect(replaceMock).toHaveBeenCalledWith(
      "/boards/abc?taskId=t1&sprint=33&type=feature",
      { scroll: false },
    );
  });

  it("removes filter params when filters are cleared", () => {
    window.history.replaceState(
      {},
      "",
      "/boards/abc?taskId=t1&sprint=33&type=feature",
    );

    const { result } = renderHook(() => useUrlBoardFilters());

    act(() => {
      result.current.setFilters({});
    });

    expect(replaceMock).toHaveBeenCalledWith("/boards/abc?taskId=t1", {
      scroll: false,
    });
  });

  it("ignores unknown URL param keys silently", () => {
    window.history.replaceState(
      {},
      "",
      "/boards/abc?sprint=33&bogus=xyz&foo=bar",
    );

    const { result } = renderHook(() => useUrlBoardFilters());
    expect(result.current.filters).toEqual({ sprint: "33" });
  });

  it("ignores empty param values", () => {
    window.history.replaceState({}, "", "/boards/abc?sprint=&type=feature");

    const { result } = renderHook(() => useUrlBoardFilters());
    expect(result.current.filters).toEqual({ type: "feature" });
  });

  it("ignores invalid values when allowedValues is provided (AC-4)", () => {
    window.history.replaceState(
      {},
      "",
      "/boards/abc?sprint=33&priority=banana",
    );

    const { result } = renderHook(() =>
      useUrlBoardFilters({
        allowedValues: {
          priority: new Set(["low", "medium", "high"]),
        },
      }),
    );

    // sprint has no allowedValues constraint → accepted as-is.
    // priority "banana" is invalid → silently dropped.
    expect(result.current.filters).toEqual({ sprint: "33" });
  });

  it("syncs on popstate (AC-3)", () => {
    const { result } = renderHook(() => useUrlBoardFilters());
    expect(result.current.filters).toEqual({});

    // Simulate browser back/forward.
    act(() => {
      window.history.replaceState({}, "", "/boards/abc?sprint=32");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(result.current.filters).toEqual({ sprint: "32" });
  });

  it("handles all supported filter keys", () => {
    window.history.replaceState(
      {},
      "",
      "/boards/abc?assignee=dev-1&priority=high&tag=bug&sprint=33&type=feature&epic=auth",
    );

    const { result } = renderHook(() => useUrlBoardFilters());
    expect(result.current.filters).toEqual({
      assignee: "dev-1",
      priority: "high",
      tag: "bug",
      sprint: "33",
      type: "feature",
      epic: "auth",
    });
  });
});
