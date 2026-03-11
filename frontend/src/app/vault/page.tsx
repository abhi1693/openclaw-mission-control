"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { Key, Plus, Trash2, Eye, EyeOff, Copy, Check } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Vault API types (based on backend routes)
interface VaultItem {
  key: string;
  value?: string;
  updated_at?: string;
}

interface VaultListResponse {
  items: VaultItem[];
}

export default function VaultPage() {
  const { isSignedIn } = useAuth();
  const [secrets, setSecrets] = useState<VaultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showValues, setShowValues] = useState<Record<string, boolean>>({});
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const fetchSecrets = async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem("mc_local_auth_token");
      const res = await fetch("/api/v1/api/vault/list", {
        headers: {
          "Authorization": `Bearer ${token}`,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setSecrets(data.items || []);
      } else {
        setError("Failed to load secrets");
      }
    } catch (err) {
      setError("Failed to connect to vault");
    } finally {
      setLoading(false);
    }
  };

  const addSecret = async () => {
    if (!newKey.trim() || !newValue.trim()) return;
    try {
      const token = localStorage.getItem("mc_local_auth_token");
      const res = await fetch("/api/v1/api/vault/set", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ key: newKey, value: newValue }),
      });
      if (res.ok) {
        setNewKey("");
        setNewValue("");
        fetchSecrets();
      }
    } catch (err) {
      setError("Failed to add secret");
    }
  };

  const deleteSecret = async (key: string) => {
    try {
      const token = localStorage.getItem("mc_local_auth_token");
      const res = await fetch("/api/v1/api/vault/delete", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ key }),
      });
      if (res.ok) {
        fetchSecrets();
      }
    } catch (err) {
      setError("Failed to delete secret");
    }
  };

  const toggleShowValue = (key: string) => {
    setShowValues(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const copyToClipboard = async (key: string, value: string) => {
    await navigator.clipboard.writeText(value);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to access vault.",
        forceRedirectUrl: "/vault",
        signUpForceRedirectUrl: "/vault",
      }}
      title="Vault"
      description="Manage secrets and configuration values."
    >
      <div className="space-y-6">
        {/* Add new secret */}
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Add Secret</h2>
          <p className="mt-1 text-sm text-slate-500">
            Store a new key-value pair in the vault.
          </p>

          <div className="mt-4 flex flex-col gap-4 sm:flex-row">
            <Input
              placeholder="Key (e.g., API_KEY)"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              className="sm:w-48"
            />
            <Input
              placeholder="Value"
              type="password"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              className="sm:w-64"
            />
            <Button onClick={addSecret} disabled={!newKey.trim() || !newValue.trim()}>
              <Plus className="h-4 w-4" />
              Add
            </Button>
            <Button variant="outline" onClick={fetchSecrets}>
              <Key className="h-4 w-4" />
              Refresh
            </Button>
          </div>
        </section>

        {/* Secrets list */}
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Stored Secrets</h2>
          <p className="mt-1 text-sm text-slate-500">
            {secrets.length} secret{secrets.length === 1 ? "" : "s"} in vault.
          </p>

          {loading ? (
            <p className="mt-4 text-sm text-slate-500">Loading...</p>
          ) : error ? (
            <p className="mt-4 text-sm text-red-500">{error}</p>
          ) : secrets.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">No secrets stored yet.</p>
          ) : (
            <div className="mt-4 space-y-2">
              {secrets.map((secret) => (
                <div
                  key={secret.key}
                  className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-3"
                >
                  <div className="flex items-center gap-3">
                    <Key className="h-4 w-4 text-slate-500" />
                    <span className="font-mono text-sm font-medium text-slate-900">
                      {secret.key}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleShowValue(secret.key)}
                      className="rounded p-1 hover:bg-slate-200"
                      title={showValues[secret.key] ? "Hide" : "Show"}
                    >
                      {showValues[secret.key] ? (
                        <EyeOff className="h-4 w-4 text-slate-500" />
                      ) : (
                        <Eye className="h-4 w-4 text-slate-500" />
                      )}
                    </button>
                    <button
                      onClick={() => copyToClipboard(secret.key, secret.value || "")}
                      className="rounded p-1 hover:bg-slate-200"
                      title="Copy"
                    >
                      {copiedKey === secret.key ? (
                        <Check className="h-4 w-4 text-green-500" />
                      ) : (
                        <Copy className="h-4 w-4 text-slate-500" />
                      )}
                    </button>
                    <button
                      onClick={() => deleteSecret(secret.key)}
                      className="rounded p-1 hover:bg-slate-200"
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4 text-red-500" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </DashboardPageLayout>
  );
}
