"use client";

import { useCallback, useMemo, useState } from "react";

import { useAuth } from "@/auth/clerk";
import { useQueryClient } from "@tanstack/react-query";

import { CheckCircle2, Clock } from "lucide-react";
import { Cell, Pie, PieChart } from "recharts";

import { ApiError } from "@/api/mutator";
import {
  type listApprovalsApiV1BoardsBoardIdApprovalsGetResponse,
  getListApprovalsApiV1BoardsBoardIdApprovalsGetQueryKey,
  useListApprovalsApiV1BoardsBoardIdApprovalsGet,
  useUpdateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch,
} from "@/api/generated/approvals/approvals";
import type { ApprovalRead } from "@/api/generated/model";
import { StatusDot } from "@/components/atoms/StatusDot";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipCard,
  type ChartConfig,
} from "@/components/charts/chart";
import { Button } from "@/components/ui/button";
import { apiDatetimeToMs, parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

type Approval = ApprovalRead & { status: string };
const normalizeApproval = (approval: ApprovalRead): Approval => ({
  ...approval,
  status: approval.status ?? "pending",
});

type BoardApprovalsPanelProps = {
  boardId: string;
  approvals?: ApprovalRead[];
  isLoading?: boolean;
  error?: string | null;
  onDecision?: (approvalId: string, status: "approved" | "rejected") => void;
  scrollable?: boolean;
  boardLabelById?: Record<string, string>;
};

const formatTimestamp = (value?: string | null) => {
  if (!value) return "—";
  const date = parseApiDatetime(value);
  if (!date) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const statusBadgeClass = (status: string) => {
  if (status === "approved") {
    return "bg-emerald-50 text-emerald-700";
  }
  if (status === "rejected") {
    return "bg-rose-50 text-rose-700";
  }
  return "bg-amber-100 text-amber-700";
};

const confidenceBadgeClass = (confidence: number) => {
  if (confidence >= 90) {
    return "bg-emerald-50 text-emerald-700";
  }
  if (confidence >= 80) {
    return "bg-amber-100 text-amber-700";
  }
  return "bg-orange-100 text-orange-700";
};

const humanizeAction = (value: string) =>
  value
    .split(".")
    .map((part) =>
      part.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()),
    )
    .join(" · ");

const formatStatusLabel = (status: string) =>
  status.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());

const rubricColors = [
  "#0f172a",
  "#1d4ed8",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
];

type TooltipValue = number | string | Array<number | string>;

const formatRubricTooltipValue = (
  value?: TooltipValue,
  name?: TooltipValue,
  item?: {
    color?: string | null;
    payload?: {
      name?: string;
      fill?: string;
      percent?: number;
      percentLabel?: string;
    };
  } | null,
) => {
  const payload = item?.payload;
  const label =
    payload?.name ??
    (typeof name === "string" || typeof name === "number" ? String(name) : "");
  const percentLabel =
    payload?.percentLabel ??
    (typeof payload?.percent === "number" && Number.isFinite(payload.percent)
      ? `${payload.percent.toFixed(1)}%`
      : null);
  const fallback =
    value === null || value === undefined ? "" : String(value ?? "");
  const displayValue = percentLabel ?? fallback;
  const indicatorColor = payload?.fill ?? item?.color ?? "#94a3b8";

  return (
    <div className="flex w-full items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-slate-600">
        <span
          className="h-2.5 w-2.5 rounded-[2px]"
          style={{ backgroundColor: indicatorColor }}
        />
        <span>{label}</span>
      </span>
      <span className="font-mono font-medium tabular-nums text-slate-900">
        {displayValue}
      </span>
    </div>
  );
};

const payloadValue = (payload: Approval["payload"], key: string) => {
  if (!payload) return null;
  const value = payload[key as keyof typeof payload];
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return null;
};

const approvalSummary = (approval: Approval, boardLabel?: string | null) => {
  const payload = approval.payload ?? {};
  const taskId =
    approval.task_id ??
    payloadValue(payload, "task_id") ??
    payloadValue(payload, "taskId") ??
    payloadValue(payload, "taskID");
  const assignedAgentId =
    payloadValue(payload, "assigned_agent_id") ??
    payloadValue(payload, "assignedAgentId");
  const reason = payloadValue(payload, "reason");
  const title = payloadValue(payload, "title");
  const description = payloadValue(payload, "description");
  const role = payloadValue(payload, "role");
  const isAssign = approval.action_type.includes("assign");
  const rows: Array<{ label: string; value: string }> = [];
  if (boardLabel) rows.push({ label: "Board", value: boardLabel });
  if (taskId) rows.push({ label: "Task", value: taskId });
  if (isAssign) {
    rows.push({
      label: "Assignee",
      value: assignedAgentId ?? "Unassigned",
    });
  }
  if (title) rows.push({ label: "Title", value: title });
  if (role) rows.push({ label: "Role", value: role });
  return { taskId, reason, rows, description };
};

