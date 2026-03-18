"use client";

import { useState } from "react";
import {
  FileText,
  File,
  FileCode,
  FilePlus,
  FolderOpen,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { cn } from "@/lib/utils";

type DocCategory = "all" | "planning" | "reports" | "newsletters" | "code" | "other";

const CATEGORIES: { value: DocCategory; label: string; icon: typeof FileText }[] = [
  { value: "all", label: "All", icon: FolderOpen },
  { value: "planning", label: "Planning", icon: FileText },
  { value: "reports", label: "Reports", icon: File },
  { value: "newsletters", label: "Newsletters", icon: FilePlus },
  { value: "code", label: "Code", icon: FileCode },
  { value: "other", label: "Other", icon: File },
];

export default function DocsPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<DocCategory>("all");

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view documents.", forceRedirectUrl: "/docs" }}
      title="Docs"
      description="Searchable repository of all files, planning docs, and newsletters created by your agents."
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
          {CATEGORIES.map((cat) => {
            const Icon = cat.icon;
            return (
              <button
                key={cat.value}
                onClick={() => setCategory(cat.value)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition",
                  category === cat.value
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {cat.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Documents list */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col items-center justify-center py-20">
          <FileText className="h-10 w-10 text-slate-300" />
          <p className="mt-3 text-sm font-medium text-slate-500">No documents yet</p>
          <p className="mt-1 max-w-sm text-center text-xs text-slate-400">
            Documents created by your agents will automatically appear here, categorized by type.
            Planning docs, newsletters, reports, and code files will all be searchable.
          </p>
        </div>
      </div>

      {/* How docs work */}
      <div className="mt-8 rounded-xl border border-violet-100 bg-violet-50/50 p-5">
        <div className="flex gap-3">
          <SlidersHorizontal className="h-5 w-5 text-violet-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-violet-900">Auto-categorization</p>
            <p className="mt-1 text-xs text-violet-700">
              When your agents create files — planning documents, weekly newsletters, code reviews, or reports —
              they are automatically indexed here. Use the category filters and search to quickly find any document.
            </p>
          </div>
        </div>
      </div>
    </DashboardPageLayout>
  );
}
