"use client";

export const dynamic = "force-dynamic";

import { useMemo } from "react";
import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type gatewaysStatusApiV1GatewaysStatusGetResponse,
  type getGatewayApiV1GatewaysGatewayIdGetResponse,
  useGatewaysStatusApiV1GatewaysStatusGet,
  useGetGatewayApiV1GatewaysGatewayIdGet,
} from "@/api/generated/gateways/gateways";
import {
  type listAgentsApiV1AgentsGetResponse,
  useListAgentsApiV1AgentsGet,
} from "@/api/generated/agents/agents";
import { formatTimestamp } from "@/lib/formatters";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";

const maskToken = (value?: string | null) => {
  if (!value) return "—";
  if (value.length <= 8) return "••••";
  return `••••${value.slice(-4)}`;
};

export default function GatewayDetailPage() {
  const router = useRouter();
  const params = useParams();
  const { isSignedIn } = useAuth();
  const gatewayIdParam = params?.gatewayId;
  const gatewayId = Array.isArray(gatewayIdParam)
    ? gatewayIdParam[0]
    : gatewayIdParam;

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const gatewayQuery = useGetGatewayApiV1GatewaysGatewayIdGet<
    getGatewayApiV1GatewaysGatewayIdGetResponse,
    ApiError
  >(gatewayId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && gatewayId),
      refetchInterval: 30_000,
    },
  });

  const gateway =
    gatewayQuery.data?.status === 200 ? gatewayQuery.data.data : null;

  const agentsQuery = useListAgentsApiV1AgentsGet<
    listAgentsApiV1AgentsGetResponse,
    ApiError
  >(gatewayId ? { gateway_id: gatewayId } : undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && gatewayId),
      refetchInterval: 15_000,
    },
  });

  const statusParams = gateway
    ? {
        gateway_url: gateway.url,
        gateway_token: gateway.token ?? undefined,
      }
    : {};

  const statusQuery = useGatewaysStatusApiV1GatewaysStatusGet<
    gatewaysStatusApiV1GatewaysStatusGetResponse,
    ApiError
  >(statusParams, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && gateway),
      refetchInterval: 15_000,
    },
  });

  const agents = useMemo(
    () =>
      agentsQuery.data?.status === 200
        ? (agentsQuery.data.data.items ?? [])
        : [],
    [agentsQuery.data],
  );

  const status =
    statusQuery.data?.status === 200 ? statusQuery.data.data : null;
  const isConnected = status?.connected ?? false;

  const title = useMemo(
    () => (gateway?.name ? gateway.name : "Gateway"),
    [gateway?.name],
  );

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view a gateway.",
        forceRedirectUrl: `/gateways/${gatewayId}`,
      }}
      title={title}
      description="Gateway configuration and connection details."
      headerActions={
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => router.push("/gateways")}>
            Back to gateways
          </Button>
          {isAdmin && gatewayId ? (
            <Button onClick={() => router.push(`/gateways/${gatewayId}/edit`)}>
              Edit gateway
            </Button>
          ) : null}
        </div>
      }
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can access gateways."
    >
      {gatewayQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          Loading gateway…
        </div>
      ) : gatewayQuery.error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
          {gatewayQuery.error.message}
        </div>
      ) : gateway ? (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Connection
                </p>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      statusQuery.isLoading
                        ? "bg-slate-300"
                        : isConnected
                          ? "bg-emerald-500"
                          : "bg-rose-500"
                    }`}
                  />
                  <span>
                    {statusQuery.isLoading
                      ? "Checking"
                      : isConnected
                        ? "Online"
                        : "Offline"}
                  </span>
                </div>
              </div>
              <div className="mt-4 space-y-3 text-sm text-slate-700">
                <div>
                  <p className="text-xs uppercase text-slate-400">
                    Gateway URL
                  </p>
                  <p className="mt-1 text-sm font-medium text-slate-900">
                    {gateway.url}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase text-slate-400">Token</p>
                  <p className="mt-1 text-sm font-medium text-slate-900">
                    {maskToken(gateway.token)}
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Runtime
              </p>
              <div className="mt-4 space-y-3 text-sm text-slate-700">
                <div>
                  <p className="text-xs uppercase text-slate-400">
                    Main session key
                  </p>
                  <p className="mt-1 text-sm font-medium text-slate-900">
                    {gateway.main_session_key}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase text-slate-400">
                    Workspace root
                  </p>
                  <p className="mt-1 text-sm font-medium text-slate-900">
                    {gateway.workspace_root}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs uppercase text-slate-400">Created</p>
                    <p className="mt-1 text-sm font-medium text-slate-900">
                      {formatTimestamp(gateway.created_at)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase text-slate-400">Updated</p>
                    <p className="mt-1 text-sm font-medium text-slate-900">
                      {formatTimestamp(gateway.updated_at)}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Agents
              </p>
              {agentsQuery.isLoading ? (
                <span className="text-xs text-slate-500">Loading…</span>
              ) : (
                <span className="text-xs text-slate-500">
                  {agents.length} total
                </span>
              )}
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Agent</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Last seen</th>
                    <th className="px-4 py-3">Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {agents.length === 0 && !agentsQuery.isLoading ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="px-4 py-6 text-center text-xs text-slate-500"
                      >
                        No agents assigned to this gateway.
                      </td>
                    </tr>
                  ) : (
                    agents.map((agent) => (
                      <tr key={agent.id} className="hover:bg-slate-50">
                        <td className="px-4 py-3">
                          <p className="text-sm font-medium text-slate-900">
                            {agent.name}
                          </p>
                          <p className="text-xs text-slate-500">{agent.id}</p>
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-700">
                          {agent.status}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {formatTimestamp(agent.last_seen_at ?? null)}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {formatTimestamp(agent.updated_at)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </DashboardPageLayout>
  );
}
