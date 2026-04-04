"use client";

import { useState, useCallback, useMemo, useRef } from "react";

import { ApiError } from "@/api/mutator";
import {
  type getCatalogApiV1MissionControlAgentsModelCatalogGetResponse,
  type getModelAssignmentApiV1MissionControlAgentsAgentIdModelAssignmentGetResponse,
  useGetCatalogApiV1MissionControlAgentsModelCatalogGet,
  useGetModelAssignmentApiV1MissionControlAgentsAgentIdModelAssignmentGet,
  usePatchPrimaryApiV1MissionControlAgentsAgentIdModelAssignmentPrimaryPatch,
  usePutFallbackOverrideApiV1MissionControlAgentsAgentIdModelAssignmentFallbackOverridePut,
  useRegenerateRecommendationApiV1MissionControlAgentsAgentIdModelAssignmentRecommendationRegeneratePost,
} from "@/api/generated/model-controls/model-controls";
import type {
  AgentModelAssignmentRead,
  CatalogEntry,
  FallbackEntry,
  PatchPrimaryRequest,
  PutFallbackOverrideRequest,
  ValidationIssue,
} from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/* ------------------------------------------------------------------ */
/* Model label helpers (dynamic catalog backed)                       */
/* ------------------------------------------------------------------ */

function modelLabel(
  modelId: string | null | undefined,
  catalogIndex: Map<string, CatalogEntry>,
): string {
  if (!modelId) return "—";
  const found = catalogIndex.get(modelId);
  return found ? found.display_name : modelId;
}

function tierBadgeVariant(
  tier: string | undefined,
): "success" | "warning" | "error" | "default" {
  switch (tier) {
    case "premium":
      return "success";
    case "specialized":
      return "warning";
    case "budget":
      return "error";
    default:
      return "default";
  }
}

/* ------------------------------------------------------------------ */
/* Sub-components                                                     */
/* ------------------------------------------------------------------ */

