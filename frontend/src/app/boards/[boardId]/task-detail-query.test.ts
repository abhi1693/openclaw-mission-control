import { describe, expect, it } from "vitest";

import { buildUrlWithTaskId, withTaskIdSearchParam } from "./task-detail-query";

describe("task-detail-query", () => {
  it("adds taskId when absent", () => {
    expect(withTaskIdSearchParam("", "task-1")).toBe("?taskId=task-1");
  });

  it("replaces taskId while preserving other params", () => {
    expect(withTaskIdSearchParam("view=list&taskId=old", "task-2")).toBe(
      "?view=list&taskId=task-2",
    );
  });

  it("removes taskId while preserving other params", () => {
    expect(withTaskIdSearchParam("view=list&taskId=old", null)).toBe(
      "?view=list",
    );
  });

  it("builds full url with taskId param updates", () => {
    expect(
      buildUrlWithTaskId("/boards/board-1", "filter=active", "task-1"),
    ).toBe("/boards/board-1?filter=active&taskId=task-1");
  });
});
