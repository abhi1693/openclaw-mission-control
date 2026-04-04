"use client";

import { useState, useCallback, useMemo, useRef } from "react";

import { ApiError } from "@/api/mutator";
import {
  type getCatalogApiV1MissionControlAgentsModelCatalogGetResponse,
  useGetCatalogApiV1MissionControlAgentsModelCatalogGet,
} from "@/api/generated/model-controls/model-controls";
import {
  type getModelProfileDefaultsApiV1GatewaysGatewayIdModelProfileDefaultsGetResponse,
  useGetModelProfileDefaultsApiV1GatewaysGatewayIdModelProfileDefaultsGet,
  usePatchModelProfileDefaultsApiV1GatewaysGatewayIdModelProfileDefaultsPatch,
} from "@/api/generated/gateway-model-profiles/gateway-model-profiles";
import type {
  CatalogEntry,
  GatewayModelProfileDefaultsRead,
  ProfileSlotRead,
} from "@/api/generated/model";
import { Button } from "@/components/ui/button";

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const DEFAULT_SENTINEL = "default";
const UNSET_VALUE = "__unset__";

const PROFILE_SLOTS = [
  {
    key: "general" as const,
    label: "General",
    sublabel: "Default for all agents",
    required: false,
    helperText:
      "Baseline model used when optional profiles are not selected. Set to 'Use runtime default' to defer to the gateway's configured default.",
  },
  {
    key: "coder" as const,
    label: "Coder",
    sublabel: "Optional",
    required: false,
    helperText:
      "Coding-optimized model for agents with coding roles. When not set, agents fall back to General.",
  },
  {
    key: "budget" as const,
    label: "Budget",
    sublabel: "Optional",
    required: false,
    helperText:
      "Cost-optimized model for automation and budget-sensitive roles. When not set, agents fall back to General.",
  },
] as const;

type SlotKey = (typeof PROFILE_SLOTS)[number]["key"];

/* ------------------------------------------------------------------ */
/* Sub-components                                                     */
/* ------------------------------------------------------------------ */

