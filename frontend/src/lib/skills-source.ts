/**
 * Normalize a repository-ish URL for UI usage.
 *
 * - Trims whitespace
 * - Removes trailing slashes
 * - Strips a trailing ".git" (common for clone URLs)
 */
export const normalizeRepoSourceUrl = (sourceUrl: string): string => {
  const trimmed = sourceUrl.trim().replace(/\/+$/, "");
  return trimmed.endsWith(".git") ? trimmed.slice(0, -4) : trimmed;
};

/**
 * Extract the base repo URL from a skill source URL.
 *
 * We support skill source URLs that may include a `/tree/<branch>/...` suffix
 * (e.g. a skill living inside a monorepo). In those cases, we want to link to
 * the repo root (the "pack") rather than the nested path.
 *
 * Returns `null` for invalid/unsupported URLs.
 */
export const repoBaseFromSkillSourceUrl = (
  skillSourceUrl: string,
): string | null => {
  try {
    const parsed = new URL(skillSourceUrl);
    const marker = "/tree/";
    const markerIndex = parsed.pathname.indexOf(marker);
    if (markerIndex <= 0) return null;

    // Reject unexpected structures (e.g. multiple /tree/ markers).
    if (parsed.pathname.indexOf(marker, markerIndex + marker.length) !== -1)
      return null;

    const repoPath = parsed.pathname.slice(0, markerIndex);
    if (!repoPath || repoPath === "/") return null;
    if (repoPath.endsWith("/tree")) return null;

    return normalizeRepoSourceUrl(`${parsed.origin}${repoPath}`);
  } catch {
    return null;
  }
};

/**
 * Derive the pack URL from a skill source URL.
 *
 * Prefer the repo base when the URL points at a nested `/tree/...` path.
 * Otherwise, fall back to the original source URL.
 */
export const packUrlFromSkillSourceUrl = (skillSourceUrl: string): string => {
  const repoBase = repoBaseFromSkillSourceUrl(skillSourceUrl);
  return repoBase ?? skillSourceUrl;
};

/**
 * Create a short, stable label for a pack URL (used in tables and filter pills).
 *
 * - For GitHub-like URLs, prefers `owner/repo`.
 * - For other URLs, falls back to the host.
 */
export const packLabelFromUrl = (packUrl: string): string => {
  try {
    const parsed = new URL(packUrl);
    const segments = parsed.pathname.split("/").filter(Boolean);
    if (segments.length >= 2) {
      return `${segments[0]}/${segments[1]}`;
    }
    return parsed.host;
  } catch {
    return "Open pack";
  }
};

/**
 * Build a packs page href filtered to a specific pack URL.
 *
 * We use a query param instead of path segments so the packs list can be
 * shareable/bookmarkable without additional route definitions.
 */
export const packsHrefFromPackUrl = (packUrl: string): string => {
  const params = new URLSearchParams({ source_url: packUrl });
  return `/skills/packs?${params.toString()}`;
};
