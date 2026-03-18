"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  FileText,
  File,
  FileCode,
  FilePlus,
  FolderOpen,
  Search,
  Clock,
  Tag,
} from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { useListBoardMemoryApiV1BoardsBoardIdMemoryGet } from "@/api/generated/board-memory/board-memory";
import type { BoardMemoryRead } from "@/api/generated/model/boardMemoryRead";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/atoms/Markdown";

type DocEntry = BoardMemoryRead & { boardName: string; boardId: string; category: string };

const CATEGORY_KEYWORDS: Record<string, string[]> = {
  planning: ["plan", "prd", "spec", "design", "architecture", "roadmap", "strategy", "proposal", "requirements"],
  reports: ["report", "summary", "analysis", "review", "retrospective", "status", "update", "metrics"],
  newsletters: ["newsletter", "digest", "weekly", "daily", "briefing", "roundup"],
  code: ["script", "code", "function", "class", "api", "endpoint", "implementation", "snippet", "config"],
};

function categorize(entry: BoardMemoryRead): string {
  const text = (entry.content + " " + (entry.tags ?? []).join(" ")).toLowerCase();
  for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
    if (keywords.some((kw) => text.includes(kw))) return cat;
  }
  return "other";
}

const CATEGORY_META: Record<string, { label: string; icon: typeof FileText; color: string }> = {
  all: { label: "All", icon: FolderOpen, color: "text-slate-600" },
  planning: { label: "Planning", icon: FileText, color: "text-blue-600" },
  reports: { label: "Reports", icon: File, color: "text-emerald-600" },
  newsletters: { label: "Newsletters", icon: FilePlus, color: "text-violet-600" },
  code: { label: "Code", icon: FileCode, color: "text-amber-600" },
  other: { label: "Other", icon: File, color: "text-slate-500" },
};

export default function DocsPage() {
  const { isSignedIn } = useAuth();
  useOrganizationMembership(isSignedIn);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });
  const boards = boardsQuery.data?.data?.items ?? [];
  const boardIds = boards.slice(0, 8).map((b: any) => b.id as string);
  const boardNameMap = new Map(boards.map((b: any) => [b.id, b.name]));

  // Fetch non-chat memory entries (documents/context)
  const memoryQueries = boardIds.map((boardId) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useListBoardMemoryApiV1BoardsBoardIdMemoryGet(
      boardId,
      { is_chat: false, limit: 100 },
      { query: { enabled: Boolean(isSignedIn) && Boolean(boardId) } },
    ),
  );

  const docs: DocEntry[] = useMemo(() => {
    const entries: DocEntry[] = [];
    memoryQueries.forEach((q, i) => {
      const items = q.data?.data?.items ?? [];
      items.forEach((m: any) => {
        // Only include substantial entries (>50 chars) as "documents"
        if (m.content.length < 50) return;
        entries.push({
          ...m,
          boardName: boardNameMap.get(boardIds[i]) ?? "Board",
          boardId: boardIds[i],
          category: categorize(m),
        });
      });
    });
    return entries.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }, [memoryQueries.map((q) => q.dataUpdatedAt).join(",")]);

  // Filter
  const filtered = useMemo(() => {
    return docs.filter((d) => {
      if (category !== "all" && d.category !== category) return false;
      if (search) {
        const q = search.toLowerCase();
        if (!d.content.toLowerCase().includes(q) && !d.boardName.toLowerCase().includes(q) && !(d.tags ?? []).some((t) => t.toLowerCase().includes(q))) return false;
      }
      return true;
    });
  }, [docs, category, search]);

  // Category counts
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: docs.length };
    docs.forEach((d) => { c[d.category] = (c[d.category] ?? 0) + 1; });
    return c;
  }, [docs]);

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const isLoading = boardsQuery.isLoading || memoryQueries.some((q) => q.isLoading);

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view documents.", forceRedirectUrl: "/docs" }}
      title="Docs"
      description={`${docs.length} documents auto-categorized from agent context across ${boards.length} boards.`}
    >
      {/* Search and category tabs */}
      <div className="mb-6 space-y-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search documents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(CATEGORY_META).map(([key, meta]) => {
            const Icon = meta.icon;
            const count = counts[key] ?? 0;
            return (
              <button
                key={key}
                onClick={() => setCategory(key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition",
                  category === key
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {meta.label}
                {count > 0 ? <span className="ml-0.5 opacity-60">({count})</span> : null}
              </button>
            );
          })}
        </div>
      </div>

      {/* Document list */}
      {isLoading ? (
        <div className="flex justify-center py-16">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : filtered.length > 0 ? (
        <div className="space-y-3">
          {filtered.map((doc) => {
            const meta = CATEGORY_META[doc.category] ?? CATEGORY_META.other;
            const Icon = meta.icon;
            const isExpanded = expanded.has(doc.id);
            const preview = doc.content.slice(0, 200);
            return (
              <div key={doc.id} className="rounded-xl border border-slate-200 bg-white shadow-sm transition hover:shadow-md">
                <button
                  onClick={() => toggleExpand(doc.id)}
                  className="w-full text-left px-5 py-4"
                >
                  <div className="flex items-start gap-3">
                    <div className={cn("mt-0.5 shrink-0", meta.color)}>
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-500">
                          {meta.label}
                        </span>
                        <span className="text-[11px] text-slate-400">
                          {doc.boardName}
                        </span>
                        <span className="flex items-center gap-1 text-[11px] text-slate-400">
                          <Clock className="h-3 w-3" />
                          {new Date(doc.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-slate-700 line-clamp-2">
                        {isExpanded ? "" : preview}{!isExpanded && doc.content.length > 200 ? "…" : ""}
                      </p>
                      {doc.tags?.length ? (
                        <div className="mt-2 flex gap-1 flex-wrap">
                          {doc.tags.map((tag) => (
                            <span key={tag} className="inline-flex items-center gap-1 rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
                              <Tag className="h-2.5 w-2.5" /> {tag}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </button>
                {isExpanded ? (
                  <div className="border-t border-slate-100 px-5 py-4">
                    <div className="prose prose-sm max-w-none text-slate-700">
                      <Markdown>{doc.content}</Markdown>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-16">
          <FileText className="h-10 w-10 text-slate-300" />
          <p className="mt-3 text-sm font-medium text-slate-500">
            {search || category !== "all" ? "No matching documents" : "No documents yet"}
          </p>
          <p className="mt-1 max-w-sm text-center text-xs text-slate-400">
            Context entries from your agent boards are auto-categorized as documents here.
            PRDs, scripts, reports, and newsletters will appear as agents create them.
          </p>
        </div>
      )}
    </DashboardPageLayout>
  );
}
