import { describe, expect, it } from "vitest";

import type { OrganizationMemberRead } from "@/api/generated/model";
import {
  DEFAULT_HUMAN_LABEL,
  normalizeDisplayName,
  resolveHumanActorName,
  resolveMemberDisplayName,
} from "./display-name";

const memberWithUser = (user: {
  preferred_name?: string | null;
  name?: string | null;
}): OrganizationMemberRead =>
  ({
    user,
  }) as OrganizationMemberRead;

describe("display-name", () => {
  it("normalizes empty strings to null", () => {
    expect(normalizeDisplayName("   ")).toBeNull();
    expect(normalizeDisplayName(" Abhimanyu ")).toBe("Abhimanyu");
  });

  it("resolves generic labels to fallback names", () => {
    expect(resolveHumanActorName("Admin", "Abhimanyu")).toBe("Abhimanyu");
    expect(resolveHumanActorName(" user ", "Abhimanyu")).toBe("Abhimanyu");
  });

  it("keeps explicit non-generic actor labels", () => {
    expect(resolveHumanActorName("Abhimanyu", "User")).toBe("Abhimanyu");
  });

  it("prefers membership preferred_name over name", () => {
    const member = memberWithUser({
      preferred_name: "Abhimanyu",
      name: "Admin",
    });
    expect(resolveMemberDisplayName(member)).toBe("Abhimanyu");
  });

  it("falls back to membership name when preferred_name missing", () => {
    const member = memberWithUser({
      preferred_name: null,
      name: "Abhimanyu",
    });
    expect(resolveMemberDisplayName(member)).toBe("Abhimanyu");
  });

  it("returns default user label when member names are unavailable", () => {
    expect(resolveMemberDisplayName(null)).toBe(DEFAULT_HUMAN_LABEL);
    expect(resolveMemberDisplayName(memberWithUser({ name: "Admin" }))).toBe(
      DEFAULT_HUMAN_LABEL,
    );
  });
});
