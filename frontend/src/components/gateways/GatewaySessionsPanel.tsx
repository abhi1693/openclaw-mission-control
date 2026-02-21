"use client";

import { useState, useMemo } from "react";
import { History, MessageSquare } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type listGatewaySessionsApiV1GatewaysSessionsGetResponse,
  useListGatewaySessionsApiV1GatewaysSessionsGet,
} from "@/api/generated/gateways/gateways";
import { useAuth } from "@/auth/clerk";
import { Button } from "@/components/ui/button";
import { SessionHistoryDialog } from "./SessionHistoryDialog";
import { SendMessageDialog } from "./SendMessageDialog";
import { formatTimestamp } from "@/lib/formatters";

interface GatewaySessionsPanelProps {
  boardId?: string;
}

interface SessionInfo {
  session_id?: string;
  id?: string;
  status?: string;
  last_activity?: string;
  agent_id?: string;
  [key: string]: unknown;
}

export function GatewaySessionsPanel({ boardId }: GatewaySessionsPanelProps) {
  const { isSignedIn } = useAuth();
  const [historySessionId, setHistorySessionId] = useState<string | null>(null);
  const [messageSessionId, setMessageSessionId] = useState<string | null>(null);

  const sessionsQuery = useListGatewaySessionsApiV1GatewaysSessionsGet<
    listGatewaySessionsApiV1GatewaysSessionsGetResponse,
    ApiError
  >(boardId ? { board_id: boardId } : undefined, {
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
      refetchInterval: 30000,
    },
  });

  const sessions = useMemo(() => {
    if (sessionsQuery.data?.status === 200) {
      return (sessionsQuery.data.data.sessions ?? []) as SessionInfo[];
    }
    return [];
  }, [sessionsQuery.data]);

  const mainSession = useMemo(() => {
    if (sessionsQuery.data?.status === 200) {
      return sessionsQuery.data.data.main_session as SessionInfo | null;
    }
    return null;
  }, [sessionsQuery.data]);

  const getSessionId = (session: SessionInfo): string => {
    return session.session_id || session.id || "unknown";
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Sessions
        </p>
        {sessionsQuery.isLoading ? (
          <span className="text-xs text-slate-500">Loading...</span>
        ) : (
          <span className="text-xs text-slate-500">
            {sessions.length} active {mainSession ? "(+ main)" : ""}
          </span>
        )}
      </div>

      <div className="mt-4 space-y-3">
        {sessionsQuery.isLoading ? (
          <div className="p-4 text-center text-sm text-slate-500">
            Loading sessions...
          </div>
        ) : sessionsQuery.error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            {sessionsQuery.error.message}
          </div>
        ) : sessions.length === 0 && !mainSession ? (
          <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-sm text-slate-500">
            No active sessions found.
          </div>
        ) : (
          <>
            {mainSession ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-blue-900">
                        Main session
                      </p>
                      <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                        {mainSession.status || "active"}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-blue-700 font-mono">
                      {getSessionId(mainSession)}
                    </p>
                    {mainSession.last_activity ? (
                      <p className="mt-1 text-xs text-blue-600">
                        Last activity: {formatTimestamp(mainSession.last_activity)}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setHistorySessionId(getSessionId(mainSession))}
                    >
                      <History className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setMessageSessionId(getSessionId(mainSession))}
                    >
                      <MessageSquare className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            ) : null}

            {sessions.map((session) => {
              const sessionId = getSessionId(session);
              return (
                <div
                  key={sessionId}
                  className="rounded-lg border border-slate-200 bg-white p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-slate-900">
                          {session.agent_id
                            ? `Agent: ${session.agent_id.slice(0, 8)}...`
                            : "Session"}
                        </p>
                        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                          {session.status || "active"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500 font-mono">
                        {sessionId}
                      </p>
                      {session.last_activity ? (
                        <p className="mt-1 text-xs text-slate-500">
                          Last activity: {formatTimestamp(session.last_activity)}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setHistorySessionId(sessionId)}
                      >
                        <History className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setMessageSessionId(sessionId)}
                      >
                        <MessageSquare className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {historySessionId ? (
        <SessionHistoryDialog
          sessionId={historySessionId}
          open={!!historySessionId}
          onOpenChange={(open) => {
            if (!open) setHistorySessionId(null);
          }}
        />
      ) : null}

      {messageSessionId ? (
        <SendMessageDialog
          sessionId={messageSessionId}
          open={!!messageSessionId}
          onOpenChange={(open) => {
            if (!open) setMessageSessionId(null);
          }}
        />
      ) : null}
    </div>
  );
}
