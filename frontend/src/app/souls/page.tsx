"use client";

export const dynamic = "force-dynamic";

import { useState, useMemo } from "react";
import { Search } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import {
  type searchApiV1SoulsDirectorySearchGetResponse,
  useSearchApiV1SoulsDirectorySearchGet,
} from "@/api/generated/souls-directory/souls-directory";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { SoulPreviewCard } from "@/components/souls/SoulPreviewCard";
import { Input } from "@/components/ui/input";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { useDebounce } from "@/lib/use-debounce";

export default function SoulsDirectoryPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedQuery = useDebounce(searchQuery, 300);

  const searchResultsQuery = useSearchApiV1SoulsDirectorySearchGet<
    searchApiV1SoulsDirectorySearchGetResponse,
    ApiError
  >(
    debouncedQuery ? { q: debouncedQuery } : undefined,
    {
      query: {
        enabled: Boolean(isSignedIn && debouncedQuery),
        refetchOnMount: "always",
      },
    },
  );

  const souls = useMemo(() => {
    if (searchResultsQuery.data?.status === 200) {
      return searchResultsQuery.data.data.items ?? [];
    }
    return [];
  }, [searchResultsQuery.data]);

  const isLoading = searchResultsQuery.isFetching;

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to browse the souls directory.",
        forceRedirectUrl: "/souls",
      }}
      title="Souls directory"
      description="Browse and search soul templates from the community."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can access the souls directory."
    >
      <div className="space-y-6">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search souls by handle or slug..."
            className="pl-10"
          />
        </div>

        {isLoading ? (
          <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500 shadow-sm">
            Searching...
          </div>
        ) : searchResultsQuery.error ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
            {searchResultsQuery.error.message}
          </div>
        ) : !debouncedQuery ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center">
            <p className="text-sm text-slate-600">
              Enter a search query to find souls in the directory.
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Search by handle (e.g., &quot;anthropic&quot;) or slug (e.g., &quot;assistant&quot;).
            </p>
          </div>
        ) : souls.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center">
            <p className="text-sm text-slate-600">
              No souls found matching &quot;{debouncedQuery}&quot;.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {souls.map((soul) => (
              <SoulPreviewCard key={`${soul.handle}/${soul.slug}`} soul={soul} />
            ))}
          </div>
        )}
      </div>
    </DashboardPageLayout>
  );
}
