"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  type listGatewaysApiV1GatewaysGetResponse,
  useListGatewaysApiV1GatewaysGet,
} from "@/api/generated/gateways/gateways";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type { BoardRead, GatewayRead } from "@/api/generated/model";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import SearchableSelect, {
  type SearchableSelectOption,
} from "@/components/ui/searchable-select";

type DiscoveredAgent = {
  agent_id: string;
  workspace: string | null;
  linked: boolean;
  linked_agent_name: string | null;
};

const getBoardOptions = (boards: BoardRead[]): SearchableSelectOption[] =>
  boards.map((board) => ({
    value: board.id,
    label: board.name,
  }));

const getGatewayOptions = (gateways: GatewayRead[]): SearchableSelectOption[] =>
  gateways.map((gateway) => ({
    value: gateway.id,
    label: gateway.name,
  }));

export default function LinkAgentPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [selectedGatewayId, setSelectedGatewayId] = useState<string>("");
  const [discoveredAgents, setDiscoveredAgents] = useState<DiscoveredAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [boardId, setBoardId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [isLinking, setIsLinking] = useState(false);

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
    },
  });

  const gatewaysQuery = useListGatewaysApiV1GatewaysGet<
    listGatewaysApiV1GatewaysGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
    },
  });

  const boards =
    boardsQuery.data?.status === 200 ? (boardsQuery.data.data.items ?? []) : [];
  const gateways =
    gatewaysQuery.data?.status === 200 ? (gatewaysQuery.data.data.items ?? []) : [];
  
  const displayBoardId = boardId || boards[0]?.id || "";
  const displayGatewayId = selectedGatewayId || gateways[0]?.id || "";
  
  const isLoading = boardsQuery.isLoading || gatewaysQuery.isLoading;
  const errorMessage = error ?? boardsQuery.error?.message ?? gatewaysQuery.error?.message ?? null;

  const handleDiscoverAgents = async () => {
    if (!displayGatewayId) {
      setError("Please select a gateway first.");
      return;
    }

    setIsDiscovering(true);
    setError(null);
    
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';
      const token = typeof window !== 'undefined' ? window.sessionStorage.getItem('mc_local_auth_token') : null;
      const response = await fetch(`${baseUrl}/api/v1/gateways/${displayGatewayId}/discover-agents`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to discover agents');
      }

      const agents: DiscoveredAgent[] = await response.json();
      setDiscoveredAgents(agents);
      
      // Clear selection if previously selected agent no longer exists
      if (selectedAgentId && !agents.some(a => a.agent_id === selectedAgentId)) {
        setSelectedAgentId("");
        setName("");
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to discover agents');
      setDiscoveredAgents([]);
    } finally {
      setIsDiscovering(false);
    }
  };

  const handleAgentSelect = (agentId: string) => {
    setSelectedAgentId(agentId);
    // Auto-fill the name field with a capitalized version of the agent ID
    const agent = discoveredAgents.find(a => a.agent_id === agentId);
    if (agent && !name.trim()) {
      const capitalizedName = agent.agent_id.charAt(0).toUpperCase() + agent.agent_id.slice(1);
      setName(capitalizedName);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn) return;
    
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Agent name is required.");
      return;
    }
    
    if (!selectedAgentId) {
      setError("Please select an agent to link.");
      return;
    }
    
    const resolvedBoardId = displayBoardId;
    if (!resolvedBoardId) {
      setError("Select a board before linking an agent.");
      return;
    }
    
    setError(null);
    setIsLinking(true);
    
    try {
      const linkToken = typeof window !== 'undefined' ? window.sessionStorage.getItem('mc_local_auth_token') : null;
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/v1/agents/link`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(linkToken ? { 'Authorization': `Bearer ${linkToken}` } : {}),
        },
        body: JSON.stringify({
          gateway_agent_id: selectedAgentId,
          board_id: resolvedBoardId,
          name: trimmedName,
          role: role.trim() || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to link agent');
      }

      const linkedAgent = await response.json();
      router.push(`/agents/${linkedAgent.id}`);
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to link agent');
    } finally {
      setIsLinking(false);
    }
  };

  const availableAgents = discoveredAgents.filter(agent => !agent.linked);
  const selectedAgent = discoveredAgents.find(a => a.agent_id === selectedAgentId);

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to link an agent.",
        forceRedirectUrl: "/agents/link",
        signUpForceRedirectUrl: "/agents/link",
      }}
      title="Link existing agent"
      description="Connect a pre-existing OpenClaw agent to Mission Control."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can link agents."
    >
      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-6"
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Discovery
          </p>
          <div className="mt-4 space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Gateway <span className="text-red-500">*</span>
              </label>
              <div className="flex gap-3">
                <div className="flex-1">
                  <SearchableSelect
                    ariaLabel="Select gateway"
                    value={displayGatewayId}
                    onValueChange={setSelectedGatewayId}
                    options={getGatewayOptions(gateways)}
                    placeholder="Select gateway"
                    searchPlaceholder="Search gateways..."
                    emptyMessage="No matching gateways."
                    triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                    contentClassName="rounded-xl border border-slate-200 shadow-lg"
                    itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                    disabled={gateways.length === 0 || isDiscovering}
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleDiscoverAgents}
                  disabled={!displayGatewayId || isDiscovering || isLoading}
                >
                  {isDiscovering ? "Discovering..." : "Discover agents"}
                </Button>
              </div>
              {gateways.length === 0 ? (
                <p className="text-xs text-slate-500">
                  Configure a gateway before linking agents.
                </p>
              ) : null}
            </div>

            {discoveredAgents.length > 0 && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Available agents
                </label>
                {availableAgents.length === 0 ? (
                  <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3">
                    <p className="text-sm text-yellow-800">
                      All discovered agents are already linked to Mission Control.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {availableAgents.map((agent) => (
                      <label
                        key={agent.agent_id}
                        className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-200 p-3 hover:border-slate-300 hover:bg-slate-50"
                      >
                        <input
                          type="radio"
                          name="agent"
                          value={agent.agent_id}
                          checked={selectedAgentId === agent.agent_id}
                          onChange={() => handleAgentSelect(agent.agent_id)}
                          className="text-blue-600 focus:ring-blue-500"
                        />
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-slate-900">
                              {agent.agent_id}
                            </span>
                          </div>
                          {agent.workspace && (
                            <p className="text-xs text-slate-500 mt-1">
                              Workspace: {agent.workspace}
                            </p>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {selectedAgentId && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Configuration
            </p>
            <div className="mt-4 space-y-6">
              <div className="grid gap-6 md:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-900">
                    Display name <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Amy"
                    disabled={isLinking}
                  />
                  <p className="text-xs text-slate-500">
                    How this agent will appear in Mission Control.
                  </p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-900">
                    Role
                  </label>
                  <Input
                    value={role}
                    onChange={(event) => setRole(event.target.value)}
                    placeholder="e.g. Assistant, Coordinator"
                    disabled={isLinking}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Board <span className="text-red-500">*</span>
                </label>
                <SearchableSelect
                  ariaLabel="Select board"
                  value={displayBoardId}
                  onValueChange={setBoardId}
                  options={getBoardOptions(boards)}
                  placeholder="Select board"
                  searchPlaceholder="Search boards..."
                  emptyMessage="No matching boards."
                  triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  contentClassName="rounded-xl border border-slate-200 shadow-lg"
                  itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                  disabled={boards.length === 0 || isLinking}
                />
                {boards.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    Create a board before linking agents.
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {selectedAgent && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
            <h4 className="font-medium text-blue-900 mb-2">Agent Details</h4>
            <div className="space-y-1 text-sm">
              <p><span className="text-blue-700">ID:</span> {selectedAgent.agent_id}</p>
              {selectedAgent.workspace && (
                <p><span className="text-blue-700">Workspace:</span> {selectedAgent.workspace}</p>
              )}
            </div>
            <p className="text-xs text-blue-700 mt-2">
              This will link the existing agent without creating a new one or modifying its workspace.
            </p>
          </div>
        )}

        {errorMessage ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 shadow-sm">
            {errorMessage}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button 
            type="submit" 
            disabled={!selectedAgentId || isLinking || isLoading}
          >
            {isLinking ? "Linking..." : "Link agent"}
          </Button>
          <Button
            variant="outline"
            type="button"
            onClick={() => router.push("/agents")}
          >
            Back to agents
          </Button>
        </div>
      </form>
    </DashboardPageLayout>
  );
}