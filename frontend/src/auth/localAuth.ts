"use client";

import { AuthMode } from "@/auth/mode";

let localToken: string | null = null;
const STORAGE_KEY = "mc_local_auth_token";

/**
 * Maximum lifetime of a stored local-auth token, in milliseconds.
 *
 * `sessionStorage` already clears on tab-close, so this cap exists to bound
 * tokens that linger in long-lived tabs. Kept conservative (12h) because a
 * single shared bearer token has no per-request server-side TTL — once it
 * leaves this client it cannot be revoked.
 */
const TOKEN_MAX_AGE_MS = 12 * 60 * 60 * 1000;

type StoredEntry = { token: string; expiresAt: number };

function isStoredEntry(value: unknown): value is StoredEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { token?: unknown }).token === "string" &&
    typeof (value as { expiresAt?: unknown }).expiresAt === "number"
  );
}

function readEntry(): StoredEntry | null {
  if (typeof window === "undefined") return null;
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (isStoredEntry(parsed)) return parsed;
  } catch {
    // Legacy format: a bare token string. Accept on read (so existing
    // sessions are not silently logged out on deploy) and let the next
    // `setLocalAuthToken` rewrite it in the new shape.
    return { token: raw, expiresAt: Date.now() + TOKEN_MAX_AGE_MS };
  }
  return null;
}

export function isLocalAuthMode(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_MODE === AuthMode.Local;
}

export function setLocalAuthToken(token: string): void {
  localToken = token;
  if (typeof window === "undefined") return;
  const entry: StoredEntry = {
    token,
    expiresAt: Date.now() + TOKEN_MAX_AGE_MS,
  };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entry));
  } catch {
    // Ignore storage failures (private mode / policy).
  }
}

export function getLocalAuthToken(): string | null {
  // Re-read storage every call so an expired token is cleared even when an
  // earlier call cached the in-memory value before the deadline elapsed.
  const entry = readEntry();
  if (entry === null) {
    if (localToken !== null) localToken = null;
    return null;
  }

  if (entry.expiresAt <= Date.now()) {
    clearLocalAuthToken();
    return null;
  }

  localToken = entry.token;
  return entry.token;
}

export function clearLocalAuthToken(): void {
  localToken = null;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
}

export const __TEST_ONLY__ = {
  STORAGE_KEY,
  TOKEN_MAX_AGE_MS,
};
