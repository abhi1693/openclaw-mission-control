"use client";

import { useMemo, useState } from "react";
import {
  BookOpen,
  Clock,
  Code,
  FolderKanban,
  GraduationCap,
  Pencil,
  PenLine,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import {
  useStudyLog,
  type StudyCategory,
  type StudyEntry,
} from "@/hooks/use-study-log";

const CATEGORY_OPTIONS: { value: StudyCategory; label: string }[] = [
  { value: "studying", label: "Studying" },
  { value: "reading", label: "Reading" },
  { value: "writing", label: "Writing" },
  { value: "project-work", label: "Project Work" },
  { value: "coding", label: "Coding" },
];

const CATEGORY_ICON: Record<StudyCategory, typeof Clock> = {
  studying: GraduationCap,
  reading: BookOpen,
  writing: PenLine,
  "project-work": FolderKanban,
  coding: Code,
};

const CATEGORY_BADGE: Record<StudyCategory, string> = {
  studying: "bg-emerald-100 text-emerald-700",
  reading: "bg-blue-100 text-blue-700",
  writing: "bg-teal-100 text-teal-700",
  "project-work": "bg-violet-100 text-violet-700",
  coding: "bg-purple-100 text-purple-700",
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
  date: string;
  hours: string;
  category: StudyCategory;
  topic: string;
  notes: string;
};

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

const emptyForm: FormData = {
  date: todayStr(),
  hours: "",
  category: "studying",
  topic: "",
  notes: "",
};

export default function StudyLogPage() {
  const { isSignedIn } = useAuth();
  useOrganizationMembership(isSignedIn);
  const { entries, loaded, addEntry, updateEntry, removeEntry, weekStats } =
    useStudyLog();

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(emptyForm);

  // Group entries by date
  const groupedEntries = useMemo(() => {
    const sorted = [...entries].sort((a, b) => b.date.localeCompare(a.date));
    const groups: { date: string; entries: StudyEntry[] }[] = [];
    for (const entry of sorted) {
      const last = groups[groups.length - 1];
      if (last && last.date === entry.date) {
        last.entries.push(entry);
      } else {
        groups.push({ date: entry.date, entries: [entry] });
      }
    }
    return groups;
  }, [entries]);

  const openAddForm = () => {
    setEditingId(null);
    setForm({ ...emptyForm, date: todayStr() });
    setShowForm(true);
  };

  const openEditForm = (entry: StudyEntry) => {
    setEditingId(entry.id);
    setForm({
      date: entry.date,
      hours: String(entry.hours),
      category: entry.category,
      topic: entry.topic ?? "",
      notes: entry.notes ?? "",
    });
    setShowForm(true);
  };

  const handleSubmit = () => {
    const hours = Number.parseFloat(form.hours);
    if (!form.date || !Number.isFinite(hours) || hours <= 0) return;
    const data = {
      date: form.date,
      hours,
      category: form.category,
      topic: form.topic.trim() || undefined,
      notes: form.notes.trim() || undefined,
    };
    if (editingId) {
      updateEntry(editingId, data);
    } else {
      addEntry(data);
    }
    setShowForm(false);
    setEditingId(null);
    setForm({ ...emptyForm, date: todayStr() });
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingId(null);
    setForm({ ...emptyForm, date: todayStr() });
  };

  const balanceColor =
    weekStats.balanceLevel === "balanced"
      ? "text-emerald-700"
      : weekStats.balanceLevel === "project-heavy"
        ? "text-amber-700"
        : "text-rose-700";

  const balanceBg =
    weekStats.balanceLevel === "balanced"
      ? "bg-emerald-50 border-emerald-200"
      : weekStats.balanceLevel === "project-heavy"
        ? "bg-amber-50 border-amber-200"
        : "bg-rose-50 border-rose-200";

  const learningPct = Math.round(weekStats.learningPct);
  const projectPct = 100 - learningPct;

  function formatDate(dateStr: string): string {
    const today = todayStr();
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const yesterdayStr = yesterday.toISOString().slice(0, 10);

    if (dateStr === today) return "Today";
    if (dateStr === yesterdayStr) return "Yesterday";
    return new Date(dateStr + "T00:00:00").toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  }

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to access your study log.",
        forceRedirectUrl: "/onboarding",
      }}
      title="Study Log"
      description="Track learning time and maintain balance"
      headerActions={
        <button
          type="button"
          onClick={openAddForm}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Log Time
        </button>
      }
    >
      {!loaded ? (
        <div className="text-sm text-slate-500">Loading...</div>
      ) : (
        <>
          {/* Balance Meter */}
          <div
            className={`rounded-xl border p-4 shadow-sm md:p-6 ${balanceBg}`}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">
                Weekly Balance
              </h3>
              <span className={`text-sm font-semibold ${balanceColor}`}>
                {weekStats.balanceLabel}
              </span>
            </div>
            {weekStats.totalHours > 0 ? (
              <>
                <div className="mb-2 flex h-6 overflow-hidden rounded-full">
                  <div
                    className="flex items-center justify-center bg-emerald-500 text-[11px] font-medium text-white transition-all duration-500"
                    style={{ width: `${Math.max(learningPct, 5)}%` }}
                  >
                    {learningPct > 10 ? `${learningPct}%` : ""}
                  </div>
                  <div
                    className="flex items-center justify-center bg-violet-500 text-[11px] font-medium text-white transition-all duration-500"
                    style={{ width: `${Math.max(projectPct, 5)}%` }}
                  >
                    {projectPct > 10 ? `${projectPct}%` : ""}
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs text-slate-600">
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                    Learning ({weekStats.learningHours.toFixed(1)}h)
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-violet-500" />
                    Projects ({weekStats.projectHours.toFixed(1)}h)
                  </span>
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-500">
                No time logged this week yet. Start logging to see your balance.
              </p>
            )}
          </div>

          {/* Weekly Stats */}
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              label="Total This Week"
              value={`${weekStats.totalHours.toFixed(1)}h`}
            />
            <StatCard
              label="Learning Hours"
              value={`${weekStats.learningHours.toFixed(1)}h`}
            />
            <StatCard
              label="Project Hours"
              value={`${weekStats.projectHours.toFixed(1)}h`}
            />
            <StatCard label="Days Logged" value={weekStats.daysLogged} />
          </div>

          {/* Log Form */}
          {showForm ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm md:p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-lg font-semibold text-slate-900">
                  {editingId ? "Edit Entry" : "Log Time"}
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
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Date <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, date: e.target.value }))
                    }
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Hours <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="number"
                    min="0.25"
                    step="0.25"
                    value={form.hours}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, hours: e.target.value }))
                    }
                    placeholder="e.g. 2.5"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Category <span className="text-rose-500">*</span>
                  </label>
                  <select
                    value={form.category}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        category: e.target.value as StudyCategory,
                      }))
                    }
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    {CATEGORY_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Topic
                  </label>
                  <input
                    type="text"
                    value={form.topic}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, topic: e.target.value }))
                    }
                    placeholder="e.g. Transformer architectures"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
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
                    rows={2}
                    placeholder="What did you learn or work on?"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={
                    !form.date ||
                    !form.hours ||
                    Number.parseFloat(form.hours) <= 0
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
                >
                  {editingId ? "Save Changes" : "Log Entry"}
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

          {/* Entries by Date */}
          <div className="mt-4 space-y-4">
            {groupedEntries.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
                <Clock className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                <p className="text-sm text-slate-500">
                  No entries yet. Click &quot;Log Time&quot; to start tracking.
                </p>
              </div>
            ) : (
              groupedEntries.map((group) => (
                <div key={group.date}>
                  <h4 className="mb-2 text-sm font-semibold text-slate-600">
                    {formatDate(group.date)}
                  </h4>
                  <div className="space-y-2">
                    {group.entries.map((entry) => {
                      const Icon = CATEGORY_ICON[entry.category];
                      return (
                        <div
                          key={entry.id}
                          className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm transition hover:border-slate-300"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <Icon className="h-4 w-4 shrink-0 text-slate-400" />
                                <span className="text-sm font-medium text-slate-900">
                                  {entry.hours}h
                                </span>
                                <span
                                  className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${CATEGORY_BADGE[entry.category]}`}
                                >
                                  {
                                    CATEGORY_OPTIONS.find(
                                      (o) => o.value === entry.category,
                                    )?.label
                                  }
                                </span>
                                {entry.topic ? (
                                  <span className="truncate text-xs text-slate-500">
                                    {entry.topic}
                                  </span>
                                ) : null}
                              </div>
                              {entry.notes ? (
                                <p className="mt-1 text-xs text-slate-500 line-clamp-2 pl-6">
                                  {entry.notes}
                                </p>
                              ) : null}
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                              <button
                                type="button"
                                onClick={() => openEditForm(entry)}
                                className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                                title="Edit"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => removeEntry(entry.id)}
                                className="rounded p-1 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                                title="Delete"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </DashboardPageLayout>
  );
}
