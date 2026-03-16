import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { useUrlSorting } from "./use-url-sorting";

const replaceMock = vi.fn();
let mockPathname = "/agents";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: replaceMock,
  }),
  usePathname: () => mockPathname,
}));

describe("useUrlSorting", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    mockPathname = "/agents";
    window.history.replaceState({}, "", "/agents");
  });

  it("uses default sorting when no params are present", () => {
    const { result } = renderHook(() =>
      useUrlSorting({
        allowedColumnIds: ["name", "status"],
        defaultSorting: [{ id: "name", desc: false }],
        paramPrefix: "agents",
      }),
    );

    expect(result.current.sorting).toEqual([{ id: "name", desc: false }]);
  });

  it("reads sorting from URL params", () => {
    window.history.replaceState(
      {},
      "",
      "/agents?agents_sort=status&agents_dir=desc",
    );

    const { result } = renderHook(() =>
      useUrlSorting({
        allowedColumnIds: ["name", "status"],
        defaultSorting: [{ id: "name", desc: false }],
        paramPrefix: "agents",
      }),
    );

    expect(result.current.sorting).toEqual([{ id: "status", desc: true }]);
  });

  it("writes updated sorting to URL and preserves unrelated params", () => {
    window.history.replaceState({}, "", "/agents?foo=1");

    const { result } = renderHook(() =>
      useUrlSorting({
        allowedColumnIds: ["name", "status"],
        defaultSorting: [{ id: "name", desc: false }],
        paramPrefix: "agents",
      }),
    );

    act(() => {
      result.current.onSortingChange([{ id: "status", desc: true }]);
    });

    expect(replaceMock).toHaveBeenCalledWith(
      "/agents?foo=1&agents_sort=status&agents_dir=desc",
      {
        scroll: false,
      },
    );
  });

  it("removes sorting params when returning to default sorting", () => {
    window.history.replaceState(
      {},
      "",
      "/agents?foo=1&agents_sort=status&agents_dir=desc",
    );

    const { result } = renderHook(() =>
      useUrlSorting({
        allowedColumnIds: ["name", "status"],
        defaultSorting: [{ id: "name", desc: false }],
        paramPrefix: "agents",
      }),
    );

    act(() => {
      result.current.onSortingChange([{ id: "name", desc: false }]);
    });

    expect(replaceMock).toHaveBeenCalledWith("/agents?foo=1", {
      scroll: false,
    });
  });

  it("supports explicit no-sorting state via sentinel", () => {
    window.history.replaceState({}, "", "/agents?agents_sort=none");

    const { result } = renderHook(() =>
      useUrlSorting({
        allowedColumnIds: ["name", "status"],
        defaultSorting: [{ id: "name", desc: false }],
        paramPrefix: "agents",
      }),
    );

    expect(result.current.sorting).toEqual([]);

    act(() => {
      result.current.onSortingChange([]);
    });

    expect(replaceMock).not.toHaveBeenCalled();
  });
});
