"use client";

import type { ReactNode } from "react";

import { getLocalAuthToken } from "@/auth/localAuth";

function hasLocalAuthToken(): boolean {
  return Boolean(getLocalAuthToken());
}

export function isClerkEnabled(): boolean {
  return false;
}

export function SignedIn(props: { children: ReactNode }) {
  return hasLocalAuthToken() ? <>{props.children}</> : null;
}

export function SignedOut(props: { children: ReactNode }) {
  return hasLocalAuthToken() ? null : <>{props.children}</>;
}

export function SignInButton(_props: Record<string, unknown>) {
  return null;
}

export function SignOutButton(_props: Record<string, unknown>) {
  return null;
}

export function useUser() {
  return {
    isLoaded: true,
    isSignedIn: hasLocalAuthToken(),
    user: null,
  } as const;
}

export function useAuth() {
  const token = getLocalAuthToken();
  return {
    isLoaded: true,
    isSignedIn: Boolean(token),
    userId: token ? "local-user" : null,
    sessionId: token ? "local-session" : null,
    getToken: async () => token,
  } as const;
}