function StatusBadge({
  status,
  variant = "default",
}: {
  status: string;
  variant?: "success" | "warning" | "error" | "default";
}) {
  const colors = {
    success:
      "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    warning:
      "bg-amber-500/10 text-amber-400 border-amber-500/20",
    error:
      "bg-red-500/10 text-red-400 border-red-500/20",
    default:
      "bg-[color:var(--surface-muted)] text-muted border-[color:var(--border)]",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${colors[variant]}`}
    >
      {status}
    </span>
  );
}

function configStatusVariant(
  s: string,
): "success" | "warning" | "error" | "default" {
  switch (s) {
    case "valid":
      return "success";
    case "stale":
    case "degraded":
      return "warning";
    case "invalid":
      return "error";
    default:
      return "default";
  }
}

function recommendationStatusVariant(
  s: string,
): "success" | "warning" | "error" | "default" {
  switch (s) {
    case "fresh":
      return "success";
    case "stale":
      return "warning";
    case "error":
      return "error";
    default:
      return "default";
  }
}

function IssuesList({
  issues,
  label,
}: {
  issues: ValidationIssue[];
  label: string;
}) {
  if (issues.length === 0) return null;
  return (
    <div className="mt-2">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
        {label}
      </p>
      <ul className="mt-1 space-y-1">
        {issues.map((issue, i) => (
          <li
            key={`${issue.code}-${i}`}
            className={`rounded-lg border px-3 py-2 text-xs ${
              issue.severity === "error"
                ? "border-red-500/20 bg-red-500/5 text-red-400"
                : "border-amber-500/20 bg-amber-500/5 text-amber-400"
            }`}
          >
            <span className="font-mono text-[10px] opacity-60">
              [{issue.code}]
            </span>{" "}
            {issue.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FallbackEntryRow({
  entry,
  catalogIndex,
}: {
  entry: FallbackEntry;
  catalogIndex: Map<string, CatalogEntry>;
}) {
  const catEntry = catalogIndex.get(entry.model_id);
  return (
    <div
      className={`flex items-center justify-between rounded-lg border border-[color:var(--border)] px-3 py-2 text-sm ${
        entry.enabled ? "bg-[color:var(--surface)]" : "bg-[color:var(--surface-muted)] opacity-60"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-quiet">#{entry.position}</span>
        <span className="text-strong">{modelLabel(entry.model_id, catalogIndex)}</span>
        {catEntry && (
          <StatusBadge status={catEntry.tier ?? "unknown"} variant={tierBadgeVariant(catEntry.tier)} />
        )}
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge status={entry.source ?? "unknown"} />
        <StatusBadge status={entry.trigger_type ?? "unavailable"} />
        {!entry.enabled && <StatusBadge status="disabled" variant="warning" />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main panel                                                         */
/* ------------------------------------------------------------------ */

interface ModelControlsPanelProps {
  agentId: string;
  isAdmin: boolean;
}

export function ModelControlsPanel({
  agentId,
  isAdmin,
}: ModelControlsPanelProps) {
  const [editPrimaryOpen, setEditPrimaryOpen] = useState(false);
  const [editFallbackOpen, setEditFallbackOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectionMode, setSelectionMode] = useState<"manual" | "auto">("auto");
  const [fallbackMode, setFallbackMode] = useState<
    "none" | "append" | "replace"
  >("none");
  const [manualFallbacks, setManualFallbacks] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Fetch dynamic model catalog
  const catalogQuery =
    useGetCatalogApiV1MissionControlAgentsModelCatalogGet<
      getCatalogApiV1MissionControlAgentsModelCatalogGetResponse,
      ApiError
    >({}, {
      query: {
        enabled: Boolean(isAdmin),
        staleTime: 60_000,       // 60s cache before refetch
        refetchInterval: 60_000, // auto-refresh every 60s
        refetchOnMount: "always",
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
    // Outage: return last-known-good if available
    return lastGoodCatalogRef.current?.models ?? [];
  }, [catalogQuery.data]);

  const catalogIndex: Map<string, CatalogEntry> = useMemo(
    () => new Map(catalogModels.map((m) => [m.model_id, m])),
    [catalogModels],
  );

  const catalogLoading = catalogQuery.isLoading;
  const catalogStale = Boolean(
    catalogQuery.error && lastGoodCatalogRef.current,
  );
  const catalogUnavailable = Boolean(
    catalogQuery.error && !lastGoodCatalogRef.current && !catalogQuery.isLoading,
  );

  // Fetch assignment
  const assignmentQuery =
    useGetModelAssignmentApiV1MissionControlAgentsAgentIdModelAssignmentGet<
      getModelAssignmentApiV1MissionControlAgentsAgentIdModelAssignmentGetResponse,
      ApiError
    >(agentId, {
      query: {
        enabled: Boolean(isAdmin && agentId),
        refetchInterval: 30_000,
        refetchOnMount: "always",
        retry: false,
      },
    });

  const assignment: AgentModelAssignmentRead | null =
    assignmentQuery.data?.status === 200 ? assignmentQuery.data.data : null;

  // Mutations
  const patchPrimary =
    usePatchPrimaryApiV1MissionControlAgentsAgentIdModelAssignmentPrimaryPatch<ApiError>(
      {
        mutation: {
          onSuccess: () => {
            setActionSuccess("Primary model updated.");
            setActionError(null);
            setEditPrimaryOpen(false);
            assignmentQuery.refetch();
          },
          onError: (err) => {
            setActionError(err.message || "Failed to update primary model.");
            setActionSuccess(null);
          },
        },
      },
    );

  const putFallback =
    usePutFallbackOverrideApiV1MissionControlAgentsAgentIdModelAssignmentFallbackOverridePut<ApiError>(
      {
        mutation: {
          onSuccess: () => {
            setActionSuccess("Fallback override saved.");
            setActionError(null);
            setEditFallbackOpen(false);
            assignmentQuery.refetch();
          },
          onError: (err) => {
            setActionError(
              err.message || "Failed to update fallback override.",
            );
            setActionSuccess(null);
          },
        },
      },
    );

  const regenerate =
    useRegenerateRecommendationApiV1MissionControlAgentsAgentIdModelAssignmentRecommendationRegeneratePost<ApiError>(
      {
        mutation: {
          onSuccess: () => {
            setActionSuccess("Recommendation regenerated.");
            setActionError(null);
            assignmentQuery.refetch();
          },
          onError: (err) => {
            setActionError(
              err.message || "Failed to regenerate recommendation.",
            );
            setActionSuccess(null);
          },
        },
      },
    );

  // Handlers
  const handlePatchPrimary = useCallback(() => {
    const payload: PatchPrimaryRequest = {
      selection_mode: selectionMode,
      model_id: selectionMode === "manual" ? selectedModel : null,
    };
    patchPrimary.mutate({ agentId, data: payload });
  }, [agentId, selectedModel, selectionMode, patchPrimary]);

  const handleSaveFallback = useCallback(() => {
    const payload: PutFallbackOverrideRequest = {
      override_mode: fallbackMode,
      entries: manualFallbacks.map((mid, i) => ({
        model_id: mid,
        position: i,
        trigger_type: "unavailable" as const,
        enabled: true,
      })),
    };
    putFallback.mutate({ agentId, data: payload });
  }, [agentId, fallbackMode, manualFallbacks, putFallback]);

  const handleResetFallback = useCallback(() => {
    const payload: PutFallbackOverrideRequest = {
      override_mode: "none",
      entries: [],
    };
    putFallback.mutate({ agentId, data: payload });
  }, [agentId, putFallback]);

  const handleRegenerate = useCallback(() => {
    regenerate.mutate({
      agentId,
      data: { reason: "admin_requested_refresh" },
    });
  }, [agentId, regenerate]);

  const openEditPrimary = useCallback(() => {
    if (assignment) {
      setSelectionMode(assignment.primary.selection_mode as "manual" | "auto");
      setSelectedModel(assignment.primary.manual_model_id ?? "");
    }
    setActionError(null);
    setActionSuccess(null);
    setEditPrimaryOpen(true);
  }, [assignment]);

  const openEditFallback = useCallback(() => {
    if (assignment) {
      setFallbackMode(
        (assignment.fallback.override_mode ?? "none") as "none" | "append" | "replace",
      );
      setManualFallbacks(
        (assignment.fallback.manual_entries ?? []).map((e) => e.model_id),
      );
    }
    setActionError(null);
    setActionSuccess(null);
    setEditFallbackOpen(true);
  }, [assignment]);

  // Derived state
  const handleRefreshCatalog = useCallback(() => {
    catalogQuery.refetch();
  }, [catalogQuery]);

  const isLoading = assignmentQuery.isLoading;
  const fetchError = assignmentQuery.error?.message ?? null;
  const catalogError = catalogQuery.error?.message ?? null;
  const isMutating =
    patchPrimary.isPending ||
    putFallback.isPending ||
    regenerate.isPending;

  if (!isAdmin) return null;

  return (
    <>
      <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
            Model Controls
          </p>
          <div className="flex items-center gap-2">
            {catalogLoading && (
              <span className="text-xs text-quiet">Loading catalog…</span>
            )}
            {!catalogLoading && catalogModels.length > 0 && (
              <span className="text-xs text-quiet">
                {catalogModels.length} models
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefreshCatalog}
              disabled={catalogQuery.isFetching}
              title="Refresh model catalog"
            >
              ↻
            </Button>
            {assignment && (
              <StatusBadge
                status={assignment.validation.config_status ?? "pending"}
                variant={configStatusVariant(
                  assignment.validation.config_status ?? "pending",
                )}
              />
            )}
          </div>
        </div>

        {/* Status messages */}
        {actionError && (
          <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-400">
            {actionError}
          </div>
        )}
        {actionSuccess && (
          <div className="mt-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-400">
            {actionSuccess}
          </div>
        )}

        {fetchError && (
          <div className="mt-3 rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 text-xs text-muted">
            {fetchError}
          </div>
        )}
        {catalogStale && lastGoodCatalogRef.current && (
          <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-400">
            ⚠ Catalog endpoint unreachable — showing cached data from{" "}
            {lastGoodCatalogRef.current.fetchedAt.toLocaleString()}.
            Models may be out of date.
          </div>
        )}
        {catalogUnavailable && (
          <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-400">
            Model catalog unavailable — no cached data. Selectors will be empty
            until the catalog endpoint recovers.
          </div>
        )}
        {catalogQuery.error && !catalogStale && !catalogUnavailable && (
          <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-400">
            Model catalog unavailable: {catalogQuery.error.message}
          </div>
        )}

        {isLoading && (
          <div className="mt-4 text-sm text-muted">
            Loading model assignment…
          </div>
        )}

        {assignment && (
          <div className="mt-4 space-y-5">
            {/* Primary model section */}
            <div>
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                  Primary Model
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={openEditPrimary}
                  disabled={isMutating}
                >
                  Edit
                </Button>
              </div>
              <div className="mt-2 grid gap-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted">Effective</span>
                  <span className="font-medium text-strong">
                    {modelLabel(assignment.primary.effective_model_id, catalogIndex)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Source</span>
                  <StatusBadge status={assignment.primary.source ?? "none"} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Mode</span>
                  <StatusBadge status={assignment.primary.selection_mode ?? "auto"} />
                </div>
                {assignment.primary.manual_model_id && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Manual selection</span>
                    <span className="text-sm text-strong">
                      {modelLabel(assignment.primary.manual_model_id, catalogIndex)}
                    </span>
                  </div>
                )}
                {assignment.primary.recommended_model_id && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Recommended</span>
                    <span className="text-sm text-strong">
                      {modelLabel(assignment.primary.recommended_model_id, catalogIndex)}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Fallback policy section */}
            <div>
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                  Fallback Policy
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleResetFallback}
                    disabled={
                      isMutating ||
                      (assignment.fallback.override_mode ?? "none") === "none"
                    }
                  >
                    Reset
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={openEditFallback}
                    disabled={isMutating}
                  >
                    Override
                  </Button>
                </div>
              </div>
              <div className="mt-2 grid gap-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted">Override mode</span>
                  <StatusBadge status={assignment.fallback.override_mode ?? "none"} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Status</span>
                  <StatusBadge
                    status={assignment.fallback.status ?? "empty_invalid"}
                    variant={
                      assignment.fallback.has_effective_fallback
                        ? "success"
                        : "warning"
                    }
                  />
                </div>
              </div>
              {(assignment.fallback.effective_entries ?? []).length > 0 && (
                <div className="mt-3 space-y-1">
                  <p className="text-xs text-quiet">Effective fallback chain</p>
                  {(assignment.fallback.effective_entries ?? []).map((entry, i) => (
                    <FallbackEntryRow
                      key={`${entry.model_id}-${i}`}
                      entry={entry}
                      catalogIndex={catalogIndex}
                    />
                  ))}
                </div>
              )}
              {assignment.fallback.no_valid_fallback_reason && (
                <p className="mt-2 text-xs text-amber-400">
                  {assignment.fallback.no_valid_fallback_reason}
                </p>
              )}
            </div>

            {/* Recommendation section */}
            <div>
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                  Recommendation
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRegenerate}
                  disabled={isMutating}
                >
                  {regenerate.isPending ? "Regenerating…" : "Regenerate"}
                </Button>
              </div>
              <div className="mt-2 grid gap-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted">Status</span>
                  <StatusBadge
                    status={assignment.recommendation.status ?? "pending"}
                    variant={recommendationStatusVariant(
                      assignment.recommendation.status ?? "pending",
                    )}
                  />
                </div>
                {assignment.recommendation.generated_at && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Generated</span>
                    <span className="text-xs text-strong">
                      {new Date(
                        assignment.recommendation.generated_at,
                      ).toLocaleString()}
                    </span>
                  </div>
                )}
                {(() => {
                  const expl = assignment.recommendation.explanation as Record<string, unknown> | undefined;
                  const summary = typeof expl?.summary === "string" ? expl.summary : null;
                  return summary ? (
                    <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-2 text-xs text-muted">
                      {summary}
                    </div>
                  ) : null;
                })()}
              </div>
            </div>

            {/* Validation section */}
            <IssuesList
              issues={assignment.validation.blocking_issues ?? []}
              label="Blocking Issues"
            />
            <IssuesList
              issues={assignment.validation.warnings ?? []}
              label="Warnings"
            />
          </div>
        )}
      </div>

      {/* Edit primary model dialog */}
      <Dialog open={editPrimaryOpen} onOpenChange={setEditPrimaryOpen}>
        <DialogContent aria-label="Edit primary model">
          <DialogHeader>
            <DialogTitle>Edit Primary Model</DialogTitle>
            <DialogDescription>
              Set a manual primary model or switch to auto
              (recommendation-backed).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                Selection Mode
              </label>
              <div className="mt-2 flex gap-2">
                <Button
                  variant={selectionMode === "auto" ? "primary" : "outline"}
                  size="sm"
                  onClick={() => setSelectionMode("auto")}
                >
                  Auto
                </Button>
                <Button
                  variant={selectionMode === "manual" ? "primary" : "outline"}
                  size="sm"
                  onClick={() => setSelectionMode("manual")}
                >
                  Manual
                </Button>
              </div>
            </div>
            {selectionMode === "manual" && (
              <div>
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                  Model
                </label>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="mt-2 w-full rounded-lg border border-[color:var(--border)] bg-[color:var(--surface)] px-3 py-2 text-sm text-strong"
                >
                  <option value="">Select a model…</option>
                  {catalogModels.map((m) => (
                    <option key={m.model_id} value={m.model_id}>
                      {m.display_name} ({m.tier} · {m.capability_class})
                    </option>
                  ))}
                </select>
              </div>
            )}
            {actionError && (
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-400">
                {actionError}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditPrimaryOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handlePatchPrimary}
              disabled={
                patchPrimary.isPending ||
                (selectionMode === "manual" && !selectedModel)
              }
            >
              {patchPrimary.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit fallback override dialog */}
      <Dialog open={editFallbackOpen} onOpenChange={setEditFallbackOpen}>
        <DialogContent aria-label="Edit fallback override">
          <DialogHeader>
            <DialogTitle>Fallback Override</DialogTitle>
            <DialogDescription>
              Set manual fallback entries. Use &quot;none&quot; to revert to
              generated-only fallback.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                Override Mode
              </label>
              <div className="mt-2 flex gap-2">
                {(["none", "append", "replace"] as const).map((mode) => (
                  <Button
                    key={mode}
                    variant={fallbackMode === mode ? "primary" : "outline"}
                    size="sm"
                    onClick={() => setFallbackMode(mode)}
                  >
                    {mode}
                  </Button>
                ))}
              </div>
            </div>
            {fallbackMode !== "none" && (
              <div>
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
                  Manual Fallback Entries
                </label>
                <div className="mt-2 space-y-2">
                  {manualFallbacks.map((mid, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-xs font-mono text-quiet">
                        #{i}
                      </span>
                      <select
                        value={mid}
                        onChange={(e) => {
                          const next = [...manualFallbacks];
                          next[i] = e.target.value;
                          setManualFallbacks(next);
                        }}
                        className="flex-1 rounded-lg border border-[color:var(--border)] bg-[color:var(--surface)] px-3 py-1.5 text-sm text-strong"
                      >
                        <option value="">Select…</option>
                        {catalogModels.map((m) => (
                          <option key={m.model_id} value={m.model_id}>
                            {m.display_name} ({m.tier} · {m.capability_class})
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setManualFallbacks(
                            manualFallbacks.filter((_, j) => j !== i),
                          );
                        }}
                      >
                        ✕
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setManualFallbacks([...manualFallbacks, ""])}
                  >
                    + Add entry
                  </Button>
                </div>
              </div>
            )}
            {actionError && (
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-400">
                {actionError}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditFallbackOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSaveFallback}
              disabled={putFallback.isPending}
            >
              {putFallback.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
