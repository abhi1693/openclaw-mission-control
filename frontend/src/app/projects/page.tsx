"use client";

import { useState } from "react";
import Link from "next/link";
import { Folder, Plus, LayoutGrid, Search } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListBoardGroupsApiV1BoardGroupsGet } from "@/api/generated/board-groups/board-groups";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const STATUS_COLORS: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  planning: "bg-blue-100 text-blue-700",
  paused: "bg-amber-100 text-amber-700",
  completed: "bg-slate-100 text-slate-600",
};

export default function ProjectsPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [search, setSearch] = useState("");

  const groupsQuery = useListBoardGroupsApiV1BoardGroupsGet({
    query: { enabled: Boolean(isSignedIn) },
  });

  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });

  const groups = groupsQuery.data?.data?.items ?? [];
  const boards = boardsQuery.data?.data?.items ?? [];

  // Board groups serve as projects
  const filteredGroups = groups.filter((g: any) =>
    !search || g.name?.toLowerCase().includes(search.toLowerCase()),
  );

  // Boards not in any group
  const ungroupedBoards = boards.filter(
    (b: any) => !b.board_group_id && (!search || b.name?.toLowerCase().includes(search.toLowerCase())),
  );

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view projects.", forceRedirectUrl: "/projects" }}
      title="Projects"
      description="Track major initiatives. Each board group is a project with linked boards, tasks, and memories."
      headerActions={
        <Link href="/board-groups/new">
          <Button size="sm">
            <Plus className="mr-1.5 h-3.5 w-3.5" /> New Project
          </Button>
        </Link>
      }
    >
      {/* Search */}
      <div className="mb-6">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search projects..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
      </div>

      {/* Projects grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filteredGroups.map((group: any) => {
          const groupBoards = boards.filter((b: any) => b.board_group_id === group.id);
          return (
            <Link
              key={group.id}
              href={`/board-groups/${group.id}`}
              className="group rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-200 hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50">
                    <Folder className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-slate-900 group-hover:text-blue-700 transition">
                      {group.name}
                    </h3>
                    <p className="text-xs text-slate-500">
                      {groupBoards.length} board{groupBoards.length !== 1 ? "s" : ""}
                    </p>
                  </div>
                </div>
                <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase", STATUS_COLORS.active)}>
                  Active
                </span>
              </div>
              {group.description ? (
                <p className="mt-3 text-xs text-slate-500 line-clamp-2">{group.description}</p>
              ) : null}
            </Link>
          );
        })}

        {/* Ungrouped boards as standalone projects */}
        {ungroupedBoards.map((board: any) => (
          <Link
            key={board.id}
            href={`/boards/${board.id}`}
            className="group rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-200 hover:shadow-md"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-50">
                  <LayoutGrid className="h-5 w-5 text-violet-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900 group-hover:text-blue-700 transition">
                    {board.name}
                  </h3>
                  <p className="text-xs text-slate-500">Standalone board</p>
                </div>
              </div>
            </div>
            {board.description ? (
              <p className="mt-3 text-xs text-slate-500 line-clamp-2">{board.description}</p>
            ) : null}
          </Link>
        ))}
      </div>

      {filteredGroups.length === 0 && ungroupedBoards.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-16">
          <Folder className="h-10 w-10 text-slate-300" />
          <p className="mt-3 text-sm font-medium text-slate-500">No projects yet</p>
          <p className="mt-1 text-xs text-slate-400">
            Create a board group to start tracking a project.
          </p>
          <Link href="/board-groups/new" className="mt-4">
            <Button size="sm" variant="secondary">
              <Plus className="mr-1.5 h-3.5 w-3.5" /> Create project
            </Button>
          </Link>
        </div>
      ) : null}
    </DashboardPageLayout>
  );
}
