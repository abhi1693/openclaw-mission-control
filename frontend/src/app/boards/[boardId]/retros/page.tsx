"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import {
  ArrowLeft,
  Plus,
  X,
  BarChart2,
  ListFilter,
} from "lucide-react";

import { SignedIn, SignedOut, useAuth, SignInButton } from "@/auth/clerk";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { customFetch } from "@/api/mutator";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type RetroItem = {
  id: string;
  board_id: string;
  sprint_id: number | null;
  category: string;
  content: string;
  author: string | null;
  date: string | null;
  status: string | null;
  priority: string | null;
  is_action_item: boolean;
  recurrence: boolean;
  created_at: string;
  updated_at: string;
};

type RetroStat = {
  sprint_id: number;
  category: string;
  count: number;
};

type RetroListResponse = {
  items: RetroItem[];
  total: number;
  limit: number;
  offset: number;
};

// ─── Category Config ──────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<
  string,
  { label: string; dotClass: string; headerClass: string; badgeClass: string; borderClass: string }
> = {
  achieved: {
    label: "Achieved ✅",
    dotClass: "bg-emerald-500",
    headerClass: "border-emerald-200 bg-emerald-50/60",
    badgeClass: "bg-emerald-100 text-emerald-700",
    borderClass: "border-emerald-200",
  },
  challenged: {
    label: "Challenged ⚠️",
    dotClass: "bg-rose-500",
    headerClass: "border-rose-200 bg-rose-50/60",
    badgeClass: "bg-rose-100 text-rose-700",
    borderClass: "border-rose-200",
  },
  transferred: {
    label: "Transferred 🔄",
    dotClass: "bg-blue-500",
    headerClass: "border-blue-200 bg-blue-50/60",
    badgeClass: "bg-blue-100 text-blue-700",
    borderClass: "border-blue-200",
  },
  action: {
    label: "Action Item 🎯",
    dotClass: "bg-amber-500",
    headerClass: "border-amber-200 bg-amber-50/60",
    badgeClass: "bg-amber-100 text-amber-700",
    borderClass: "border-amber-200",
  },
  quality: {
    label: "Quality 🔍",
    dotClass: "bg-indigo-500",
    headerClass: "border-indigo-200 bg-indigo-50/60",
    badgeClass: "bg-indigo-100 text-indigo-700",
    borderClass: "border-indigo-200",
  },
  process: {
    label: "Process 📋",
    dotClass: "bg-purple-500",
    headerClass: "border-purple-200 bg-purple-50/60",
    badgeClass: "bg-purple-100 text-purple-700",
    borderClass: "border-purple-200",
  },
  decision: {
    label: "Decision 🏁",
    dotClass: "bg-teal-500",
    headerClass: "border-teal-200 bg-teal-50/60",
    badgeClass: "bg-teal-100 text-teal-700",
    borderClass: "border-teal-200",
  },
  improve: {
    label: "Improve 📈",
    dotClass: "bg-orange-500",
    headerClass: "border-orange-200 bg-orange-50/60",
    badgeClass: "bg-orange-100 text-orange-700",
    borderClass: "border-orange-200",
  },
};

const DEFAULT_CATEGORY_CONFIG = {
  label: "",
  dotClass: "bg-slate-400",
  headerClass: "border-slate-200 bg-slate-50/60",
  badgeClass: "bg-slate-100 text-slate-600",
  borderClass: "border-slate-200",
};

const getCategoryConfig = (category: string) => {
  const normalized = category.toLowerCase().trim();
  return CATEGORY_CONFIG[normalized] ?? {
    ...DEFAULT_CATEGORY_CONFIG,
    label: category.charAt(0).toUpperCase() + category.slice(1),
  };
};

const PRIORITY_OPTIONS = [
  { value: "", label: "No priority" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

const CATEGORY_OPTIONS = [
  "achieved",
  "challenged",
  "transferred",
  "action",
  "quality",
  "process",
  "decision",
  "improve",
];

const PRIORITY_BADGE: Record<string, string> = {
  high: "bg-rose-100 text-rose-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-emerald-100 text-emerald-700",
};

// ─── RetroCard Component ──────────────────────────────────────────────────────

function RetroCard({ item }: { item: RetroItem }) {
  const cfg = getCategoryConfig(item.category);
  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-3 shadow-sm transition hover:shadow-md",
        cfg.borderClass,
      )}
    >
      <p className="text-sm leading-relaxed text-slate-800 break-words whitespace-pre-wrap">
        {item.content}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
        {item.author ? (
          <span className="font-medium text-slate-500">{item.author}</span>
        ) : null}
        {item.priority ? (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 font-semibold uppercase tracking-wide",
              PRIORITY_BADGE[item.priority] ?? "bg-slate-100 text-slate-600",
            )}
          >
            {item.priority}
          </span>
        ) : null}
        {item.status && item.status !== "open" ? (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-500">
            {item.status}
          </span>
        ) : null}
        {item.is_action_item ? (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 font-semibold text-amber-700 border border-amber-200">
            Action
          </span>
        ) : null}
      </div>
    </div>
  );
}

