"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getApiBaseUrl } from "@/lib/api-base";
import { isLocalAuthMode, getLocalAuthToken } from "@/auth/localAuth";

type ClerkSession = { getToken: () => Promise<string> };
type ClerkGlobal = { session?: ClerkSession | null };

async function resolveToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;

  if (isLocalAuthMode()) {
    return getLocalAuthToken();
  }

  const clerk = (window as unknown as { Clerk?: ClerkGlobal }).Clerk;
  if (!clerk?.session) return null;
  try {
    return await clerk.session.getToken();
  } catch {
    return null;
  }
}

export type SSEStatus = "connecting" | "connected" | "disconnected" | "error";

export interface UseSSEOptions {
  /** SSE endpoint path (e.g. "/api/v1/agents/stream") */
  path: string;
  /** Query params appended to the URL */
  params?: Record<string, string | undefined>;
  /** Callback for each SSE message */
  onMessage: (event: MessageEvent) => void;
  /** Whether the hook is enabled (default true) */
  enabled?: boolean;
  /** Reconnect delay in ms after error (default 5000) */
  reconnectDelay?: number;
}

/**
 * React hook for consuming Server-Sent Events with auth.
 *
 * Because the browser EventSource API does not support custom headers,
 * we pass the auth token as a query parameter (`_token`). The backend
 * should accept this for SSE endpoints.
 *
 * Falls back to fetch-based SSE reading if the token approach fails.
 */
export function useSSE({
  path,
  params,
  onMessage,
  enabled = true,
  reconnectDelay = 5_000,
}: UseSSEOptions): { status: SSEStatus } {
  const [status, setStatus] = useState<SSEStatus>("disconnected");
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      cleanup();
      setStatus("disconnected");
      return;
    }

    let cancelled = false;

    const connect = async () => {
      cleanup();
      setStatus("connecting");

      const baseUrl = getApiBaseUrl();
      const token = await resolveToken();

      if (cancelled) return;

      const url = new URL(`${baseUrl}${path}`, window.location.origin);
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          if (v !== undefined) url.searchParams.set(k, v);
        });
      }
      // Pass token as query param since EventSource doesn't support headers
      if (token) {
        url.searchParams.set("_token", token);
      }

      const es = new EventSource(url.toString());
      esRef.current = es;

      es.onopen = () => {
        if (!cancelled) setStatus("connected");
      };

      es.onmessage = (event) => {
        if (!cancelled) onMessageRef.current(event);
      };

      es.onerror = () => {
        if (cancelled) return;
        es.close();
        esRef.current = null;
        setStatus("error");
        reconnectTimer.current = setTimeout(() => {
          if (!cancelled) void connect();
        }, reconnectDelay);
      };
    };

    void connect();

    return () => {
      cancelled = true;
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, path, JSON.stringify(params), reconnectDelay, cleanup]);

  return { status };
}
