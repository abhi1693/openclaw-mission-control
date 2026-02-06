"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { SignInButton, SignedIn, SignedOut, useAuth } from "@clerk/nextjs";
import { X } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  type getBoardApiV1BoardsBoardIdGetResponse,
  useGetBoardApiV1BoardsBoardIdGet,
  useUpdateBoardApiV1BoardsBoardIdPatch,
} from "@/api/generated/boards/boards";
import {
  type listGatewaysApiV1GatewaysGetResponse,
  useListGatewaysApiV1GatewaysGet,
} from "@/api/generated/gateways/gateways";
import type { BoardRead, BoardUpdate } from "@/api/generated/model";
import { BoardOnboardingChat } from "@/components/BoardOnboardingChat";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
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

const slugify = (value: string) =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "board";

const toDateInput = (value?: string | null) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
};

export default function EditBoardPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams();
  const boardIdParam = params?.boardId;
  const boardId = Array.isArray(boardIdParam) ? boardIdParam[0] : boardIdParam;

  const [board, setBoard] = useState<BoardRead | null>(null);
  const [name, setName] = useState<string | undefined>(undefined);
  const [gatewayId, setGatewayId] = useState<string | undefined>(undefined);
  const [boardType, setBoardType] = useState<string | undefined>(undefined);
  const [objective, setObjective] = useState<string | undefined>(undefined);
  const [successMetrics, setSuccessMetrics] = useState<string | undefined>(
    undefined,
  );
  const [targetDate, setTargetDate] = useState<string | undefined>(undefined);

  const [error, setError] = useState<string | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [isOnboardingOpen, setIsOnboardingOpen] = useState(false);

  const onboardingParam = searchParams.get("onboarding");
  const searchParamsString = searchParams.toString();
  const shouldAutoOpenOnboarding =
    onboardingParam !== null &&
    onboardingParam !== "" &&
    onboardingParam !== "0" &&
    onboardingParam.toLowerCase() !== "false";

  useEffect(() => {
    if (!boardId) return;
    if (!shouldAutoOpenOnboarding) return;

    setIsOnboardingOpen(true);

    // Remove the flag from the URL so refreshes don't constantly reopen it.
    const nextParams = new URLSearchParams(searchParamsString);
    nextParams.delete("onboarding");
    const qs = nextParams.toString();
    router.replace(qs ? `/boards/${boardId}/edit?${qs}` : `/boards/${boardId}/edit`);
  }, [boardId, router, searchParamsString, shouldAutoOpenOnboarding]);

  const gatewaysQuery = useListGatewaysApiV1GatewaysGet<
    listGatewaysApiV1GatewaysGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const boardQuery = useGetBoardApiV1BoardsBoardIdGet<
    getBoardApiV1BoardsBoardIdGetResponse,
    ApiError
  >(boardId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && boardId),
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

  const gateways =
    gatewaysQuery.data?.status === 200
      ? gatewaysQuery.data.data.items ?? []
      : [];
  const loadedBoard: BoardRead | null =
    boardQuery.data?.status === 200 ? boardQuery.data.data : null;
  const baseBoard = board ?? loadedBoard;

  const resolvedName = name ?? baseBoard?.name ?? "";
  const resolvedGatewayId = gatewayId ?? baseBoard?.gateway_id ?? "";
  const resolvedBoardType = boardType ?? baseBoard?.board_type ?? "goal";
  const resolvedObjective = objective ?? baseBoard?.objective ?? "";
  const resolvedSuccessMetrics =
    successMetrics ??
    (baseBoard?.success_metrics
      ? JSON.stringify(baseBoard.success_metrics, null, 2)
      : "");
  const resolvedTargetDate =
    targetDate ?? toDateInput(baseBoard?.target_date);

  const displayGatewayId = resolvedGatewayId || gateways[0]?.id || "";

  const isLoading =
    gatewaysQuery.isLoading || boardQuery.isLoading || updateBoardMutation.isPending;
  const errorMessage =
    error ??
    gatewaysQuery.error?.message ??
    boardQuery.error?.message ??
    null;

  const isFormReady = Boolean(resolvedName.trim() && displayGatewayId);

  const gatewayOptions = useMemo(
    () => gateways.map((gateway) => ({ value: gateway.id, label: gateway.name })),
    [gateways],
  );

  const handleOnboardingConfirmed = (updated: BoardRead) => {
    setBoard(updated);
    setBoardType(updated.board_type ?? "goal");
    setObjective(updated.objective ?? "");
    setSuccessMetrics(
      updated.success_metrics ? JSON.stringify(updated.success_metrics, null, 2) : "",
    );
    setTargetDate(toDateInput(updated.target_date));
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

    setError(null);
    setMetricsError(null);

    let parsedMetrics: Record<string, unknown> | null = null;
    if (resolvedSuccessMetrics.trim()) {
      try {
        parsedMetrics = JSON.parse(resolvedSuccessMetrics) as Record<string, unknown>;
      } catch {
        setMetricsError("Success metrics must be valid JSON.");
        return;
      }
    }

    const payload: BoardUpdate = {
      name: trimmedName,
      slug: slugify(trimmedName),
      gateway_id: resolvedGatewayId || null,
      board_type: resolvedBoardType,
      objective: resolvedObjective.trim() || null,
      success_metrics: parsedMetrics,
      target_date: resolvedTargetDate
        ? new Date(resolvedTargetDate).toISOString()
        : null,
    };

    updateBoardMutation.mutate({ boardId, data: payload });
  };

  return (
    <>
      <DashboardShell>
      <SignedOut>
        <div className="col-span-2 flex min-h-[calc(100vh-64px)] items-center justify-center bg-slate-50 p-10 text-center">
          <div className="rounded-xl border border-slate-200 bg-white px-8 py-6 shadow-sm">
            <p className="text-sm text-slate-600">Sign in to edit boards.</p>
            <SignInButton
              mode="modal"
              forceRedirectUrl={`/boards/${boardId}/edit`}
              signUpForceRedirectUrl={`/boards/${boardId}/edit`}
            >
              <Button className="mt-4">Sign in</Button>
            </SignInButton>
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          <div className="border-b border-slate-200 bg-white px-8 py-6">
            <div>
              <h1 className="font-heading text-2xl font-semibold text-slate-900 tracking-tight">
                Edit board
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                Update board settings and gateway.
              </p>
            </div>
          </div>

          <div className="p-8">
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
                        Start onboarding to draft an objective and success
                        metrics.
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
                    <p>No gateways available. Create one in Gateways to continue.</p>
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
                  <Button type="submit" disabled={isLoading || !baseBoard || !isFormReady}>
                    {isLoading ? "Saving…" : "Save changes"}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        </main>
      </SignedIn>
      </DashboardShell>
      <Dialog open={isOnboardingOpen} onOpenChange={setIsOnboardingOpen}>
        <DialogContent
          aria-label="Board onboarding"
          className="relative"
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
        >
          <DialogClose asChild>
            <button
              type="button"
              className="absolute right-4 top-4 rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
              aria-label="Close onboarding"
            >
              <X className="h-4 w-4" />
            </button>
          </DialogClose>
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
