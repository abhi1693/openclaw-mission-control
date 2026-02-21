"use client";

import { useMemo } from "react";

import { ApiError } from "@/api/mutator";
import {
  type getSessionHistoryApiV1GatewaysSessionsSessionIdHistoryGetResponse,
  useGetSessionHistoryApiV1GatewaysSessionsSessionIdHistoryGet,
} from "@/api/generated/gateways/gateways";
import { useAuth } from "@/auth/clerk";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatTimestamp } from "@/lib/formatters";

interface SessionHistoryDialogProps {
  sessionId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface HistoryEvent {
  timestamp?: string;
  event_type?: string;
  content?: string;
  [key: string]: unknown;
}

export function SessionHistoryDialog({
  sessionId,
  open,
  onOpenChange,
}: SessionHistoryDialogProps) {
  const { isSignedIn } = useAuth();

  const historyQuery = useGetSessionHistoryApiV1GatewaysSessionsSessionIdHistoryGet<
    getSessionHistoryApiV1GatewaysSessionsSessionIdHistoryGetResponse,
    ApiError
  >(sessionId, {
    query: {
      enabled: Boolean(isSignedIn && open && sessionId),
      refetchOnMount: "always",
    },
  });

  const history = useMemo(() => {
    if (historyQuery.data?.status === 200) {
      return (historyQuery.data.data.history ?? []) as HistoryEvent[];
    }
    return [];
  }, [historyQuery.data]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label="Session history" className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Session history</DialogTitle>
          <DialogDescription>
            Events and messages for session {sessionId.slice(0, 8)}...
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[400px] overflow-y-auto">
          {historyQuery.isLoading ? (
            <div className="p-4 text-center text-sm text-slate-500">
              Loading history...
            </div>
          ) : historyQuery.error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
              {historyQuery.error.message}
            </div>
          ) : history.length === 0 ? (
            <div className="p-4 text-center text-sm text-slate-500">
              No history events found.
            </div>
          ) : (
            <div className="space-y-3">
              {history.map((event, index) => (
                <div
                  key={index}
                  className="rounded-lg border border-slate-200 bg-white p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      {event.event_type ? (
                        <p className="text-sm font-medium text-slate-900">
                          {event.event_type}
                        </p>
                      ) : null}
                      {event.content ? (
                        <p className="mt-1 text-sm text-slate-600 whitespace-pre-wrap break-words">
                          {event.content}
                        </p>
                      ) : null}
                    </div>
                    {event.timestamp ? (
                      <p className="flex-shrink-0 text-xs text-slate-500">
                        {formatTimestamp(event.timestamp)}
                      </p>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
