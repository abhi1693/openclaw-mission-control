"use client";

export const dynamic = "force-dynamic";

import { useCallback, useMemo } from "react";

import { SignedIn, SignedOut, SignInButton, useAuth } from "@/auth/clerk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "@/api/mutator";
import {
  listApprovalsApiV1BoardsBoardIdApprovalsGet,
  updateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch,
} from "@/api/generated/approvals/approvals";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import type { ApprovalRead, BoardRead } from "@/api/generated/model";
import { BoardApprovalsPanel } from "@/components/BoardApprovalsPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { Button } from "@/components/ui/button";

type GlobalApprovalsData = {
  approvals: ApprovalRead[];
  warnings: string[];
};

function GlobalApprovalsInner() {
  const { isSignedIn } = useAuth();
  const queryClient = useQueryClient();

  const boardsQuery = useListBoardsApiV1BoardsGet(undefined, {
    query: {
      enabled: Boolean(isSignedIn),
      refetchInterval: 30_000,
      refetchOnMount: "always",
      retry: false,
    },
    request: { cache: "no-store" },
  });

  const boards = useMemo(() => {
    if (boardsQuery.data?.status !== 200) return [];
    return boardsQuery.data.data.items ?? [];
  }, [boardsQuery.data]);

  const boardLabelById = useMemo(() => {
    const entries = boards.map((board: BoardRead) => [board.id, board.name]);
    return Object.fromEntries(entries) as Record<string, string>;
  }, [boards]);

  const boardIdsKey = useMemo(() => {
    const ids = boards.map((board) => board.id);
    ids.sort();
    return ids.join(",");
  }, [boards]);

  const approvalsKey = useMemo(
    () => ["approvals", "global", boardIdsKey] as const,
    [boardIdsKey],
  );

  const approvalsQuery = useQuery<GlobalApprovalsData, ApiError>({
    queryKey: approvalsKey,
    enabled: Boolean(isSignedIn && boards.length > 0),
    refetchInterval: 15_000,
    refetchOnMount: "always",
    retry: false,
    queryFn: async () => {
      const results = await Promise.allSettled(
        boards.map(async (board) => {
          const response = await listApprovalsApiV1BoardsBoardIdApprovalsGet(
            board.id,
            { limit: 200 },
            { cache: "no-store" },
          );
          if (response.status !== 200) {
            throw new Error(
              `Failed to load approvals for ${board.name} (status ${response.status}).`,
            );
          }
          return { boardId: board.id, approvals: response.data.items ?? [] };
        }),
      );

      const approvals: ApprovalRead[] = [];
      const warnings: string[] = [];

      for (const result of results) {
        if (result.status === "fulfilled") {
          approvals.push(...result.value.approvals);
        } else {
          warnings.push(result.reason?.message ?? "Unable to load approvals.");
        }
      }

      return { approvals, warnings };
    },
  });

  const updateApprovalMutation = useMutation<
    Awaited<
      ReturnType<
        typeof updateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch
      >
    >,
    ApiError,
    { boardId: string; approvalId: string; status: "approved" | "rejected" }
  >({
    mutationFn: ({ boardId, approvalId, status }) =>
      updateApprovalApiV1BoardsBoardIdApprovalsApprovalIdPatch(
        boardId,
        approvalId,
        { status },
        { cache: "no-store" },
      ),
  });

  const approvals = useMemo(
    () => approvalsQuery.data?.approvals ?? [],
    [approvalsQuery.data],
  );
  const warnings = useMemo(
    () => approvalsQuery.data?.warnings ?? [],
    [approvalsQuery.data],
  );
  const errorText = approvalsQuery.error?.message ?? null;

  const handleDecision = useCallback(
    (approvalId: string, status: "approved" | "rejected") => {
      const approval = approvals.find((item) => item.id === approvalId);
      const boardId = approval?.board_id;
      if (!boardId) return;

      updateApprovalMutation.mutate(
        { boardId, approvalId, status },
        {
          onSuccess: (result) => {
            if (result.status !== 200) return;
            queryClient.setQueryData<GlobalApprovalsData>(
              approvalsKey,
              (prev) => {
                if (!prev) return prev;
                return {
                  ...prev,
                  approvals: prev.approvals.map((item) =>
                    item.id === approvalId ? result.data : item,
                  ),
                };
              },
            );
          },
          onSettled: () => {
            queryClient.invalidateQueries({ queryKey: approvalsKey });
          },
        },
      );
    },
    [approvals, approvalsKey, queryClient, updateApprovalMutation],
  );

  const combinedError = useMemo(() => {
    const parts: string[] = [];
    if (errorText) parts.push(errorText);
    if (warnings.length > 0) parts.push(warnings.join(" "));
    return parts.length > 0 ? parts.join(" ") : null;
  }, [errorText, warnings]);

  return (
    <main className="flex-1 overflow-y-auto bg-gradient-to-br from-slate-50 to-slate-100">
      <div className="p-4 md:p-6">
        <div className="h-[calc(100vh-160px)] min-h-[300px] sm:min-h-[520px]">
          <BoardApprovalsPanel
            boardId="global"
            approvals={approvals}
            isLoading={boardsQuery.isLoading || approvalsQuery.isLoading}
            error={combinedError}
            onDecision={handleDecision}
            scrollable
            boardLabelById={boardLabelById}
          />
        </div>
      </div>
    </main>
  );
}

export default function GlobalApprovalsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl surface-panel p-10 text-center">
          <p className="text-sm text-muted">Sign in to view approvals.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/approvals"
            signUpForceRedirectUrl="/approvals"
          >
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <GlobalApprovalsInner />
      </SignedIn>
    </DashboardShell>
  );
}
