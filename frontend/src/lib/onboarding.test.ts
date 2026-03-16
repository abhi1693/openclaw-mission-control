import { describe, expect, it } from "vitest";

import { isOnboardingComplete } from "@/lib/onboarding";

describe("isOnboardingComplete", () => {
  it("returns false when profile is missing", () => {
    expect(isOnboardingComplete(null)).toBe(false);
    expect(isOnboardingComplete(undefined)).toBe(false);
  });

  it("returns false when timezone is missing", () => {
    expect(
      isOnboardingComplete({
        preferred_name: "Asha",
        timezone: "",
      }),
    ).toBe(false);
  });

  it("returns false when both name fields are missing", () => {
    expect(
      isOnboardingComplete({
        name: "   ",
        preferred_name: "   ",
        timezone: "America/New_York",
      }),
    ).toBe(false);
  });

  it("accepts preferred_name + timezone", () => {
    expect(
      isOnboardingComplete({
        preferred_name: "Asha",
        timezone: "America/New_York",
      }),
    ).toBe(true);
  });

  it("accepts fallback name + timezone", () => {
    expect(
      isOnboardingComplete({
        name: "Asha",
        timezone: "America/New_York",
      }),
    ).toBe(true);
  });
});
