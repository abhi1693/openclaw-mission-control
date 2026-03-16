import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveSignInRedirectUrl } from "@/auth/redirects";

describe("resolveSignInRedirectUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("uses env fallback when redirect is missing", () => {
    vi.stubEnv("NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL", "/boards");

    expect(resolveSignInRedirectUrl(null)).toBe("/boards");
  });

  it("defaults to /onboarding when no env fallback is set", () => {
    expect(resolveSignInRedirectUrl(null)).toBe("/onboarding");
  });

  it("allows safe relative paths", () => {
    expect(resolveSignInRedirectUrl("/dashboard?tab=ops#queue")).toBe(
      "/dashboard?tab=ops#queue",
    );
  });

  it("rejects protocol-relative urls", () => {
    vi.stubEnv("NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL", "/activity");

    expect(resolveSignInRedirectUrl("//evil.example.com/path")).toBe(
      "/activity",
    );
  });

  it("rejects external absolute urls", () => {
    vi.stubEnv("NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL", "/activity");

    expect(resolveSignInRedirectUrl("https://evil.example.com/steal")).toBe(
      "/activity",
    );
  });

  it("accepts same-origin absolute urls and normalizes to path", () => {
    const url = `${window.location.origin}/boards/new?src=invite#top`;
    expect(resolveSignInRedirectUrl(url)).toBe("/boards/new?src=invite#top");
  });
});
