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

type ProtocolSectionKey =
  | "intake_checklist"
  | "execution_protocol"
  | "verification_commands"
  | "escalation_triggers";

type ProtocolSection = {
  key: ProtocolSectionKey;
  label: string;
};

const PROTOCOL_SECTIONS: ProtocolSection[] = [
  { key: "intake_checklist", label: "Intake checklist" },
  { key: "execution_protocol", label: "Execution protocol" },
  { key: "verification_commands", label: "Verification commands" },
  { key: "escalation_triggers", label: "Escalation triggers" },
];

const parseProtocolSteps = (value: unknown): string[] => {
  if (typeof value !== "string") return [];
  const normalized = value.trim();
  if (!normalized) return [];
  if (normalized.includes("\n")) {
    return normalized
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }
  if (normalized.includes(", ")) {
    return normalized
      .split(/,\s+/)
      .map((line) => line.trim())
      .filter(Boolean);
  }
  return [normalized];
};

export default function AgentDetailPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const params = useParams();
  const agentIdParam = params?.agentId;
  const agentId = Array.isArray(agentIdParam) ? agentIdParam[0] : agentIdParam;

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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

  const protocolSections = useMemo(() => {
    const identity = agent?.identity_profile;
    if (!identity || typeof identity !== "object") return [];
    const profile = identity as Record<string, unknown>;
    return PROTOCOL_SECTIONS.map((section) => ({
      label: section.label,
      steps: parseProtocolSteps(profile[section.key]),
    })).filter((section) => section.steps.length > 0);
  }, [agent?.identity_profile]);

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
          <div className="flex h-full flex-col gap-6 rounded-2xl surface-panel p-8">
            <div className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface)] px-6 py-5 text-sm text-muted">
              Only organization owners and admins can access agents.
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col gap-6 rounded-2xl surface-panel p-8">
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

                  {protocolSections.length > 0 ? (
                    <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                        Behavior protocol
                      </p>
                      <p className="mt-1 text-xs text-quiet">
                        Operational steps configured for this agent.
                      </p>
                      <div className="mt-4 space-y-4">
                        {protocolSections.map((section) => (
                          <div key={section.label}>
                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                              {section.label}
                            </p>
                            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                              {section.steps.map((step, index) => (
                                <li key={`${section.label}-${index}`}>{step}</li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {(agent.soul_template || agent.identity_template) ? (
                    <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                        Templates
                      </p>
                      <p className="mt-1 text-xs text-quiet">
                        Custom templates configured for this agent.
                      </p>
                      <div className="mt-4 space-y-4">
                        {agent.soul_template ? (
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                              Soul template
                            </p>
                            <div className="mt-2 rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-sm">
                              <Markdown
                                content={agent.soul_template as string}
                                variant="comment"
                              />
                            </div>
                          </div>
                        ) : null}
                        {agent.identity_template ? (
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                              Identity template
                            </p>
                            <div className="mt-2 rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-sm">
                              <Markdown
                                content={agent.identity_template as string}
                                variant="comment"
                              />
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
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

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent aria-label="Delete agent">
          <DialogHeader>
            <DialogTitle>Delete agent</DialogTitle>
            <DialogDescription>
              This will remove {agent?.name}. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {deleteError ? (
            <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
              {deleteError}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleDelete} disabled={isDeleting}>
              {isDeleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardShell>
  );
}
