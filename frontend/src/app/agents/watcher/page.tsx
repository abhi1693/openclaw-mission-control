"use client";

export const dynamic = "force-dynamic";

import { useState, useEffect } from "react";
import { Activity, Eye, RefreshCw, Play, Square } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";

// Agent status types from API
interface AgentStatus {
  name: string;
  status: string;
  last_seen?: string;
  tasks_done?: number;
  tokens_used?: number;
  failed_count?: number;
  approval_rate?: number;
  avg_duration_ms?: number;
}

interface AgentsStatusResponse {
  agents: AgentStatus[];
}

const AGENT_EMOJI: Record<string, string> = {
  boss: "👑",
  dev: "💻",
  researcher: "🔬",
  mailman: "📧",
  planner: "📋",
  social: "📱",
  cronos: "⏰",
  fixbot: "🔧",
  memory: "🧠",
  watcher: "👁️",
};

export default function AgentWatcherPage() {
  const { isSignedIn } = useAuth();
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState<string | null>(null);

  const fetchAgentsStatus = async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem("openclaw_token");      const res = await fetch("/api/v1/api/agents/status", {
        headers: {
          "Authorization": `Bearer ${token}`,
        },
      });
      if (res.ok) {
        const data: AgentsStatusResponse = await res.json();
        setAgents(data.agents || []);
      } else {
        setError("Failed to load agent status");
      }
    } catch (err) {
      setError("Failed to connect to agents API");
    } finally {
      setLoading(false);
    }
  };

  const restartAgent = async (agentName: string) => {
    setRestarting(agentName);
    try {
      const token = localStorage.getItem("openclaw_token");
      const res = await fetch(`/api/v1/api/agents/${agentName}/restart`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
        },
      });
      if (res.ok) {
        // Refresh after restart
        setTimeout(fetchAgentsStatus, 2000);
      }
    } catch (err) {
      setError(`Failed to restart ${agentName}`);
    } finally {
      setRestarting(null);
    }
  };

  // Auto-refresh every 10 seconds
  useEffect(() => {
    fetchAgentsStatus();
    const interval = setInterval(fetchAgentsStatus, 10000);
    return () => clearInterval(interval);
  }, [isSignedIn]);

  const getStatusColor = (status: string) => {
    switch (status?.toLowerCase()) {
      case "active":
      case "running":
        return "bg-emerald-500";
      case "idle":
        return "bg-yellow-500";
      case "error":
      case "failed":
        return "bg-red-500";
      default:
        return "bg-slate-400";
    }
  };

  const formatTime = (dateStr?: string) => {
    if (!dateStr) return "Never";
    // Handle both ISO format and "2026-03-11 07:51:11.556897+00:00" format
    const date = dateStr.includes(" ") 
      ? new Date(dateStr.replace(" ", "T"))
      : new Date(dateStr);
    if (isNaN(date.getTime())) return "Unknown";
    const now = new Date();
    const diff = Math.floor((now.getTime() - date.getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to watch agents.",
        forceRedirectUrl: "/agents/watcher",
        signUpForceRedirectUrl: "/agents/watcher",
      }}
      title="Agent Watcher"
      description="Monitor all agents across boards in real-time."
      headerActions={
        <Button variant="outline" onClick={fetchAgentsStatus} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      }
    >
      <div className="space-y-6">
        {/* Agent cards */}
        {loading && agents.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="h-8 w-8 animate-spin text-slate-400" />
          </div>
        ) : error && agents.length === 0 ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
            <p className="text-red-600">{error}</p>
            <Button variant="outline" onClick={fetchAgentsStatus} className="mt-4">
              Retry
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <div
                key={agent.name}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{AGENT_EMOJI[agent.name] || "🤖"}</span>
                    <div>
                      <h3 className="font-semibold text-slate-900">{agent.name}</h3>
                      <div className="mt-1 flex items-center gap-2">
                        <span
                          className={`h-2 w-2 rounded-full ${getStatusColor(agent.status)}`}
                        />
                        <span className="text-sm text-slate-500 capitalize">
                          {agent.status || "unknown"}
                        </span>
                      </div>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => restartAgent(agent.name)}
                    disabled={restarting === agent.name}
                    title="Restart agent"
                  >
                    {restarting === agent.name ? (
                      <RefreshCw className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4 text-green-600" />
                    )}
                  </Button>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <p className="text-slate-500">Last seen</p>
                    <p className="font-medium text-slate-900">
                      {formatTime(agent.last_seen)}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500">Tasks done</p>
                    <p className="font-medium text-slate-900">
                      {agent.tasks_done ?? 0}
                    </p>
                  </div>
                </div>

                <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <p className="text-slate-500">Tokens used</p>
                    <p className="font-medium text-slate-900">
                      {agent.tokens_used ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500">Failed</p>
                    <p className="font-medium text-slate-900">
                      {agent.failed_count ?? 0}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {agents.length === 0 && !loading && !error && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-center">
            <p className="text-slate-500">No agents found.</p>
          </div>
        )}

        {/* Auto-refresh indicator */}
        <div className="flex items-center justify-center gap-2 text-sm text-slate-500">
          <Eye className="h-4 w-4" />
          Auto-refreshes every 10 seconds
        </div>
      </div>
    </DashboardPageLayout>
  );
}
