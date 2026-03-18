"use client";

import type { ReactNode } from "react";

import { getLocalAuthToken } from "@/auth/localAuth";
import { LocalAuthLogin } from "@/components/organisms/LocalAuthLogin";

export function AuthProvider({ children }: { children: ReactNode }) {
  if (!getLocalAuthToken()) {
    return <LocalAuthLogin />;
  }
  return <>{children}</>;
}