function SourceBadge({ source }: { source?: string }) {
  const colors: Record<string, string> = {
    explicit: "bg-emerald-50 text-emerald-700 border-emerald-200",
    default_sentinel: "bg-blue-50 text-blue-700 border-blue-200",
    fallback_to_general: "bg-amber-50 text-amber-700 border-amber-200",
    unset: "bg-slate-50 text-slate-500 border-slate-200",
  };
  const labels: Record<string, string> = {
    explicit: "Explicit",
    default_sentinel: "Runtime default",
    fallback_to_general: "Falls back to General",
    unset: "Not set",
  };
  const s = source ?? "unset";
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${colors[s] ?? colors.unset}`}
    >
      {labels[s] ?? s}
    </span>
  );
}

function SlotDisplay({
  slot,
  label,
  sublabel,
  helperText,
}: {
  slot: ProfileSlotRead;
  label: string;
  sublabel: string;
  helperText: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-semibold text-slate-900">{label}</span>
          <span className="ml-2 text-xs text-slate-400">{sublabel}</span>
        </div>
        <SourceBadge source={slot.source} />
      </div>
      <div className="mt-2 text-sm text-slate-700">
        {slot.source === "unset" ? (
          <span className="italic text-slate-400">No model selected</span>
        ) : slot.source === "default_sentinel" ? (
          <span className="text-blue-700">Using runtime default</span>
        ) : slot.display_name ? (
          <span className="font-medium">{slot.display_name}</span>
        ) : (
          <span className="font-mono text-xs">{slot.model_id}</span>
        )}
      </div>
      {slot.effective_model_id &&
        slot.effective_model_id !== slot.model_id && (
          <div className="mt-1 text-xs text-slate-400">
            Effective: {slot.effective_model_id}
          </div>
        )}
      <p className="mt-2 text-xs text-slate-400">{helperText}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main panel                                                         */
/* ------------------------------------------------------------------ */

interface GatewayModelProfilesPanelProps {
  gatewayId: string;
  isAdmin: boolean;
}

export function GatewayModelProfilesPanel({
  gatewayId,
  isAdmin,
}: GatewayModelProfilesPanelProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValues, setEditValues] = useState<Record<SlotKey, string>>({
    general: UNSET_VALUE,
    coder: UNSET_VALUE,
    budget: UNSET_VALUE,
  });
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Fetch catalog
  const catalogQuery =
    useGetCatalogApiV1MissionControlAgentsModelCatalogGet<
      getCatalogApiV1MissionControlAgentsModelCatalogGetResponse,
      ApiError
    >({}, {
      query: {
        enabled: Boolean(isAdmin),
        staleTime: 60_000,
        refetchInterval: 60_000,
        retry: 1,
      },
    });

  // Cache last-known-good catalog for outage resilience
  const lastGoodCatalogRef = useRef<{ models: CatalogEntry[]; fetchedAt: Date } | null>(null);

  const catalogModels: CatalogEntry[] = useMemo(() => {
    if (catalogQuery.data?.status === 200) {
      const models = catalogQuery.data.data.models ?? [];
      lastGoodCatalogRef.current = { models, fetchedAt: new Date() };
      return models;
    }
    return lastGoodCatalogRef.current?.models ?? [];
  }, [catalogQuery.data]);

  const catalogStale = Boolean(
    catalogQuery.error && lastGoodCatalogRef.current,
  );
  const catalogUnavailable = Boolean(
    catalogQuery.error && !lastGoodCatalogRef.current && !catalogQuery.isLoading,
  );

  // Fetch profile defaults
  const profileQuery =
    useGetModelProfileDefaultsApiV1GatewaysGatewayIdModelProfileDefaultsGet<
      getModelProfileDefaultsApiV1GatewaysGatewayIdModelProfileDefaultsGetResponse,
      ApiError
    >(gatewayId, {
      query: {
        enabled: Boolean(isAdmin && gatewayId),
        refetchInterval: 30_000,
        refetchOnMount: "always",
        retry: false,
      },
    });

  const profileDefaults: GatewayModelProfileDefaultsRead | null =
    profileQuery.data?.status === 200 ? profileQuery.data.data : null;

  // Mutation
  const patchMutation =
    usePatchModelProfileDefaultsApiV1GatewaysGatewayIdModelProfileDefaultsPatch<ApiError>(
      {
        mutation: {
          onSuccess: () => {
            setActionSuccess("Model profiles saved.");
            setActionError(null);
            setIsEditing(false);
            profileQuery.refetch();
          },
          onError: (err) => {
            setActionError(err.message || "Failed to save model profiles.");
            setActionSuccess(null);
          },
        },
      },
    );

  const handleStartEdit = useCallback(() => {
    if (profileDefaults) {
      setEditValues({
        general:
          profileDefaults.general.model_id === null
            ? UNSET_VALUE
            : profileDefaults.general.model_id ?? UNSET_VALUE,
        coder:
          profileDefaults.coder.model_id === null
            ? UNSET_VALUE
            : profileDefaults.coder.model_id ?? UNSET_VALUE,
        budget:
          profileDefaults.budget.model_id === null
            ? UNSET_VALUE
            : profileDefaults.budget.model_id ?? UNSET_VALUE,
      });
    }
    setActionError(null);
    setActionSuccess(null);
    setIsEditing(true);
  }, [profileDefaults]);

  const handleSave = useCallback(() => {
    const toApiValue = (v: string): string | null =>
      v === UNSET_VALUE ? null : v;

    patchMutation.mutate({
      gatewayId,
      data: {
        general_model_id: toApiValue(editValues.general),
        coder_model_id: toApiValue(editValues.coder),
        budget_model_id: toApiValue(editValues.budget),
      },
    });
  }, [gatewayId, editValues, patchMutation]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
    setActionError(null);
  }, []);

  if (!isAdmin) return null;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Model Profiles for Recommendations
          </p>
          <p className="mt-1 text-xs text-slate-400">
            Configure which models agents prefer by role. General applies when
            optional profiles are not selected.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!isEditing && (
            <Button variant="outline" size="sm" onClick={handleStartEdit}>
              {profileDefaults &&
              (profileDefaults.general.source !== "unset" ||
                profileDefaults.coder.source !== "unset" ||
                profileDefaults.budget.source !== "unset")
                ? "Edit"
                : "Configure"}
            </Button>
          )}
        </div>
      </div>

      {/* Status messages */}
      {actionSuccess && (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {actionSuccess}
        </div>
      )}
      {actionError && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {actionError}
        </div>
      )}

      {profileQuery.isLoading && (
        <div className="mt-4 text-sm text-slate-400">Loading profiles…</div>
      )}

      {profileQuery.error && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          {profileQuery.error.message}
        </div>
      )}

      {catalogStale && lastGoodCatalogRef.current && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          ⚠ Catalog endpoint unreachable — showing cached data from{" "}
          {lastGoodCatalogRef.current.fetchedAt.toLocaleString()}.
          Model options may be out of date.
        </div>
      )}
      {catalogUnavailable && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          Model catalog unavailable — no cached data. Dropdowns will be empty
          until the catalog endpoint recovers.
        </div>
      )}

      {/* Read view */}
      {profileDefaults && !isEditing && (
        <div className="mt-4 space-y-3">
          {PROFILE_SLOTS.map((slot) => (
            <SlotDisplay
              key={slot.key}
              slot={profileDefaults[slot.key]}
              label={slot.label}
              sublabel={slot.sublabel}
              helperText={slot.helperText}
            />
          ))}
          {profileDefaults.updated_at && (
            <p className="text-xs text-slate-400">
              Last updated:{" "}
              {new Date(profileDefaults.updated_at).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Edit view */}
      {isEditing && (
        <div className="mt-4 space-y-4">
          {PROFILE_SLOTS.map((slot) => (
            <div key={slot.key}>
              <label className="block text-sm font-semibold text-slate-900">
                {slot.label}
                <span className="ml-2 text-xs font-normal text-slate-400">
                  {slot.sublabel}
                </span>
              </label>
              <p className="mt-1 text-xs text-slate-400">{slot.helperText}</p>
              <select
                value={editValues[slot.key]}
                onChange={(e) =>
                  setEditValues((prev) => ({
                    ...prev,
                    [slot.key]: e.target.value,
                  }))
                }
                className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value={UNSET_VALUE}>
                  {slot.key === "general"
                    ? "— Not set —"
                    : "— Not set (falls back to General) —"}
                </option>
                <option value={DEFAULT_SENTINEL}>
                  Use runtime default
                </option>
                {catalogModels.map((m) => (
                  <option key={m.model_id} value={m.model_id}>
                    {m.display_name} ({m.tier} · {m.capability_class})
                  </option>
                ))}
              </select>
            </div>
          ))}

          {actionError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {actionError}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={handleCancel}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={patchMutation.isPending}
            >
              {patchMutation.isPending ? "Saving…" : "Save profiles"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