// ─── StatsTable Component ─────────────────────────────────────────────────────

function StatsTable({ stats }: { stats: RetroStat[] }) {
  const sprints = useMemo(
    () => [...new Set(stats.map((s) => s.sprint_id))].sort((a, b) => a - b),
    [stats],
  );
  const categories = useMemo(
    () => [...new Set(stats.map((s) => s.category))].sort(),
    [stats],
  );

  const bySprintCat = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of stats) {
      map.set(`${s.sprint_id}:${s.category}`, s.count);
    }
    return map;
  }, [stats]);

  const sprintTotals = useMemo(() => {
    const map = new Map<number, number>();
    for (const s of stats) {
      map.set(s.sprint_id, (map.get(s.sprint_id) ?? 0) + s.count);
    }
    return map;
  }, [stats]);

  const maxCount = useMemo(
    () => Math.max(1, ...stats.map((s) => s.count)),
    [stats],
  );

  if (stats.length === 0) {
    return (
      <p className="text-sm text-slate-500">No stats available.</p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-50">
          <tr>
            <th className="sticky left-0 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-600">
              Sprint
            </th>
            {categories.map((cat) => {
              const cfg = getCategoryConfig(cat);
              return (
                <th
                  key={cat}
                  className="px-3 py-2 text-center font-semibold text-slate-600 whitespace-nowrap"
                >
                  <span className={cn("inline-flex items-center gap-1")}>
                    <span className={cn("h-2 w-2 rounded-full", cfg.dotClass)} />
                    {cat}
                  </span>
                </th>
              );
            })}
            <th className="px-3 py-2 text-center font-semibold text-slate-700">
              Total
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {sprints.map((sprintId) => (
            <tr key={sprintId} className="hover:bg-slate-50">
              <td className="sticky left-0 bg-white px-3 py-2 font-semibold text-slate-700 hover:bg-slate-50">
                S{sprintId}
              </td>
              {categories.map((cat) => {
                const count = bySprintCat.get(`${sprintId}:${cat}`) ?? 0;
                const pct = count > 0 ? Math.round((count / maxCount) * 100) : 0;
                const cfg = getCategoryConfig(cat);
                return (
                  <td key={cat} className="px-3 py-2 text-center">
                    {count > 0 ? (
                      <div className="flex flex-col items-center gap-1">
                        <span className="font-semibold text-slate-800">{count}</span>
                        <div className="h-1.5 w-10 rounded-full bg-slate-100 overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", cfg.dotClass)}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                );
              })}
              <td className="px-3 py-2 text-center font-bold text-slate-700">
                {sprintTotals.get(sprintId) ?? 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function RetroDashboardPage() {
  const router = useRouter();
  const params = useParams();
  const boardIdParam = params?.boardId;
  const boardId = Array.isArray(boardIdParam) ? boardIdParam[0] : boardIdParam;
  const { isSignedIn } = useAuth();

  const [selectedSprint, setSelectedSprint] = useState<string>("all");
  const [items, setItems] = useState<RetroItem[]>([]);
  const [stats, setStats] = useState<RetroStat[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"board" | "stats">("board");

  // Create form state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [formCategory, setFormCategory] = useState("achieved");
  const [formContent, setFormContent] = useState("");
  const [formAuthor, setFormAuthor] = useState("");
  const [formPriority, setFormPriority] = useState("");
  const [formSprint, setFormSprint] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Derive available sprints from stats
  const availableSprints = useMemo(() => {
    const from = new Set<number>();
    for (const s of stats) from.add(s.sprint_id);
    return [...from].sort((a, b) => b - a); // descending
  }, [stats]);

  // Load stats once
  const loadStats = useCallback(async () => {
    if (!isSignedIn || !boardId) return;
    setStatsLoading(true);
    try {
      const res = await customFetch<{ data: RetroStat[]; status: number }>(
        `/api/v1/boards/${boardId}/retros/stats`,
        { method: "GET" },
      );
      if (res.status === 200) {
        setStats(Array.isArray(res.data) ? res.data : []);
      }
    } catch {
      // stats are non-critical
    } finally {
      setStatsLoading(false);
    }
  }, [boardId, isSignedIn]);

  // Load retro items (with optional sprint filter)
  const loadItems = useCallback(async () => {
    if (!isSignedIn || !boardId) return;
    setIsLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ limit: "200", offset: "0" });
      if (selectedSprint !== "all") qs.set("sprint_id", selectedSprint);
      const res = await customFetch<{ data: RetroListResponse; status: number }>(
        `/api/v1/boards/${boardId}/retros?${qs.toString()}`,
        { method: "GET" },
      );
      if (res.status === 200) {
        setItems(res.data.items ?? []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load retros.");
    } finally {
      setIsLoading(false);
    }
  }, [boardId, isSignedIn, selectedSprint]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  // Set default sprint to the latest one when stats load
  useEffect(() => {
    if (availableSprints.length > 0 && selectedSprint === "all") {
      setSelectedSprint(String(availableSprints[0]));
    }
  }, [availableSprints, selectedSprint]);

  // Group items by category
  const grouped = useMemo(() => {
    const map = new Map<string, RetroItem[]>();
    for (const item of items) {
      const cat = item.category ?? "other";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(item);
    }
    return map;
  }, [items]);

  // Order categories: known first, then alphabetical
  const orderedCategories = useMemo(() => {
    const all = [...grouped.keys()];
    const known = CATEGORY_OPTIONS.filter((c) => all.includes(c));
    const others = all.filter((c) => !CATEGORY_OPTIONS.includes(c)).sort();
    return [...known, ...others];
  }, [grouped]);

  const handleCreate = async () => {
    if (!boardId || !isSignedIn) return;
    if (!formContent.trim()) {
      setCreateError("Content is required.");
      return;
    }
    setIsCreating(true);
    setCreateError(null);
    try {
      const body: Record<string, unknown> = {
        category: formCategory,
        content: formContent.trim(),
      };
      if (formAuthor.trim()) body.author = formAuthor.trim();
      if (formPriority) body.priority = formPriority;
      if (formSprint) body.sprint_id = parseInt(formSprint, 10);

      const res = await customFetch<{ data: RetroItem; status: number }>(
        `/api/v1/boards/${boardId}/retros`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      if (res.status === 200 || res.status === 201) {
        const created = res.data;
        setItems((prev) => [created, ...prev]);
        // Also reload stats
        void loadStats();
        setIsCreateOpen(false);
        setFormContent("");
        setFormAuthor("");
        setFormPriority("");
        setFormSprint(selectedSprint !== "all" ? selectedSprint : "");
      }
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create.");
    } finally {
      setIsCreating(false);
    }
  };

  const openCreate = () => {
    setFormCategory("achieved");
    setFormContent("");
    setFormAuthor("");
    setFormPriority("");
    setFormSprint(selectedSprint !== "all" ? selectedSprint : "");
    setCreateError(null);
    setIsCreateOpen(true);
  };

  return (
    <DashboardShell>
      <SignedOut>
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl p-10 text-center">
          <p className="text-sm text-slate-500">Sign in to view retros.</p>
          <SignInButton mode="modal" forceRedirectUrl="/boards">
            <Button>Sign in</Button>
          </SignInButton>
        </div>
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-gradient-to-br from-slate-50 to-slate-100">
          {/* Header */}
          <div className="sticky top-0 z-30 border-b border-slate-200 bg-white shadow-sm">
            <div className="px-4 py-4 md:px-8 md:py-5">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => router.push(`/boards/${boardId ?? ""}`)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Board
                  </button>
                  <div>
                    <h1 className="text-xl font-semibold text-slate-900 tracking-tight">
                      Sprint Retrospective
                    </h1>
                    <p className="mt-0.5 text-sm text-slate-500">
                      Review what went well, what was challenging, and what to carry forward.
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  {/* Sprint selector */}
                  <div className="flex items-center gap-2">
                    <ListFilter className="h-4 w-4 text-slate-400" />
                    <Select
                      value={selectedSprint}
                      onValueChange={setSelectedSprint}
                    >
                      <SelectTrigger className="h-9 w-36 text-sm">
                        <SelectValue placeholder="Sprint…" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All sprints</SelectItem>
                        {availableSprints.map((s) => (
                          <SelectItem key={s} value={String(s)}>
                            Sprint {s}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Tab toggles */}
                  <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1">
                    <button
                      className={cn(
                        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                        activeTab === "board"
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-slate-200 hover:text-slate-900",
                      )}
                      onClick={() => setActiveTab("board")}
                    >
                      Board
                    </button>
                    <button
                      className={cn(
                        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                        activeTab === "stats"
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-slate-200 hover:text-slate-900",
                      )}
                      onClick={() => setActiveTab("stats")}
                    >
                      <span className="flex items-center gap-1.5">
                        <BarChart2 className="h-3.5 w-3.5" />
                        Stats
                      </span>
                    </button>
                  </div>

                  <Button
                    onClick={openCreate}
                    className="h-9 gap-1.5"
                  >
                    <Plus className="h-4 w-4" />
                    Add Retro
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="p-4 md:p-6">
            {error ? (
              <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}

            {activeTab === "stats" ? (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-semibold text-slate-900">
                        Category breakdown by sprint
                      </h2>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {stats.length} data points across{" "}
                        {availableSprints.length} sprints
                      </p>
                    </div>
                  </div>
                  {statsLoading ? (
                    <p className="text-sm text-slate-500">Loading stats…</p>
                  ) : (
                    <StatsTable stats={stats} />
                  )}
                </div>
              </div>
            ) : (
              <>
                {isLoading ? (
                  <div className="flex min-h-[50vh] items-center justify-center text-sm text-slate-500">
                    Loading retro items…
                  </div>
                ) : items.length === 0 ? (
                  <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-slate-300 bg-white text-center">
                    <p className="text-sm text-slate-500">
                      No retro items for this selection.
                    </p>
                    <Button variant="outline" onClick={openCreate}>
                      Add the first one
                    </Button>
                  </div>
                ) : (
                  <div
                    className={cn(
                      "grid grid-cols-1 gap-4",
                      orderedCategories.length >= 3
                        ? "md:grid-cols-2 xl:grid-cols-3"
                        : orderedCategories.length === 2
                          ? "md:grid-cols-2"
                          : "",
                    )}
                  >
                    {orderedCategories.map((cat) => {
                      const catItems = grouped.get(cat) ?? [];
                      const cfg = getCategoryConfig(cat);
                      return (
                        <div key={cat} className="flex flex-col gap-2">
                          {/* Column header */}
                          <div
                            className={cn(
                              "flex items-center justify-between rounded-xl border px-4 py-3",
                              cfg.headerClass,
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <span
                                className={cn(
                                  "h-2.5 w-2.5 rounded-full",
                                  cfg.dotClass,
                                )}
                              />
                              <h3 className="text-sm font-semibold text-slate-800">
                                {cfg.label ||
                                  cat.charAt(0).toUpperCase() + cat.slice(1)}
                              </h3>
                            </div>
                            <span
                              className={cn(
                                "flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-xs font-semibold",
                                cfg.badgeClass,
                              )}
                            >
                              {catItems.length}
                            </span>
                          </div>

                          {/* Cards */}
                          <div className="space-y-2">
                            {catItems.map((item) => (
                              <RetroCard key={item.id} item={item} />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </SignedIn>

      {/* Create Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Retro Item</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {/* Category */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Category
              </label>
              <Select value={formCategory} onValueChange={setFormCategory}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c.charAt(0).toUpperCase() + c.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Content */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Content <span className="text-rose-500">*</span>
              </label>
              <Textarea
                value={formContent}
                onChange={(e) => setFormContent(e.target.value)}
                placeholder="What happened? What should we note?"
                rows={3}
              />
            </div>

            {/* Author */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Author
              </label>
              <Input
                value={formAuthor}
                onChange={(e) => setFormAuthor(e.target.value)}
                placeholder="e.g. dev-1, pm-1…"
              />
            </div>

            {/* Priority */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Priority
              </label>
              <Select value={formPriority} onValueChange={setFormPriority}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="No priority" />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITY_OPTIONS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Sprint */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Sprint
              </label>
              <Select value={formSprint} onValueChange={setFormSprint}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select sprint…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">No sprint</SelectItem>
                  {availableSprints.map((s) => (
                    <SelectItem key={s} value={String(s)}>
                      Sprint {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {createError ? (
              <p className="text-sm text-rose-600">{createError}</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsCreateOpen(false)}
              disabled={isCreating}
            >
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={isCreating}>
              {isCreating ? "Adding…" : "Add item"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardShell>
  );
}