export function BoardApprovalsPanel({
  boardId,
  approvals: externalApprovals,
  isLoading: externalLoading,
  error: externalError,
  onDecision,
  scrollable = false,
  boardLabelById,
}: BoardApprovalsPanelProps) {
  const { isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const usingExternal = Array.isArray(externalApprovals);
  const approvalsKey = useMemo(
    () => getListApprovalsApiV1BoardsBoardIdApprovalsGetQueryKey(boardId),
    [boardId],
  );

  const approvalsQuery = useListApprovalsApiV1BoardsBoardIdApprovalsGet<
    listApprovalsApiV1BoardsBoardIdApprovalsGetResponse,
    ApiError
  >(boardId, undefined, {
    query: {
      enabled: Boolean(!usingExternal && isSignedIn && boardId),
      refetchInterval: 15_000,
      refetchOnMount: "always",
      retry: false,
    },
  });

  const updateApprovalMutation =
    useUpdateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch<ApiError>();

  const approvals = useMemo(() => {
    const raw = usingExternal
      ? (externalApprovals ?? [])
      : approvalsQuery.data?.status === 200
        ? (approvalsQuery.data.data.items ?? [])
        : [];
    return raw.map(normalizeApproval);
  }, [approvalsQuery.data, externalApprovals, usingExternal]);

  const loadingState = usingExternal
    ? (externalLoading ?? false)
    : approvalsQuery.isLoading;
  const errorState = usingExternal
    ? (externalError ?? null)
    : (error ?? approvalsQuery.error?.message ?? null);

  const handleDecision = useCallback(
    (approvalId: string, status: "approved" | "rejected") => {
      const pendingNext = [...approvals]
        .filter((item) => item.id !== approvalId)
        .filter((item) => item.status === "pending")
        .sort(
          (a, b) =>
            (apiDatetimeToMs(b.created_at) ?? 0) -
            (apiDatetimeToMs(a.created_at) ?? 0),
        )[0]?.id;
      if (pendingNext) {
        setSelectedId(pendingNext);
      }

      if (onDecision) {
        onDecision(approvalId, status);
        return;
      }
      if (usingExternal) return;
      if (!isSignedIn || !boardId) return;
      setUpdatingId(approvalId);
      setError(null);

      updateApprovalMutation.mutate(
        { boardId, approvalId, data: { status } },
        {
          onSuccess: (result) => {
            if (result.status !== 200) return;
            queryClient.setQueryData<listApprovalsApiV1BoardsBoardIdApprovalsGetResponse>(
              approvalsKey,
              (previous) => {
                if (!previous || previous.status !== 200) return previous;
                return {
                  ...previous,
                  data: {
                    ...previous.data,
                    items: previous.data.items.map((item) =>
                      item.id === approvalId ? result.data : item,
                    ),
                  },
                };
              },
            );
          },
          onError: (err) => {
            setError(err.message || "Unable to update approval.");
          },
          onSettled: () => {
            setUpdatingId(null);
            queryClient.invalidateQueries({ queryKey: approvalsKey });
          },
        },
      );
    },
    [
      approvals,
      approvalsKey,
      boardId,
      isSignedIn,
      onDecision,
      queryClient,
      updateApprovalMutation,
      usingExternal,
    ],
  );

  const sortedApprovals = useMemo(() => {
    const sortByTime = (items: Approval[]) =>
      [...items].sort((a, b) => {
        const aTime = apiDatetimeToMs(a.created_at) ?? 0;
        const bTime = apiDatetimeToMs(b.created_at) ?? 0;
        return bTime - aTime;
      });
    const pending = sortByTime(
      approvals.filter((item) => item.status === "pending"),
    );
    const resolved = sortByTime(
      approvals.filter((item) => item.status !== "pending"),
    );
    return { pending, resolved };
  }, [approvals]);

  const orderedApprovals = useMemo(
    () => [...sortedApprovals.pending, ...sortedApprovals.resolved],
    [sortedApprovals.pending, sortedApprovals.resolved],
  );

  const effectiveSelectedId = useMemo(() => {
    if (orderedApprovals.length === 0) return null;
    if (selectedId && orderedApprovals.some((item) => item.id === selectedId)) {
      return selectedId;
    }
    return orderedApprovals[0].id;
  }, [orderedApprovals, selectedId]);

  const selectedApproval = useMemo(() => {
    if (!effectiveSelectedId) return null;
    return (
      orderedApprovals.find((item) => item.id === effectiveSelectedId) ?? null
    );
  }, [effectiveSelectedId, orderedApprovals]);

  const pendingCount = sortedApprovals.pending.length;
  const resolvedCount = sortedApprovals.resolved.length;

  return (
    <div className={cn("space-y-6", scrollable && "h-full")}>
      {errorState ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {errorState}
        </div>
      ) : null}
      {loadingState ? (
        <p className="text-sm text-slate-500">Loading approvals…</p>
      ) : pendingCount === 0 && resolvedCount === 0 ? (
        <div
          className={cn(
            "rounded-xl border border-dashed border-slate-200 bg-white px-6 py-10 text-center",
            scrollable && "flex h-full items-center justify-center",
          )}
        >
          <div className="max-w-sm">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <p className="mt-4 text-sm font-semibold text-slate-900">
              All clear
            </p>
            <p className="mt-2 text-sm text-slate-500">
              No approvals to review right now. New approvals will show up here
              as soon as they arrive.
            </p>
          </div>
        </div>
      ) : (
        <div
          className={cn(
            "grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]",
            scrollable && "h-full",
          )}
        >
          <div
            className={cn(
              "overflow-hidden rounded-xl border border-slate-200 bg-white",
              scrollable && "flex min-h-0 flex-col",
            )}
          >
            <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                Unapproved tasks
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {pendingCount} pending · {resolvedCount} resolved
              </p>
            </div>
            <div
              className={cn(
                "divide-y divide-slate-100",
                scrollable && "min-h-0 overflow-y-auto",
              )}
            >
              {orderedApprovals.map((approval) => {
                const summary = approvalSummary(
                  approval,
                  boardLabelById?.[approval.board_id] ?? null,
                );
                const isSelected = effectiveSelectedId === approval.id;
                const isPending = approval.status === "pending";
                const titleRow = summary.rows.find(
                  (row) => row.label.toLowerCase() === "title",
                );
                const fallbackRow = summary.rows.find(
                  (row) =>
                    row.label.toLowerCase() !== "title" &&
                    row.label.toLowerCase() !== "board",
                );
                const primaryLabel =
                  titleRow?.value ?? fallbackRow?.value ?? "Untitled";
                const boardRow = summary.rows.find(
                  (row) => row.label.toLowerCase() === "board",
                );
                const boardText =
                  boardRow && boardRow.value !== primaryLabel
                    ? boardRow.value
                    : null;
                return (
                  <button
                    key={approval.id}
                    type="button"
                    onClick={() => setSelectedId(approval.id)}
                    className={cn(
                      "w-full px-4 py-4 text-left transition hover:bg-slate-50",
                      isSelected && "bg-amber-50 border-l-2 border-amber-500",
                      !isPending && "opacity-60",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                        {humanizeAction(approval.action_type)}
                      </span>
                      <span
                        className={cn(
                          "rounded-[3px] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em]",
                          statusBadgeClass(approval.status),
                        )}
                      >
                        {formatStatusLabel(approval.status)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-semibold text-slate-900">
                      {primaryLabel}
                    </p>
                    {boardText ? (
                      <p className="mt-1 text-xs text-slate-500">
                        Board · {boardText}
                      </p>
                    ) : null}
                    <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                      <Clock className="h-3.5 w-3.5 opacity-60" />
                      <span>{formatTimestamp(approval.created_at)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div
            className={cn(
              "overflow-hidden rounded-xl border border-slate-200 bg-white",
              scrollable && "flex min-h-0 flex-col",
            )}
          >
            <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                {selectedApproval?.status === "pending"
                  ? "Latest unapproved task"
                  : "Approval detail"}
              </p>
            </div>
            {!selectedApproval ? (
              <div className="flex h-full items-center justify-center px-6 py-10 text-sm text-slate-500">
                Select an approval to review details.
              </div>
            ) : (
              (() => {
                const summary = approvalSummary(
                  selectedApproval,
                  boardLabelById?.[selectedApproval.board_id] ?? null,
                );
                const titleRow = summary.rows.find(
                  (row) => row.label.toLowerCase() === "title",
                );
                const titleText = titleRow?.value?.trim() ?? "";
                const descriptionText = summary.description?.trim() ?? "";
                const reasoningText = summary.reason?.trim() ?? "";
                const extraRows = summary.rows.filter((row) => {
                  const normalized = row.label.toLowerCase();
                  if (normalized === "title") return false;
                  if (normalized === "task") return false;
                  if (normalized === "assignee") return false;
                  return true;
                });
                const rubricEntries = Object.entries(
                  selectedApproval.rubric_scores ?? {},
                ).map(([key, value]) => ({
                  label: key
                    .replace(/_/g, " ")
                    .replace(/\b\w/g, (char) => char.toUpperCase()),
                  value,
                }));
                const rubricTotal = rubricEntries.reduce(
                  (total, entry) => total + entry.value,
                  0,
                );
                const hasRubric = rubricEntries.length > 0 && rubricTotal > 0;
                const rubricChartData = rubricEntries.map((entry, index) => {
                  const percent =
                    rubricTotal > 0 ? (entry.value / rubricTotal) * 100 : 0;
                  return {
                    key: entry.label.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
                    name: entry.label,
                    value: entry.value,
                    percent,
                    percentLabel: `${percent.toFixed(1)}%`,
                    fill: rubricColors[index % rubricColors.length],
                  };
                });
                const rubricChartConfig = rubricChartData.reduce<ChartConfig>(
                  (accumulator, entry) => {
                    accumulator[entry.key] = {
                      label: entry.name,
                      color: entry.fill,
                    };
                    return accumulator;
                  },
                  {},
                );

                return (
                  <div className="flex h-full flex-col gap-6 px-6 py-6">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-lg font-semibold text-slate-900">
                          {humanizeAction(selectedApproval.action_type)}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          Requested{" "}
                          {formatTimestamp(selectedApproval.created_at)}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-3">
                        <span
                          className={cn(
                            "rounded-md px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em]",
                            confidenceBadgeClass(selectedApproval.confidence),
                          )}
                        >
                          {selectedApproval.confidence}% confidence
                        </span>
                        {selectedApproval.status === "pending" ? (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="primary"
                              size="sm"
                              onClick={() =>
                                handleDecision(selectedApproval.id, "approved")
                              }
                              disabled={updatingId === selectedApproval.id}
                              className="bg-slate-900 text-white hover:bg-slate-800"
                            >
                              Approve
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                handleDecision(selectedApproval.id, "rejected")
                              }
                              disabled={updatingId === selectedApproval.id}
                              className="border-slate-300 text-slate-700 hover:bg-slate-100"
                            >
                              Reject
                            </Button>
                          </div>
                        ) : null}
                      </div>
                    </div>

                    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                      <StatusDot
                        status={selectedApproval.status}
                        variant="approval"
                        className={cn("h-2 w-2 rounded-full")}
                      />
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                          Status
                        </p>
                        <p className="text-sm font-medium text-slate-700">
                          {formatStatusLabel(selectedApproval.status)} ·{" "}
                          {selectedApproval.status === "pending"
                            ? "Awaiting your decision"
                            : "Decision complete"}
                        </p>
                      </div>
                    </div>

                    {titleText ? (
                      <div className="space-y-2">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                          Title
                        </p>
                        <div className="text-sm font-medium text-slate-900">
                          {titleText}
                        </div>
                      </div>
                    ) : null}

                    {descriptionText ? (
                      <div className="space-y-2">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                          Description
                        </p>
                        <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                          {descriptionText}
                        </div>
                      </div>
                    ) : null}

                    {reasoningText ? (
                      <div className="space-y-2">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                          Lead reasoning
                        </p>
                        <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                          <p>{reasoningText}</p>
                        </div>
                      </div>
                    ) : null}

                    {extraRows.length > 0 ? (
                      <div className="space-y-2">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                          Details
                        </p>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {extraRows.map((row) => (
                            <div
                              key={`${selectedApproval.id}-${row.label}`}
                              className="rounded-lg border border-slate-200 bg-white px-3 py-2"
                            >
                              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                                {row.label}
                              </p>
                              <p className="mt-1 text-sm font-medium text-slate-900">
                                {row.value}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {hasRubric ? (
                      <div className="space-y-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                          Rubric scores
                        </p>
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                          <div className="w-full space-y-2 sm:max-w-[220px]">
                            {rubricChartData.map((entry) => (
                              <div
                                key={entry.key}
                                className="flex items-center justify-between gap-4 text-xs"
                              >
                                <div className="flex items-center gap-2">
                                  <span
                                    className="h-2.5 w-2.5 rounded-full"
                                    style={{ backgroundColor: entry.fill }}
                                  />
                                  <span className="text-slate-700">
                                    {entry.name}
                                  </span>
                                </div>
                                <span className="font-medium tabular-nums text-slate-900">
                                  {entry.percentLabel}
                                </span>
                              </div>
                            ))}
                          </div>
                          <ChartContainer
                            config={rubricChartConfig}
                            className="h-56 w-full max-w-[260px] aspect-square"
                          >
                            <PieChart>
                              {rubricTotal > 0 ? (
                                <ChartTooltip
                                  cursor={false}
                                  content={
                                    <ChartTooltipCard
                                      formatter={formatRubricTooltipValue}
                                      hideLabel
                                    />
                                  }
                                />
                              ) : null}
                              <Pie
                                data={rubricChartData}
                                dataKey="value"
                                nameKey="name"
                                innerRadius={50}
                                outerRadius={80}
                                strokeWidth={2}
                              >
                                {rubricChartData.map((entry) => (
                                  <Cell key={entry.key} fill={entry.fill} />
                                ))}
                              </Pie>
                            </PieChart>
                          </ChartContainer>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })()
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default BoardApprovalsPanel;
