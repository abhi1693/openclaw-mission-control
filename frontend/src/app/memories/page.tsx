"use client";

import { useMemo, useState } from "react";
import { Brain, Bot, MessageSquare, Search, User } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { useListBoardMemoryApiV1BoardsBoardIdMemoryGet } from "@/api/generated/board-memory/board-memory";
import type { BoardMemoryRead } from "@/api/generated/model/boardMemoryRead";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/atoms/Markdown";

type MemoryEntry = BoardMemoryRead & { boardName: string; boardId: string };

function formatDateGroup(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);

  if (date.toDateString() === now.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

function dateKey(dateStr: string): string {
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function MemoriesPage() {
  const { isSignedIn } = useAuth();
  useOrganizationMembership(isSignedIn);
  const [search, setSearch] = useState("");
  const [filterBoard, setFilterBoard] = useState<string>("all");
  const [filterType, setFilterType] = useState<"all" | "chat" | "memory">("all");

  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });
  const boards = boardsQuery.data?.data?.items ?? [];
  const boardIds = boards.slice(0, 8).map((b: any) => b.id as string);
  const boardNameMap = new Map(boards.map((b: any) => [b.id, b.name]));

  // Fetch memories from each board
  const memoryQueries = boardIds.map((boardId) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useListBoardMemoryApiV1BoardsBoardIdMemoryGet(
      boardId,
      { limit: 100 },
      { query: { enabled: Boolean(isSignedIn) && Boolean(boardId) } },
    ),
  );

  const allMemories: MemoryEntry[] = useMemo(() => {
    const entries: MemoryEntry[] = [];
    memoryQueries.forEach((q, i) => {
      const items = q.data?.data?.items ?? [];
      items.forEach((m: any) => {
        entries.push({
          ...m,
          boardName: boardNameMap.get(boardIds[i]) ?? "Board",
          boardId: boardIds[i],
        });
      });
    });
    return entries.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }, [memoryQueries.map((q) => q.dataUpdatedAt).join(",")]);

  // Apply filters
  const filtered = useMemo(() => {
    return allMemories.filter((m) => {
      if (filterBoard !== "all" && m.boardId !== filterBoard) return false;
      if (filterType === "chat" && !m.is_chat) return false;
      if (filterType === "memory" && m.is_chat) return false;
      if (search) {
        const q = search.toLowerCase();
        if (!m.content.toLowerCase().includes(q) && !(m.source ?? "").toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [allMemories, filterBoard, filterType, search]);

  // Group by day
  const grouped = useMemo(() => {
    const groups: { date: string; label: string; items: MemoryEntry[] }[] = [];
    const map = new Map<string, MemoryEntry[]>();
    filtered.forEach((m) => {
      const key = dateKey(m.created_at);
      const arr = map.get(key) ?? [];
      arr.push(m);
      map.set(key, arr);
    });
    // Sort date keys descending
    const keys = [...map.keys()].sort().reverse();
    keys.forEach((key) => {
      const items = map.get(key)!;
      groups.push({ date: key, label: formatDateGroup(items[0].created_at), items });
    });
    return groups;
  }, [filtered]);

  const isLoading = boardsQuery.isLoading || memoryQueries.some((q) => q.isLoading);

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view memories.", forceRedirectUrl: "/memories" }}
      title="Memories"
      description={`${allMemories.length} entries across ${boards.length} boards — a searchable journal of agent context and conversations.`}
    >
      {/* Filters */}
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
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 focus:border-blue-300 focus:outline-none"
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
                filterType === type ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-700",
              )}
            >
              {type === "all" ? "All" : type === "chat" ? "Chat" : "Context"}
            </button>
          ))}
        </div>
      </div>

      {/* Timeline */}
      {isLoading ? (
        <div className="flex justify-center py-16">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : grouped.length > 0 ? (
        <div className="space-y-8">
          {grouped.map((group) => (
            <div key={group.date}>
              <div className="flex items-center gap-2 mb-3">
                <div className="h-px flex-1 bg-slate-200" />
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{group.label}</span>
                <span className="text-[10px] text-slate-300">{group.items.length} entries</span>
                <div className="h-px flex-1 bg-slate-200" />
              </div>
              <div className="space-y-2">
                {group.items.map((m) => (
                  <div key={m.id} className={cn(
                    "rounded-lg border bg-white p-4 transition hover:shadow-sm",
                    m.is_chat ? "border-blue-100" : "border-slate-200",
                  )}>
                    <div className="flex items-center gap-2 mb-2">
                      {m.is_chat ? (
                        <MessageSquare className="h-3.5 w-3.5 text-blue-500" />
                      ) : (
                        <Brain className="h-3.5 w-3.5 text-violet-500" />
                      )}
                      <span className="text-xs font-medium text-slate-600">
                        {m.source ?? "System"}
                      </span>
                      <span className="text-[10px] text-slate-400">
                        {new Date(m.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                        {m.boardName}
                      </span>
                      {m.tags?.length ? (
                        <div className="flex gap-1">
                          {m.tags.map((tag) => (
                            <span key={tag} className="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
                              {tag}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="text-sm text-slate-700 leading-relaxed prose prose-sm max-w-none">
                      <Markdown>{m.content}</Markdown>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-16">
          <Brain className="h-10 w-10 text-slate-300" />
          <p className="mt-3 text-sm font-medium text-slate-500">
            {search || filterBoard !== "all" || filterType !== "all" ? "No matching memories" : "No memories yet"}
          </p>
          <p className="mt-1 max-w-sm text-center text-xs text-slate-400">
            Memories are created as agents work — board chat and context entries will appear here organized by day.
          </p>
        </div>
      )}
    </DashboardPageLayout>
  );
}
