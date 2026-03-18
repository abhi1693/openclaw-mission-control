"use client";

import { useState } from "react";
import { Brain, MessageSquare, Search } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { cn } from "@/lib/utils";

export default function MemoriesPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [search, setSearch] = useState("");
  const [filterBoard, setFilterBoard] = useState<string>("all");
  const [filterType, setFilterType] = useState<"all" | "chat" | "memory">("all");

  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });

  const boards = boardsQuery.data?.data?.items ?? [];

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view memories.", forceRedirectUrl: "/memories" }}
      title="Memories"
      description="A searchable journal of conversations and agent context, organized by day."
    >
      {/* Search and filters */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search memories..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <select
          value={filterBoard}
          onChange={(e) => setFilterBoard(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All boards</option>
          {boards.map((b: any) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
          {(["all", "chat", "memory"] as const).map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(type)}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition",
                filterType === type
                  ? "bg-slate-900 text-white"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              {type === "all" ? "All" : type === "chat" ? "Chat" : "Context"}
            </button>
          ))}
        </div>
      </div>

      {/* Memory timeline */}
      <div className="space-y-6">
        {/* Today section */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1 bg-slate-200" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Today
            </span>
            <div className="h-px flex-1 bg-slate-200" />
          </div>

          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-16">
            <Brain className="h-10 w-10 text-slate-300" />
            <p className="mt-3 text-sm font-medium text-slate-500">No memories yet</p>
            <p className="mt-1 max-w-sm text-center text-xs text-slate-400">
              Memories are created automatically as your agents work. Board chat messages and context entries will appear here, organized by day.
            </p>
          </div>
        </div>
      </div>

      {/* Info card */}
      <div className="mt-8 rounded-xl border border-blue-100 bg-blue-50/50 p-5">
        <div className="flex gap-3">
          <MessageSquare className="h-5 w-5 text-blue-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-blue-900">How memories work</p>
            <p className="mt-1 text-xs text-blue-700">
              Every board has a memory stream. Chat messages between you and agents, along with persistent context entries,
              are stored here. Use the search and filters above to find past conversations and decisions.
              Memories are grouped by day, creating a journal of your AI collaboration.
            </p>
          </div>
        </div>
      </div>
    </DashboardPageLayout>
  );
}
