"use client";

import { useMemo, useState } from "react";
import {
  BookOpen,
  ExternalLink,
  FileText,
  GraduationCap,
  Newspaper,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import {
  useReadingList,
  type ReadingItem,
  type ReadingItemType,
  type ReadingItemStatus,
} from "@/hooks/use-reading-list";

const TYPE_OPTIONS: { value: ReadingItemType; label: string }[] = [
  { value: "paper", label: "Paper" },
  { value: "book", label: "Book" },
  { value: "article", label: "Article" },
  { value: "course", label: "Course" },
];

const STATUS_OPTIONS: { value: ReadingItemStatus; label: string }[] = [
  { value: "to-read", label: "To Read" },
  { value: "reading", label: "Reading" },
  { value: "completed", label: "Completed" },
];

const TYPE_ICON: Record<ReadingItemType, typeof BookOpen> = {
  paper: FileText,
  book: BookOpen,
  article: Newspaper,
  course: GraduationCap,
};

const TYPE_BADGE_STYLE: Record<ReadingItemType, string> = {
  paper: "bg-blue-100 text-blue-700",
  book: "bg-violet-100 text-violet-700",
  article: "bg-amber-100 text-amber-700",
  course: "bg-emerald-100 text-emerald-700",
};

const STATUS_BADGE_STYLE: Record<ReadingItemStatus, string> = {
  "to-read": "bg-slate-100 text-slate-600",
  reading: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
};

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 font-heading text-2xl font-bold text-slate-900">
        {value}
      </p>
    </div>
  );
}

type FormData = {
  title: string;
  url: string;
  type: ReadingItemType;
  status: ReadingItemStatus;
  notes: string;
};

const emptyForm: FormData = {
  title: "",
  url: "",
  type: "paper",
  status: "to-read",
  notes: "",
};

