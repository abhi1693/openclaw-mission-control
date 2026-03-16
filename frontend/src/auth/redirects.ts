const DEFAULT_SIGN_IN_REDIRECT = "/onboarding";

function isSafeRelativePath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//");
}

export function resolveSignInRedirectUrl(rawRedirect: string | null): string {
  const fallback =
    process.env.NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL ??
    DEFAULT_SIGN_IN_REDIRECT;

  if (!rawRedirect) return fallback;

  if (isSafeRelativePath(rawRedirect)) {
    return rawRedirect;
  }

  if (typeof window === "undefined") {
    return fallback;
  }

  try {
    const parsed = new URL(rawRedirect, window.location.origin);
    if (parsed.origin !== window.location.origin) {
      return fallback;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}
