"use client";

export const dynamic = "force-dynamic";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  updateBoardApiV1BoardsBoardIdPatch,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  type getBoardGroupApiV1BoardGroupsGroupIdGetResponse,
  useGetBoardGroupApiV1BoardGroupsGroupIdGet,
  useUpdateBoardGroupApiV1BoardGroupsGroupIdPatch,
} from "@/api/generated/board-groups/board-groups";
import type {
  BoardGroupRead,
  BoardGroupUpdate,
  BoardRead,
} from "@/api/generated/model";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const slugify = (value: string) =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "group";

export default function EditBoardGroupPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams();
  const groupIdParam = params?.groupId;
  const groupId = Array.isArray(groupIdParam) ? groupIdParam[0] : groupIdParam;

  const [name, setName] = useState<string | undefined>(undefined);
  const [description, setDescription] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const [boardSearch, setBoardSearch] = useState("");
  const [selectedBoardIds, setSelectedBoardIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [isAssignmentsSaving, setIsAssignmentsSaving] = useState(false);
  const [assignmentsError, setAssignmentsError] = useState<string | null>(null);
  const [assignmentsResult, setAssignmentsResult] = useState<{
    updated: number;
    failed: number;
  } | null>(null);

  const assignFailedParam = searchParams.get("assign_failed");
  const assignFailedCount = assignFailedParam
    ? Number.parseInt(assignFailedParam, 10)
    : null;

  const groupQuery = useGetBoardGroupApiV1BoardGroupsGroupIdGet<
    getBoardGroupApiV1BoardGroupsGroupIdGetResponse,
    ApiError
  >(groupId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && groupId),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const loadedGroup: BoardGroupRead | null =
    groupQuery.data?.status === 200 ? groupQuery.data.data : null;
  const baseGroup = loadedGroup;

  const resolvedName = name ?? baseGroup?.name ?? "";
  const resolvedDescription = description ?? baseGroup?.description ?? "";

  const allBoardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchOnMount: "always",
        retry: false,
      },
    },
  );

  const groupBoardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(
    { limit: 200, board_group_id: groupId ?? null },
    {
      query: {
        enabled: Boolean(isSignedIn && groupId),
        refetchOnMount: "always",
        retry: false,
      },
    },
  );

  const allBoards = useMemo<BoardRead[]>(() => {
    if (allBoardsQuery.data?.status !== 200) return [];
    return allBoardsQuery.data.data.items ?? [];
  }, [allBoardsQuery.data]);

  const groupBoards = useMemo<BoardRead[]>(() => {
    if (groupBoardsQuery.data?.status !== 200) return [];
    return groupBoardsQuery.data.data.items ?? [];
  }, [groupBoardsQuery.data]);

  const boards = useMemo<BoardRead[]>(() => {
    const byId = new Map<string, BoardRead>();
    for (const board of allBoards) {
      byId.set(board.id, board);
    }
    for (const board of groupBoards) {
      byId.set(board.id, board);
    }
    const merged = Array.from(byId.values());
    merged.sort((a, b) => a.name.localeCompare(b.name));
    return merged;
  }, [allBoards, groupBoards]);

  const initializedSelectionRef = useRef(false);

  useEffect(() => {
    if (!groupId) return;
    if (initializedSelectionRef.current) return;
    if (groupBoardsQuery.data?.status !== 200) return;
    initializedSelectionRef.current = true;
    setSelectedBoardIds(new Set(groupBoards.map((board) => board.id)));
  }, [groupBoards, groupBoardsQuery.data, groupId]);

  const updateMutation =
    useUpdateBoardGroupApiV1BoardGroupsGroupIdPatch<ApiError>({
      mutation: {
        retry: false,
      },
    });

  const isGroupSaving = groupQuery.isLoading || updateMutation.isPending;
  const boardsLoading = allBoardsQuery.isLoading || groupBoardsQuery.isLoading;
  const boardsError = groupBoardsQuery.error ?? allBoardsQuery.error ?? null;
  const isBoardsBusy = boardsLoading || isAssignmentsSaving;
  const isLoading = isGroupSaving || isBoardsBusy;
  const errorMessage = error ?? groupQuery.error?.message ?? null;
  const isFormReady = Boolean(resolvedName.trim());

  const handleSaveAssignments = async (): Promise<{
    updated: number;
    failed: number;
  } | null> => {
    if (!isSignedIn || !groupId) return null;
    if (groupBoardsQuery.data?.status !== 200) {
      setAssignmentsError("Group boards are not loaded yet.");
      return null;
    }

    setAssignmentsError(null);
    setAssignmentsResult(null);

    const desired = selectedBoardIds;
    const current = new Set(groupBoards.map((board) => board.id));
    const toAdd = Array.from(desired).filter((id) => !current.has(id));
    const toRemove = Array.from(current).filter((id) => !desired.has(id));

    const failures: string[] = [];
    let updated = 0;

    for (const boardId of toAdd) {
      try {
        const result = await updateBoardApiV1BoardsBoardIdPatch(boardId, {
          board_group_id: groupId,
        });
        if (result.status === 200) {
          updated += 1;
        } else {
          failures.push(boardId);
        }
      } catch {
        failures.push(boardId);
      }
    }

    for (const boardId of toRemove) {
      try {
        const result = await updateBoardApiV1BoardsBoardIdPatch(boardId, {
          board_group_id: null,
        });
        if (result.status === 200) {
          updated += 1;
        } else {
          failures.push(boardId);
        }
      } catch {
        failures.push(boardId);
      }
    }

    setAssignmentsResult({ updated, failed: failures.length });
    if (failures.length > 0) {
      setAssignmentsError(
        `Failed to update ${failures.length} board assignment${
          failures.length === 1 ? "" : "s"
        }.`,
      );
    }

    void groupBoardsQuery.refetch();
    void allBoardsQuery.refetch();

    return { updated, failed: failures.length };
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn || !groupId) return;
    const trimmedName = resolvedName.trim();
    if (!trimmedName) {
      setError("Group name is required.");
      return;
    }

    setError(null);
    setAssignmentsError(null);
    setAssignmentsResult(null);

    const payload: BoardGroupUpdate = {
      name: trimmedName,
      slug: slugify(trimmedName),
      description: resolvedDescription.trim() || null,
    };

    setIsAssignmentsSaving(true);
    try {
      const result = await updateMutation.mutateAsync({
        groupId,
        data: payload,
      });
      if (result.status !== 200) {
        setError("Something went wrong.");
        return;
      }

      const assignments = await handleSaveAssignments();
      if (!assignments || assignments.failed > 0) {
        return;
      }

      router.push(`/board-groups/${result.data.id}`);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : null;
      setError(message || "Something went wrong.");
    } finally {
      setIsAssignmentsSaving(false);
    }
  };

  const title = useMemo(
    () => baseGroup?.name ?? "Edit group",
    [baseGroup?.name],
  );

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to edit board groups.",
        forceRedirectUrl: `/board-groups/${groupId ?? ""}/edit`,
      }}
      title={title}
      description="Update the shared context that connects boards in this group."
    >
      <form
        onSubmit={handleSubmit}
        className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        {assignFailedCount && Number.isFinite(assignFailedCount) ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 shadow-sm">
            Group was created, but {assignFailedCount} board assignment
            {assignFailedCount === 1 ? "" : "s"} failed. You can retry below.
          </div>
        ) : null}
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-900">
              Group name <span className="text-red-500">*</span>
            </label>
            <Input
              value={resolvedName}
              onChange={(event) => setName(event.target.value)}
              placeholder="Group name"
              disabled={isLoading || !baseGroup}
            />
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Description
          </label>
          <Textarea
            value={resolvedDescription}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What ties these boards together?"
            className="min-h-[120px]"
            disabled={isLoading || !baseGroup}
          />
        </div>

        <div className="space-y-2 border-t border-slate-100 pt-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-slate-900">Boards</p>
              <p className="mt-1 text-xs text-slate-500">
                Assign boards to this group to share context across related
                work.
              </p>
            </div>
            <span className="text-xs text-slate-500">
              {selectedBoardIds.size} selected
            </span>
          </div>

          <Input
            value={boardSearch}
            onChange={(event) => setBoardSearch(event.target.value)}
            placeholder="Search boards..."
            disabled={isLoading || !baseGroup}
          />

          <div className="max-h-64 overflow-auto rounded-xl border border-slate-200 bg-slate-50/40">
            {boardsLoading && boards.length === 0 ? (
              <div className="px-4 py-6 text-sm text-slate-500">
                Loading boards…
              </div>
            ) : boardsError ? (
              <div className="px-4 py-6 text-sm text-rose-700">
                {boardsError.message}
              </div>
            ) : boards.length === 0 ? (
              <div className="px-4 py-6 text-sm text-slate-500">
                No boards found.
              </div>
            ) : (
              <ul className="divide-y divide-slate-200">
                {boards
                  .filter((board) => {
                    const q = boardSearch.trim().toLowerCase();
                    if (!q) return true;
                    return (
                      board.name.toLowerCase().includes(q) ||
                      board.slug.toLowerCase().includes(q)
                    );
                  })
                  .map((board) => {
                    const checked = selectedBoardIds.has(board.id);
                    const isInThisGroup = board.board_group_id === groupId;
                    const isAlreadyGrouped =
                      Boolean(board.board_group_id) && !isInThisGroup;
                    return (
                      <li key={board.id} className="px-4 py-3">
                        <label className="flex cursor-pointer items-start gap-3">
                          <input
                            type="checkbox"
                            className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600"
                            checked={checked}
                            onChange={() => {
                              setSelectedBoardIds((prev) => {
                                const next = new Set(prev);
                                if (next.has(board.id)) {
                                  next.delete(board.id);
                                } else {
                                  next.add(board.id);
                                }
                                return next;
                              });
                            }}
                            disabled={isLoading || !baseGroup}
                          />
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-slate-900">
                              {board.name}
                            </p>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                              <span className="font-mono text-[11px] text-slate-400">
                                {board.id}
                              </span>
                              {isAlreadyGrouped ? (
                                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-amber-900">
                                  in another group
                                </span>
                              ) : null}
                            </div>
                          </div>
                        </label>
                      </li>
                    );
                  })}
              </ul>
            )}
          </div>

          {assignmentsError ? (
            <p className="text-sm text-rose-700">{assignmentsError}</p>
          ) : null}
          {assignmentsResult ? (
            <p className="text-sm text-slate-700">
              Updated {assignmentsResult.updated} board
              {assignmentsResult.updated === 1 ? "" : "s"}, failed{" "}
              {assignmentsResult.failed}.
            </p>
          ) : null}
        </div>

        {errorMessage ? (
          <p className="text-sm text-red-500">{errorMessage}</p>
        ) : null}

        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="ghost"
            onClick={() => router.push(`/board-groups/${groupId ?? ""}`)}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={isLoading || !baseGroup || !isFormReady}
          >
            {isLoading ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>
    </DashboardPageLayout>
  );
}