export default function ReadingListPage() {
  const { isSignedIn } = useAuth();
  useOrganizationMembership(isSignedIn);
  const { items, loaded, addItem, updateItem, removeItem } = useReadingList();

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(emptyForm);

  const [filterType, setFilterType] = useState<ReadingItemType | "all">("all");
  const [filterStatus, setFilterStatus] = useState<ReadingItemStatus | "all">("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (filterType !== "all" && item.type !== filterType) return false;
      if (filterStatus !== "all" && item.status !== filterStatus) return false;
      if (search) {
        const q = search.toLowerCase();
        if (
          !item.title.toLowerCase().includes(q) &&
          !(item.notes ?? "").toLowerCase().includes(q)
        )
          return false;
      }
      return true;
    });
  }, [items, filterType, filterStatus, search]);

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
  const completedThisMonth = items.filter(
    (i) => i.status === "completed" && i.completedAt && i.completedAt >= monthStart,
  ).length;
  const currentlyReading = items.filter((i) => i.status === "reading").length;

  const openAddForm = () => {
    setEditingId(null);
    setForm(emptyForm);
    setShowForm(true);
  };

  const openEditForm = (item: ReadingItem) => {
    setEditingId(item.id);
    setForm({
      title: item.title,
      url: item.url ?? "",
      type: item.type,
      status: item.status,
      notes: item.notes ?? "",
    });
    setShowForm(true);
  };

  const handleSubmit = () => {
    if (!form.title.trim()) return;
    const data = {
      title: form.title.trim(),
      url: form.url.trim() || undefined,
      type: form.type,
      status: form.status,
      notes: form.notes.trim() || undefined,
    };
    if (editingId) {
      updateItem(editingId, data);
    } else {
      addItem(data);
    }
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to access your reading list.",
        forceRedirectUrl: "/onboarding",
      }}
      title="Reading List"
      description="Track papers, books, and articles for your research"
      headerActions={
        <button
          type="button"
          onClick={openAddForm}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Add Item
        </button>
      }
    >
      {!loaded ? (
        <div className="text-sm text-slate-500">Loading...</div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Total Items" value={items.length} />
            <StatCard label="Currently Reading" value={currentlyReading} />
            <StatCard label="Completed This Month" value={completedThisMonth} />
          </div>

          {/* Form */}
          {showForm ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm md:p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-lg font-semibold text-slate-900">
                  {editingId ? "Edit Item" : "Add New Item"}
                </h3>
                <button
                  type="button"
                  onClick={handleCancel}
                  className="text-slate-400 hover:text-slate-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Title <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.title}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, title: e.target.value }))
                    }
                    placeholder="e.g. Attention Is All You Need"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    URL
                  </label>
                  <input
                    type="url"
                    value={form.url}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, url: e.target.value }))
                    }
                    placeholder="https://arxiv.org/abs/..."
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Type
                  </label>
                  <select
                    value={form.type}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        type: e.target.value as ReadingItemType,
                      }))
                    }
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    {TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Status
                  </label>
                  <select
                    value={form.status}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        status: e.target.value as ReadingItemStatus,
                      }))
                    }
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    {STATUS_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Notes
                  </label>
                  <textarea
                    value={form.notes}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, notes: e.target.value }))
                    }
                    rows={3}
                    placeholder="Key takeaways, chapter notes, etc."
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={!form.title.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
                >
                  {editingId ? "Save Changes" : "Add Item"}
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          {/* Filters */}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search..."
                className="rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <select
              value={filterType}
              onChange={(e) =>
                setFilterType(e.target.value as ReadingItemType | "all")
              }
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="all">All types</option>
              {TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              value={filterStatus}
              onChange={(e) =>
                setFilterStatus(e.target.value as ReadingItemStatus | "all")
              }
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="all">All statuses</option>
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Items */}
          <div className="mt-4 space-y-2">
            {filtered.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
                <BookOpen className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                <p className="text-sm text-slate-500">
                  {items.length === 0
                    ? 'No items yet. Click "Add Item" to get started.'
                    : "No items match your filters."}
                </p>
              </div>
            ) : (
              filtered.map((item) => {
                const Icon = TYPE_ICON[item.type];
                return (
                  <div
                    key={item.id}
                    className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm transition hover:border-slate-300"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <Icon className="h-4 w-4 shrink-0 text-slate-400" />
                          <h4 className="truncate text-sm font-medium text-slate-900">
                            {item.url ? (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 hover:text-blue-600"
                              >
                                {item.title}
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            ) : (
                              item.title
                            )}
                          </h4>
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2">
                          <span
                            className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${TYPE_BADGE_STYLE[item.type]}`}
                          >
                            {item.type}
                          </span>
                          <select
                            value={item.status}
                            onChange={(e) =>
                              updateItem(item.id, {
                                status: e.target.value as ReadingItemStatus,
                              })
                            }
                            className={`inline-flex cursor-pointer rounded-full border-0 px-2 py-0.5 text-[11px] font-medium ${STATUS_BADGE_STYLE[item.status]} focus:outline-none focus:ring-1 focus:ring-blue-500`}
                          >
                            {STATUS_OPTIONS.map((opt) => (
                              <option key={opt.value} value={opt.value}>
                                {opt.label}
                              </option>
                            ))}
                          </select>
                          <span className="text-[11px] text-slate-400">
                            Added{" "}
                            {new Date(item.addedAt).toLocaleDateString()}
                          </span>
                          {item.completedAt ? (
                            <span className="text-[11px] text-emerald-600">
                              Completed{" "}
                              {new Date(
                                item.completedAt,
                              ).toLocaleDateString()}
                            </span>
                          ) : null}
                        </div>
                        {item.notes ? (
                          <p className="mt-1.5 text-xs text-slate-500 line-clamp-2">
                            {item.notes}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => openEditForm(item)}
                          className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                          title="Edit"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => removeItem(item.id)}
                          className="rounded p-1 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                          title="Delete"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </>
      )}
    </DashboardPageLayout>
  );
}
