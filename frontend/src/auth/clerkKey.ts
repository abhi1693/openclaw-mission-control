// Shared Clerk publishable-key gating logic.
//
// IMPORTANT: keep this file dependency-free (no `"use client"`, no React, no Clerk imports)
// so it can be used from both client and server/edge entrypoints.

export function isLikelyValidClerkPublishableKey(
  key: string | undefined,
): key is string {
  if (!key) return false;

  // Clerk publishable keys look like: pk_test_... or pk_live_...
  // In CI we want builds to stay secretless; if the key isn't present/valid,
  // we skip Clerk entirely so `next build` can prerender.
  //
  // Note: this is a conservative heuristic (not an authoritative validation).
  const m = /^pk_(test|live)_([A-Za-z0-9]+)$/.exec(key);
  if (!m) return false;

  const body = m[2];
  if (body.length < 16) return false;
  if (/^0+$/.test(body)) return false;

  return true;
}
