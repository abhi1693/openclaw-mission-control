"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { SignInButton, SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import { ArrowUpRight, Activity as ActivityIcon } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type listTaskCommentFeedApiV1ActivityTaskCommentsGetResponse,
  streamTaskCommentFeedApiV1ActivityTaskCommentsStreamGet,
  useListTaskCommentFeedApiV1ActivityTaskCommentsGet,
} from "@/api/generated/activity/activity";
import type { ActivityTaskCommentFeedItemRead } from "@/api/generated/model";
import { Markdown } from "@/components/atoms/Markdown";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { Button } from "@/components/ui/button";
import { createExponentialBackoff } from "@/lib/backoff";
import { apiDatetimeToMs, parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";
import { usePageActive } from "@/hooks/usePageActive";

const SSE_RECONNECT_BACKOFF = {
  baseMs: 1_000,
  factor: 2,
  jitter: 0.2,
  maxMs: 5 * 60_000,
} as const;

const formatShortTimestamp = (value: string) => {
  const date = parseApiDatetime(value);
  if (!date) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const latestTimestamp = (items: ActivityTaskCommentFeedItemRead[]) => {
  let latest = 0;
  for (const item of items) {
    const time = apiDatetimeToMs(item.created_at) ?? 0;
    latest = Math.max(latest, time);
  }
  return latest ? new Date(latest).toISOString() : null;
};

const FeedCard = memo(function FeedCard({
  item,
}: {
  item: ActivityTaskCommentFeedItemRead;
}) {
  const message = (item.message ?? "").trim();
  const authorName = item.agent_name?.trim() || "Admin";
  const authorRole = item.agent_role?.trim() || null;
  const authorAvatar = (authorName[0] ?? "A").toUpperCase();

  const taskHref = `/boards/${item.board_id}?taskId=${item.task_id}`;
  const boardHref = `/boards/${item.board_id}`;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-slate-300">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700">
          {authorAvatar}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <Link
                href={taskHref}
                className={cn(
                  "block text-sm font-semibold leading-snug text-slate-900 transition hover:text-slate-950 hover:underline",
                )}
                title={item.task_title}
                style={{
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                }}
              >
                {item.task_title}
              </Link>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500">
                <Link
                  href={boardHref}
                  className="font-semibold text-slate-700 hover:text-slate-900 hover:underline"
                >
                  {item.board_name}
                </Link>
                <span className="text-slate-300">·</span>
                <span className="font-medium text-slate-700">{authorName}</span>
                {authorRole ? (
                  <>
                    <span className="text-slate-300">·</span>
                    <span className="text-slate-500">{authorRole}</span>
                  </>
                ) : null}
                <span className="text-slate-300">·</span>
                <span className="text-slate-400">
                  {formatShortTimestamp(item.created_at)}
                </span>
              </div>
            </div>
            <Link
              href={taskHref}
              className="inline-flex flex-shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold text-slate-600 transition hover:bg-slate-50 hover:text-slate-900"
              aria-label="View task"
            >
              View task
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>
      {message ? (
        <div className="mt-3 select-text cursor-text text-sm leading-relaxed text-slate-900 break-words">
          <Markdown content={message} variant="basic" />
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500">—</p>
      )}
    </div>
  );
});

FeedCard.displayName = "FeedCard";

export default function ActivityPage() {
  const { isSignedIn } = useAuth();
  const isPageActive = usePageActive();

  const feedQuery = useListTaskCommentFeedApiV1ActivityTaskCommentsGet<
    listTaskCommentFeedApiV1ActivityTaskCommentsGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchOnMount: "always",
        refetchOnWindowFocus: false,
        retry: false,
      },
    },
  );

  const [feedItems, setFeedItems] = useState<ActivityTaskCommentFeedItemRead[]>(
    [],
  );
  const feedItemsRef = useRef<ActivityTaskCommentFeedItemRead[]>([]);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const initializedRef = useRef(false);

  useEffect(() => {
    feedItemsRef.current = feedItems;
  }, [feedItems]);

  useEffect(() => {
    if (initializedRef.current) return;
    if (feedQuery.data?.status !== 200) return;
    const items = feedQuery.data.data.items ?? [];
    initializedRef.current = true;
    setFeedItems((prev) => {
      const map = new Map<string, ActivityTaskCommentFeedItemRead>();
      [...prev, ...items].forEach((item) => map.set(item.id, item));
      const merged = [...map.values()];
      merged.sort((a, b) => {
        const aTime = apiDatetimeToMs(a.created_at) ?? 0;
        const bTime = apiDatetimeToMs(b.created_at) ?? 0;
        return bTime - aTime;
      });
      const next = merged.slice(0, 200);
      seenIdsRef.current = new Set(next.map((item) => item.id));
      return next;
    });
  }, [feedQuery.data]);

  const pushFeedItem = useCallback((item: ActivityTaskCommentFeedItemRead) => {
    setFeedItems((prev) => {
      if (seenIdsRef.current.has(item.id)) return prev;
      seenIdsRef.current.add(item.id);
      const next = [item, ...prev];
      return next.slice(0, 200);
    });
  }, []);

  useEffect(() => {
    if (!isPageActive) return;
    if (!isSignedIn) return;
    let isCancelled = false;
    const abortController = new AbortController();
    const backoff = createExponentialBackoff(SSE_RECONNECT_BACKOFF);
    let reconnectTimeout: number | undefined;

    const connect = async () => {
      try {
        const since = latestTimestamp(feedItemsRef.current);
        const streamResult =
          await streamTaskCommentFeedApiV1ActivityTaskCommentsStreamGet(
            since ? { since } : undefined,
            {
              headers: { Accept: "text/event-stream" },
              signal: abortController.signal,
            },
          );
        if (streamResult.status !== 200) {
          throw new Error("Unable to connect task comment feed stream.");
        }
        const response = streamResult.data as Response;
        if (!(response instanceof Response) || !response.body) {
          throw new Error("Unable to connect task comment feed stream.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value && value.length) {
            backoff.reset();
          }
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const lines = raw.split("\n");
            let eventType = "message";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                data += line.slice(5).trim();
              }
            }
            if (eventType === "comment" && data) {
              try {
                const payload = JSON.parse(data) as {
                  comment?: ActivityTaskCommentFeedItemRead;
                };
                if (payload.comment) {
                  pushFeedItem(payload.comment);
                }
              } catch {
                // ignore malformed
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch {
        // Reconnect handled below.
      }

      if (!isCancelled) {
        if (reconnectTimeout !== undefined) {
          window.clearTimeout(reconnectTimeout);
        }
        const delay = backoff.nextDelayMs();
        reconnectTimeout = window.setTimeout(() => {
          reconnectTimeout = undefined;
          void connect();
        }, delay);
      }
    };

    void connect();
    return () => {
      isCancelled = true;
      abortController.abort();
      if (reconnectTimeout !== undefined) {
        window.clearTimeout(reconnectTimeout);
      }
    };
  }, [isPageActive, isSignedIn, pushFeedItem]);

  const orderedFeed = useMemo(() => {
    return [...feedItems].sort((a, b) => {
      const aTime = apiDatetimeToMs(a.created_at) ?? 0;
      const bTime = apiDatetimeToMs(b.created_at) ?? 0;
      return bTime - aTime;
    });
  }, [feedItems]);

  return (
    <DashboardShell>
      <SignedOut>
        <div className="col-span-2 flex min-h-[calc(100vh-64px)] items-center justify-center bg-slate-50 p-10 text-center">
          <div className="rounded-xl border border-slate-200 bg-white px-8 py-6 shadow-sm">
            <p className="text-sm text-slate-600">Sign in to view the feed.</p>
            <SignInButton
              mode="redirect"
              forceRedirectUrl="/activity"
              signUpForceRedirectUrl="/activity"
            >
              <Button className="mt-4" data-testid="activity-signin">
                Sign in
              </Button>
            </SignInButton>
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          <div className="sticky top-0 z-30 border-b border-slate-200 bg-white">
            <div className="px-8 py-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <ActivityIcon className="h-5 w-5 text-slate-600" />
                    <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                      Live feed
                    </h1>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    Realtime task comments across all boards.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="p-8">
            {feedQuery.isLoading && feedItems.length === 0 ? (
              <p className="text-sm text-slate-500">Loading feed…</p>
            ) : feedQuery.error ? (
              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm">
                {feedQuery.error.message || "Unable to load feed."}
              </div>
            ) : orderedFeed.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white p-10 text-center shadow-sm">
                <p className="text-sm font-medium text-slate-900">
                  Waiting for new comments…
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  When agents post updates, they will show up here.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {orderedFeed.map((item) => (
                  <FeedCard key={item.id} item={item} />
                ))}
              </div>
            )}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}
