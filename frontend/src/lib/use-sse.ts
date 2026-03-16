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

export interface SSEEvent {
  /** The SSE event name (empty string for unnamed/default events) */
  event: string;
  /** The event data payload (raw string) */
  data: string;
  /** The event id, if present */
  id?: string;
}

export interface UseSSEOptions {
  /** SSE endpoint path (e.g. "/api/v1/agents/stream") */
  path: string;
  /** Query params appended to the URL */
  params?: Record<string, string | undefined>;
  /** Callback for each SSE event (receives parsed event with name + data) */
  onEvent: (event: SSEEvent) => void;
  /** Whether the hook is enabled (default true) */
  enabled?: boolean;
  /** Reconnect delay in ms after error (default 5000) */
  reconnectDelay?: number;
}

/**
 * React hook for consuming Server-Sent Events with auth header support.
 *
 * Uses fetch + ReadableStream instead of the browser EventSource API so we can
 * send Authorization headers (EventSource does not support custom headers).
 * Supports named SSE events (e.g. `event: agent`).
 */
export function useSSE({
  path,
  params,
  onEvent,
  enabled = true,
  reconnectDelay = 5_000,
}: UseSSEOptions): { status: SSEStatus } {
  const [status, setStatus] = useState<SSEStatus>("disconnected");
  const abortRef = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
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

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
        };
        if (token) {
          headers["Authorization"] = `Bearer ${token}`;
        }

        const response = await fetch(url.toString(), {
          headers,
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`SSE HTTP ${response.status}`);
        }

        if (!response.body) {
          throw new Error("SSE response has no body");
        }

        if (!cancelled) setStatus("connected");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        // SSE parsing state
        let currentEvent = "";
        let currentData: string[] = [];
        let currentId: string | undefined;

        const dispatch = () => {
          if (currentData.length > 0) {
            const data = currentData.join("\n");
            onEventRef.current({
              event: currentEvent || "",
              data,
              id: currentId,
            });
          }
          // Reset for next event
          currentEvent = "";
          currentData = [];
          currentId = undefined;
        };

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done || cancelled) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete lines
          const lines = buffer.split("\n");
          // Keep incomplete last line in buffer
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line === "") {
              // Empty line = end of event
              dispatch();
            } else if (line.startsWith(":")) {
              // Comment, ignore
            } else if (line.startsWith("event:")) {
              currentEvent = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              currentData.push(line.slice(5).trimStart());
            } else if (line.startsWith("id:")) {
              currentId = line.slice(3).trim();
            }
            // Ignore retry: and unknown fields
          }
        }
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) {
          return;
        }
        if (!cancelled) {
          setStatus("error");
          reconnectTimer.current = setTimeout(() => {
            if (!cancelled) void connect();
          }, reconnectDelay);
        }
      }
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
