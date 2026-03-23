"use client";

export const dynamic = "force-dynamic";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { SignInButton, SignedIn, SignedOut, useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type getAgentApiV1AgentsAgentIdGetResponse,
  useDeleteAgentApiV1AgentsAgentIdDelete,
  useGetAgentApiV1AgentsAgentIdGet,
} from "@/api/generated/agents/agents";
import {
  type listActivityApiV1ActivityGetResponse,
  useListActivityApiV1ActivityGet,
} from "@/api/generated/activity/activity";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  formatRelativeTimestamp as formatRelative,
  formatTimestamp,
} from "@/lib/formatters";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type {
  ActivityEventRead,
  AgentRead,
  BoardRead,
} from "@/api/generated/model";
import { Markdown } from "@/components/atoms/Markdown";
import { StatusPill } from "@/components/atoms/StatusPill";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export default function AgentDetailPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const params = useParams();
  const agentIdParam = params?.agentId;
  const agentId = Array.isArray(agentIdParam) ? agentIdParam[0] : agentIdParam;

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");
  const [unlinkOpen, setUnlinkOpen] = useState(false);
  const [unlinkError, setUnlinkError] = useState<string | null>(null);
  const [unlinking, setUnlinking] = useState(false);

  const agentQuery = useGetAgentApiV1AgentsAgentIdGet<
    getAgentApiV1AgentsAgentIdGetResponse,
    ApiError
  >(agentId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && agentId),
      refetchInterval: 30_000,
      refetchOnMount: "always",
      retry: false,
    },
  });

  const activityQuery = useListActivityApiV1ActivityGet<
    listActivityApiV1ActivityGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn && isAdmin),
        refetchInterval: 30_000,
        retry: false,
      },
    },
  );

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchInterval: 60_000,
      refetchOnMount: "always",
      retry: false,
    },
  });

  const agent: AgentRead | null =
    agentQuery.data?.status === 200 ? agentQuery.data.data : null;
  const events = useMemo<ActivityEventRead[]>(() => {
    if (activityQuery.data?.status !== 200) return [];
    return activityQuery.data.data.items ?? [];
  }, [activityQuery.data]);
  const boards = useMemo<BoardRead[]>(() => {
    if (boardsQuery.data?.status !== 200) return [];
    return boardsQuery.data.data.items ?? [];
  }, [boardsQuery.data]);

  const agentEvents = useMemo(() => {
    if (!agent) return [];
    return events.filter((event) => event.agent_id === agent.id);
  }, [events, agent]);
  const linkedBoard =
    !agent?.board_id || agent?.is_gateway_main
      ? null
      : (boards.find((board) => board.id === agent.board_id) ?? null);

  const deleteMutation = useDeleteAgentApiV1AgentsAgentIdDelete<ApiError>({
    mutation: {
      onSuccess: () => {
        setDeleteOpen(false);
        router.push("/agents");
      },
      onError: (err) => {
        setDeleteError(err.message || "Something went wrong.");
      },
    },
  });

  const isLoading =
    agentQuery.isLoading || activityQuery.isLoading || boardsQuery.isLoading;
  const error =
    agentQuery.error?.message ??
    activityQuery.error?.message ??
    boardsQuery.error?.message ??
    null;

  const isDeleting = deleteMutation.isPending;
  const agentStatus = agent?.status ?? "unknown";

  const handleDelete = () => {
    if (!agentId || !isSignedIn) return;
    setDeleteError(null);
    deleteMutation.mutate({ agentId });
  };

  const handleUnlink = async () => {
    if (!agentId || !isSignedIn) return;
    setUnlinkError(null);
    setUnlinking(true);
    try {
      const unlinkToken = typeof window !== 'undefined' ? window.sessionStorage.getItem('mc_local_auth_token') : null;
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/v1/agents/${agentId}/unlink`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(unlinkToken ? { "Authorization": `Bearer ${unlinkToken}` } : {}),
        },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Error ${res.status}`);
      }
      setUnlinkOpen(false);
      router.push("/agents");
    } catch (err: unknown) {
      setUnlinkError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setUnlinking(false);
    }
  };

  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl surface-panel p-10 text-center">
          <p className="text-sm text-muted">Sign in to view agents.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/agents"
            signUpForceRedirectUrl="/agents"
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        {!isAdmin ? (
          <div className="flex h-full flex-col gap-6 rounded-2xl surface-panel p-4 md:p-8">
            <div className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface)] px-6 py-5 text-sm text-muted">
              Only organization owners and admins can access agents.
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col gap-6 rounded-2xl surface-panel p-4 md:p-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-quiet">
                  Agents
                </p>
                <h1 className="text-2xl font-semibold text-strong">
                  {agent?.name ?? "Agent"}
                </h1>
                <p className="text-sm text-muted">
                  Review agent health, session binding, and recent activity.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => router.push("/agents")}
                >
                  Back to agents
                </Button>
                {agent ? (
                  <Link
                    href={`/agents/${agent.id}/edit`}
                    className="inline-flex h-10 items-center justify-center rounded-xl border border-[color:var(--border)] px-4 text-sm font-semibold text-muted transition hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                  >
                    Edit
                  </Link>
                ) : null}
                {agent && !agent.is_board_lead ? (
                  <Button variant="outline" onClick={() => setUnlinkOpen(true)}>
                    Unlink
                  </Button>
                ) : null}
                {agent ? (
                  <Button variant="outline" onClick={() => setDeleteOpen(true)}>
                    Delete
                  </Button>
                ) : null}
              </div>
            </div>

            {error ? (
              <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
                {error}
              </div>
            ) : null}

            {isLoading ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted">
                Loading agent details…
              </div>
            ) : agent ? (
              <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
                <div className="space-y-6">
                  <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Overview
                        </p>
                        <p className="mt-1 text-lg font-semibold text-strong">
                          {agent.name}
                        </p>
                      </div>
                      <StatusPill status={agentStatus} />
                    </div>
                    <div className="mt-4 grid gap-4 md:grid-cols-2">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Agent ID
                        </p>
                        <p className="mt-1 text-sm text-muted">{agent.id}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Session key
                        </p>
                        <p className="mt-1 text-sm text-muted">
                          {agent.openclaw_session_id ?? "—"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Board
                        </p>
                        {agent.is_gateway_main ? (
                          <p className="mt-1 text-sm text-strong">
                            Gateway main (no board)
                          </p>
                        ) : linkedBoard ? (
                          <Link
                            href={`/boards/${linkedBoard.id}`}
                            className="mt-1 inline-flex text-sm font-medium text-[color:var(--accent)] transition hover:underline"
                          >
                            {linkedBoard.name}
                          </Link>
                        ) : (
                          <p className="mt-1 text-sm text-strong">—</p>
                        )}
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Last seen
                        </p>
                        <p className="mt-1 text-sm text-strong">
                          {formatRelative(agent.last_seen_at)}
                        </p>
                        <p className="text-xs text-quiet">
                          {formatTimestamp(agent.last_seen_at)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Updated
                        </p>
                        <p className="mt-1 text-sm text-muted">
                          {formatTimestamp(agent.updated_at)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                          Created
                        </p>
                        <p className="mt-1 text-sm text-muted">
                          {formatTimestamp(agent.created_at)}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                        Health
                      </p>
                      <StatusPill status={agentStatus} />
                    </div>
                    <div className="mt-4 grid gap-3 text-sm text-muted">
                      <div className="flex items-center justify-between">
                        <span>Heartbeat window</span>
                        <span>{formatRelative(agent.last_seen_at)}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span>Session binding</span>
                        <span>
                          {agent.openclaw_session_id ? "Bound" : "Unbound"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span>Status</span>
                        <span className="text-strong">{agentStatus}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-5">
                  <div className="mb-4 flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                      Activity
                    </p>
                    <p className="text-xs text-quiet">
                      {agentEvents.length} events
                    </p>
                  </div>
                  <div className="space-y-3">
                    {agentEvents.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-[color:var(--border)] bg-[color:var(--surface)] p-4 text-sm text-muted">
                        No activity yet for this agent.
                      </div>
                    ) : (
                      agentEvents.map((event) => (
                        <div
                          key={event.id}
                          className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface)] p-4 text-sm text-muted"
                        >
                          {event.message?.trim() ? (
                            <div className="select-text cursor-text leading-relaxed text-strong break-words">
                              <Markdown
                                content={event.message}
                                variant="comment"
                              />
                            </div>
                          ) : (
                            <p className="font-medium text-strong">
                              {event.event_type}
                            </p>
                          )}
                          <p className="mt-1 text-xs text-quiet">
                            {formatTimestamp(event.created_at)}
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-muted">
                Agent not found.
              </div>
            )}
          </div>
        )}
      </SignedIn>

      <Dialog open={unlinkOpen} onOpenChange={setUnlinkOpen}>
        <DialogContent aria-label="Unlink agent">
          <DialogHeader>
            <DialogTitle>Unlink agent</DialogTitle>
            <DialogDescription>
              This will remove {agent?.name} from Mission Control but will NOT
              delete the agent from the gateway. It will keep running — you can
              re-link it later.
            </DialogDescription>
          </DialogHeader>
          {unlinkError ? (
            <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
              {unlinkError}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setUnlinkOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleUnlink} disabled={unlinking}>
              {unlinking ? "Unlinking…" : "Unlink"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={(open) => { setDeleteOpen(open); if (!open) setDeleteConfirmName(""); }}>
        <DialogContent aria-label="Delete agent">
          <DialogHeader>
            <DialogTitle>Delete agent</DialogTitle>
            <DialogDescription>
              This will <strong>permanently delete</strong> {agent?.name} from
              both Mission Control and the gateway, including its workspace.
              This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <p className="text-sm text-muted">
              Type <strong>{agent?.name}</strong> to confirm:
            </p>
            <input
              type="text"
              value={deleteConfirmName}
              onChange={(e) => setDeleteConfirmName(e.target.value)}
              placeholder={agent?.name ?? ""}
              className="w-full rounded-lg border border-[color:var(--border)] bg-[color:var(--surface)] px-3 py-2 text-sm text-strong outline-none focus:border-[color:var(--accent)]"
            />
          </div>
          {deleteError ? (
            <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
              {deleteError}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setDeleteOpen(false); setDeleteConfirmName(""); }}>
              Cancel
            </Button>
            <Button
              onClick={handleDelete}
              disabled={isDeleting || deleteConfirmName !== agent?.name}
            >
              {isDeleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardShell>
  );
}
