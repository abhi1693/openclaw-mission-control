"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  updateBoardApiV1BoardsBoardIdPatch,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { useCreateBoardGroupApiV1BoardGroupsPost } from "@/api/generated/board-groups/board-groups";
import type { BoardRead } from "@/api/generated/model";
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

export default function NewBoardGroupPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [boardSearch, setBoardSearch] = useState("");
  const [selectedBoardIds, setSelectedBoardIds] = useState<Set<string>>(
    () => new Set(),
  );

  const boardsQuery = useListBoardsApiV1BoardsGet<
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

  const boards: BoardRead[] =
    boardsQuery.data?.status === 200 ? (boardsQuery.data.data.items ?? []) : [];

  const createMutation = useCreateBoardGroupApiV1BoardGroupsPost<ApiError>({
    mutation: {
      onError: (err) => {
        setError(err.message || "Something went wrong.");
      },
    },
  });

  const isCreating = createMutation.isPending;
  const isFormReady = Boolean(name.trim());

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn) return;
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Group name is required.");
      return;
    }

    setError(null);
    try {
      const created = await createMutation.mutateAsync({
        data: {
          name: trimmedName,
          slug: slugify(trimmedName),
          description: description.trim() || null,
        },
      });
      if (created.status !== 200) {
        throw new Error("Unable to create group.");
      }

      const groupId = created.data.id;
      const boardIds = Array.from(selectedBoardIds);
      if (boardIds.length) {
        const failures: string[] = [];
        for (const boardId of boardIds) {
          try {
            const result = await updateBoardApiV1BoardsBoardIdPatch(boardId, {
              board_group_id: groupId,
            });
            if (result.status !== 200) {
              failures.push(boardId);
            }
          } catch {
            failures.push(boardId);
          }
        }

        if (failures.length) {
          router.push(
            `/board-groups/${groupId}/edit?assign_failed=${failures.length}`,
          );
          return;
        }
      }

      router.push(`/board-groups/${groupId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    }
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to create a board group.",
        forceRedirectUrl: "/board-groups/new",
      }}
      title="Create board group"
      description="Groups help agents discover related work across boards."
    >
      <form
        onSubmit={handleSubmit}
        className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-900">
              Group name <span className="text-red-500">*</span>
            </label>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Release hardening"
              disabled={isCreating}
            />
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Description
          </label>
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What ties these boards together? What should agents coordinate on?"
            className="min-h-[120px]"
            disabled={isCreating}
          />
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="text-sm font-medium text-slate-900">Boards</label>
            <span className="text-xs text-slate-500">
              {selectedBoardIds.size} selected
            </span>
          </div>
          <Input
            value={boardSearch}
            onChange={(event) => setBoardSearch(event.target.value)}
            placeholder="Search boards..."
            disabled={isCreating}
          />
          <div className="max-h-64 overflow-auto rounded-xl border border-slate-200 bg-slate-50/40">
            {boardsQuery.isLoading ? (
              <div className="px-4 py-6 text-sm text-slate-500">
                Loading boards…
              </div>
            ) : boardsQuery.error ? (
              <div className="px-4 py-6 text-sm text-rose-700">
                {boardsQuery.error.message}
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
                    const isAlreadyGrouped = Boolean(board.board_group_id);
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
                            disabled={isCreating}
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
                                  currently grouped
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
          <p className="text-xs text-slate-500">
            Optional. Selected boards will be assigned to this group after
            creation. You can change membership later in group edit or board
            settings.
          </p>
        </div>

        {error ? <p className="text-sm text-red-500">{error}</p> : null}

        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="ghost"
            onClick={() => router.push("/board-groups")}
            disabled={isCreating}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={isCreating || !isFormReady}>
            {isCreating ? "Creating…" : "Create group"}
          </Button>
        </div>

        <div className="border-t border-slate-100 pt-4 text-xs text-slate-500">
          Want to assign boards later? Update each board in{" "}
          <Link
            href="/boards"
            className="font-medium text-blue-600 hover:text-blue-700"
          >
            Boards
          </Link>{" "}
          and pick this group.
        </div>
      </form>
    </DashboardPageLayout>
  );
}
