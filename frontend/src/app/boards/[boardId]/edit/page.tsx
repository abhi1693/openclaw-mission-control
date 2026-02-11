"use client";

export const dynamic = "force-dynamic";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { X } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type getBoardApiV1BoardsBoardIdGetResponse,
  useGetBoardApiV1BoardsBoardIdGet,
  useUpdateBoardApiV1BoardsBoardIdPatch,
} from "@/api/generated/boards/boards";
import {
  type listBoardGroupsApiV1BoardGroupsGetResponse,
  useListBoardGroupsApiV1BoardGroupsGet,
} from "@/api/generated/board-groups/board-groups";
import {
  type listGatewaysApiV1GatewaysGetResponse,
  useListGatewaysApiV1GatewaysGet,
} from "@/api/generated/gateways/gateways";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type {
  BoardGroupRead,
  BoardRead,
  BoardUpdate,
} from "@/api/generated/model";
import { BoardOnboardingChat } from "@/components/BoardOnboardingChat";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import SearchableSelect from "@/components/ui/searchable-select";
import { Textarea } from "@/components/ui/textarea";
import { localDateInputToUtcIso, toLocalDateInput } from "@/lib/datetime";

const slugify = (value: string) =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "board";

export default function EditBoardPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams();
  const boardIdParam = params?.boardId;
  const boardId = Array.isArray(boardIdParam) ? boardIdParam[0] : boardIdParam;

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const mainRef = useRef<HTMLElement | null>(null);

  const [board, setBoard] = useState<BoardRead | null>(null);
  const [name, setName] = useState<string | undefined>(undefined);
  const [description, setDescription] = useState<string | undefined>(undefined);
  const [gatewayId, setGatewayId] = useState<string | undefined>(undefined);
  const [boardGroupId, setBoardGroupId] = useState<string | undefined>(
    undefined,
  );
  const [boardType, setBoardType] = useState<string | undefined>(undefined);
  const [objective, setObjective] = useState<string | undefined>(undefined);
  const [successMetrics, setSuccessMetrics] = useState<string | undefined>(
    undefined,
  );
  const [targetDate, setTargetDate] = useState<string | undefined>(undefined);

  const [error, setError] = useState<string | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);

  const onboardingParam = searchParams.get("onboarding");
  const searchParamsString = searchParams.toString();
  const shouldAutoOpenOnboarding =
    onboardingParam !== null &&
    onboardingParam !== "" &&
    onboardingParam !== "0" &&
    onboardingParam.toLowerCase() !== "false";

  const [isOnboardingOpen, setIsOnboardingOpen] = useState(
    shouldAutoOpenOnboarding,
  );

  useEffect(() => {
    if (!isOnboardingOpen) return;

    const mainEl = mainRef.current;
    const previousMainOverflow = mainEl?.style.overflow ?? "";
    const previousHtmlOverflow = document.documentElement.style.overflow;
    const previousBodyOverflow = document.body.style.overflow;

    if (mainEl) {
      mainEl.style.overflow = "hidden";
    }
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";

    return () => {
      if (mainEl) {
        mainEl.style.overflow = previousMainOverflow;
      }
      document.documentElement.style.overflow = previousHtmlOverflow;
      document.body.style.overflow = previousBodyOverflow;
    };
  }, [isOnboardingOpen]);

  useEffect(() => {
    if (!boardId) return;
    if (!shouldAutoOpenOnboarding) return;

    // Remove the flag from the URL so refreshes don't constantly reopen it.
    const nextParams = new URLSearchParams(searchParamsString);
    nextParams.delete("onboarding");
    const qs = nextParams.toString();
    router.replace(
      qs ? `/boards/${boardId}/edit?${qs}` : `/boards/${boardId}/edit`,
    );
  }, [boardId, router, searchParamsString, shouldAutoOpenOnboarding]);

  const gatewaysQuery = useListGatewaysApiV1GatewaysGet<
    listGatewaysApiV1GatewaysGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const groupsQuery = useListBoardGroupsApiV1BoardGroupsGet<
    listBoardGroupsApiV1BoardGroupsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const boardQuery = useGetBoardApiV1BoardsBoardIdGet<
    getBoardApiV1BoardsBoardIdGetResponse,
    ApiError
  >(boardId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && boardId),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const updateBoardMutation = useUpdateBoardApiV1BoardsBoardIdPatch<ApiError>({
    mutation: {
      onSuccess: (result) => {
        if (result.status === 200) {
          router.push(`/boards/${result.data.id}`);
        }
      },
      onError: (err) => {
        setError(err.message || "Something went wrong.");
      },
    },
  });

  const gateways = useMemo(() => {
    if (gatewaysQuery.data?.status !== 200) return [];
    return gatewaysQuery.data.data.items ?? [];
  }, [gatewaysQuery.data]);
  const loadedBoard: BoardRead | null =
    boardQuery.data?.status === 200 ? boardQuery.data.data : null;
  const baseBoard = board ?? loadedBoard;

  const resolvedName = name ?? baseBoard?.name ?? "";
  const resolvedDescription = description ?? baseBoard?.description ?? "";
  const resolvedGatewayId = gatewayId ?? baseBoard?.gateway_id ?? "";
  const resolvedBoardGroupId =
    boardGroupId ?? baseBoard?.board_group_id ?? "none";
  const resolvedBoardType = boardType ?? baseBoard?.board_type ?? "goal";
  const resolvedObjective = objective ?? baseBoard?.objective ?? "";
  const resolvedSuccessMetrics =
    successMetrics ??
    (baseBoard?.success_metrics
      ? JSON.stringify(baseBoard.success_metrics, null, 2)
      : "");
  const resolvedTargetDate =
    targetDate ?? toLocalDateInput(baseBoard?.target_date);

  const displayGatewayId = resolvedGatewayId || gateways[0]?.id || "";

  const isLoading =
    gatewaysQuery.isLoading ||
    groupsQuery.isLoading ||
    boardQuery.isLoading ||
    updateBoardMutation.isPending;
  const errorMessage =
    error ??
    gatewaysQuery.error?.message ??
    groupsQuery.error?.message ??
    boardQuery.error?.message ??
    null;

  const isFormReady = Boolean(
    resolvedName.trim() && resolvedDescription.trim() && displayGatewayId,
  );

  const gatewayOptions = useMemo(
    () =>
      gateways.map((gateway) => ({ value: gateway.id, label: gateway.name })),
    [gateways],
  );

  const groups = useMemo<BoardGroupRead[]>(() => {
    if (groupsQuery.data?.status !== 200) return [];
    return groupsQuery.data.data.items ?? [];
  }, [groupsQuery.data]);
  const groupOptions = useMemo(
    () => [
      { value: "none", label: "No group" },
      ...groups.map((group) => ({ value: group.id, label: group.name })),
    ],
    [groups],
  );

  const handleOnboardingConfirmed = (updated: BoardRead) => {
    setBoard(updated);
    setDescription(updated.description ?? "");
    setBoardType(updated.board_type ?? "goal");
    setObjective(updated.objective ?? "");
    setSuccessMetrics(
      updated.success_metrics
        ? JSON.stringify(updated.success_metrics, null, 2)
        : "",
    );
    setTargetDate(toLocalDateInput(updated.target_date));
    setBoardGroupId(updated.board_group_id ?? "none");
    setIsOnboardingOpen(false);
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn || !boardId) return;
    const trimmedName = resolvedName.trim();
    if (!trimmedName) {
      setError("Board name is required.");
      return;
    }
    const resolvedGatewayId = displayGatewayId;
    if (!resolvedGatewayId) {
      setError("Select a gateway before saving.");
      return;
    }
    const trimmedDescription = resolvedDescription.trim();
    if (!trimmedDescription) {
      setError("Board description is required.");
      return;
    }

    setError(null);
    setMetricsError(null);

    let parsedMetrics: Record<string, unknown> | null = null;
    if (resolvedSuccessMetrics.trim()) {
      try {
        parsedMetrics = JSON.parse(resolvedSuccessMetrics) as Record<
          string,
          unknown
        >;
      } catch {
        setMetricsError("Success metrics must be valid JSON.");
        return;
      }
    }

    const payload: BoardUpdate = {
      name: trimmedName,
      slug: slugify(trimmedName),
      description: trimmedDescription,
      gateway_id: resolvedGatewayId || null,
      board_group_id:
        resolvedBoardGroupId === "none" ? null : resolvedBoardGroupId,
      board_type: resolvedBoardType,
      objective: resolvedObjective.trim() || null,
      success_metrics: parsedMetrics,
      target_date: localDateInputToUtcIso(resolvedTargetDate),
    };

    updateBoardMutation.mutate({ boardId, data: payload });
  };

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to edit boards.",
          forceRedirectUrl: `/boards/${boardId}/edit`,
          signUpForceRedirectUrl: `/boards/${boardId}/edit`,
        }}
        title="Edit board"
        description="Update board settings and gateway."
        isAdmin={isAdmin}
        adminOnlyMessage="Only organization owners and admins can edit board settings."
        mainRef={mainRef}
      >
        <div className="space-y-6">
          <form
            onSubmit={handleSubmit}
            className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
          >
            {resolvedBoardType !== "general" &&
            baseBoard &&
            !(baseBoard.goal_confirmed ?? false) ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-amber-900">
                    Goal needs confirmation
                  </p>
                  <p className="mt-1 text-xs text-amber-800/80">
                    Start onboarding to draft an objective and success metrics.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setIsOnboardingOpen(true)}
                  disabled={isLoading || !baseBoard}
                >
                  Start onboarding
                </Button>
              </div>
            ) : null}
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Board name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={resolvedName}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Board name"
                  disabled={isLoading || !baseBoard}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Gateway <span className="text-red-500">*</span>
                </label>
                <SearchableSelect
                  ariaLabel="Select gateway"
                  value={displayGatewayId}
                  onValueChange={setGatewayId}
                  options={gatewayOptions}
                  placeholder="Select gateway"
                  searchPlaceholder="Search gateways..."
                  emptyMessage="No gateways found."
                  triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  contentClassName="rounded-xl border border-slate-200 shadow-lg"
                  itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                />
              </div>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Board type
                </label>
                <Select value={resolvedBoardType} onValueChange={setBoardType}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select board type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="goal">Goal</SelectItem>
                    <SelectItem value="general">General</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Board group
                </label>
                <SearchableSelect
                  ariaLabel="Select board group"
                  value={resolvedBoardGroupId}
                  onValueChange={setBoardGroupId}
                  options={groupOptions}
                  placeholder="No group"
                  searchPlaceholder="Search groups..."
                  emptyMessage="No groups found."
                  triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  contentClassName="rounded-xl border border-slate-200 shadow-lg"
                  itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                  disabled={isLoading}
                />
                <p className="text-xs text-slate-500">
                  Boards in the same group can share cross-board context for
                  agents.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Target date
                </label>
                <Input
                  type="date"
                  value={resolvedTargetDate}
                  onChange={(event) => setTargetDate(event.target.value)}
                  disabled={isLoading}
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Description <span className="text-red-500">*</span>
              </label>
              <Textarea
                value={resolvedDescription}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What context should the lead agent know?"
                className="min-h-[120px]"
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Objective
              </label>
              <Textarea
                value={resolvedObjective}
                onChange={(event) => setObjective(event.target.value)}
                placeholder="What should this board achieve?"
                className="min-h-[120px]"
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Success metrics (JSON)
              </label>
              <Textarea
                value={resolvedSuccessMetrics}
                onChange={(event) => setSuccessMetrics(event.target.value)}
                placeholder='e.g. { "target": "Launch by week 2" }'
                className="min-h-[140px] font-mono text-xs"
                disabled={isLoading}
              />
              <p className="text-xs text-slate-500">
                Add key outcomes so the lead agent can measure progress.
              </p>
              {metricsError ? (
                <p className="text-xs text-red-500">{metricsError}</p>
              ) : null}
            </div>

            {gateways.length === 0 ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <p>
                  No gateways available. Create one in Gateways to continue.
                </p>
              </div>
            ) : null}

            {errorMessage ? (
              <p className="text-sm text-red-500">{errorMessage}</p>
            ) : null}

            <div className="flex justify-end gap-3">
              <Button
                type="button"
                variant="ghost"
                onClick={() => router.push(`/boards/${boardId}`)}
                disabled={isLoading}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={isLoading || !baseBoard || !isFormReady}
              >
                {isLoading ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </form>
        </div>
      </DashboardPageLayout>
      <Dialog open={isOnboardingOpen} onOpenChange={setIsOnboardingOpen}>
        <DialogContent
          aria-label="Board onboarding"
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
        >
          <div className="flex">
            <DialogClose asChild>
              <button
                type="button"
                className="sticky top-4 z-10 ml-auto rounded-lg border border-slate-200 bg-[color:var(--surface)] p-2 text-slate-500 transition hover:bg-slate-50"
                aria-label="Close onboarding"
              >
                <X className="h-4 w-4" />
              </button>
            </DialogClose>
          </div>
          {boardId ? (
            <BoardOnboardingChat
              boardId={boardId}
              onConfirmed={handleOnboardingConfirmed}
            />
          ) : (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
              Unable to start onboarding.
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
