import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __TEST_ONLY__,
  clearLocalAuthToken,
  getLocalAuthToken,
  setLocalAuthToken,
} from "@/auth/localAuth";

const VALID_TOKEN = "x".repeat(80);

beforeEach(() => {
  window.sessionStorage.clear();
  clearLocalAuthToken();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("setLocalAuthToken / getLocalAuthToken", () => {
  it("persists the token and reads it back via sessionStorage", () => {
    setLocalAuthToken(VALID_TOKEN);

    const raw = window.sessionStorage.getItem(__TEST_ONLY__.STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed.token).toBe(VALID_TOKEN);
    expect(typeof parsed.expiresAt).toBe("number");

    expect(getLocalAuthToken()).toBe(VALID_TOKEN);
  });

  it("returns null after the token has exceeded its max lifetime", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-30T10:00:00Z"));

    setLocalAuthToken(VALID_TOKEN);
    expect(getLocalAuthToken()).toBe(VALID_TOKEN);

    vi.advanceTimersByTime(__TEST_ONLY__.TOKEN_MAX_AGE_MS - 1000);
    expect(getLocalAuthToken()).toBe(VALID_TOKEN);

    vi.advanceTimersByTime(2000);
    expect(getLocalAuthToken()).toBeNull();
    expect(
      window.sessionStorage.getItem(__TEST_ONLY__.STORAGE_KEY),
    ).toBeNull();
  });

  it("accepts legacy bare-string entries left by older builds", () => {
    window.sessionStorage.setItem(__TEST_ONLY__.STORAGE_KEY, VALID_TOKEN);
    expect(getLocalAuthToken()).toBe(VALID_TOKEN);
  });

  it("rewrites legacy entries into the new shape on the next set", () => {
    window.sessionStorage.setItem(__TEST_ONLY__.STORAGE_KEY, VALID_TOKEN);
    expect(getLocalAuthToken()).toBe(VALID_TOKEN);

    setLocalAuthToken(VALID_TOKEN);
    const raw = window.sessionStorage.getItem(__TEST_ONLY__.STORAGE_KEY);
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string)).toMatchObject({ token: VALID_TOKEN });
  });

  it("rejects malformed JSON entries by returning null", () => {
    window.sessionStorage.setItem(
      __TEST_ONLY__.STORAGE_KEY,
      '{"token":42,"expiresAt":"soon"}',
    );

    expect(getLocalAuthToken()).toBeNull();
  });
});

describe("clearLocalAuthToken", () => {
  it("removes the entry from sessionStorage and the in-memory cache", () => {
    setLocalAuthToken(VALID_TOKEN);
    expect(getLocalAuthToken()).toBe(VALID_TOKEN);

    clearLocalAuthToken();

    expect(getLocalAuthToken()).toBeNull();
    expect(
      window.sessionStorage.getItem(__TEST_ONLY__.STORAGE_KEY),
    ).toBeNull();
  });
});
