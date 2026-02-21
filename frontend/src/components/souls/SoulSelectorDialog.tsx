"use client";

import { useState, useMemo } from "react";
import { Search } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import {
  type searchApiV1SoulsDirectorySearchGetResponse,
  useSearchApiV1SoulsDirectorySearchGet,
  type getMarkdownApiV1SoulsDirectoryHandleSlugGetResponse,
  useGetMarkdownApiV1SoulsDirectoryHandleSlugGet,
} from "@/api/generated/souls-directory/souls-directory";
import type { SoulsDirectorySoulRef } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SoulPreviewCard } from "./SoulPreviewCard";
import { useDebounce } from "@/lib/use-debounce";

interface SoulSelectorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (content: string) => void;
}

export function SoulSelectorDialog({
  open,
  onOpenChange,
  onSelect,
}: SoulSelectorDialogProps) {
  const { isSignedIn } = useAuth();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSoul, setSelectedSoul] = useState<SoulsDirectorySoulRef | null>(
    null,
  );
  const debouncedQuery = useDebounce(searchQuery, 300);

  const searchResultsQuery = useSearchApiV1SoulsDirectorySearchGet<
    searchApiV1SoulsDirectorySearchGetResponse,
    ApiError
  >(
    debouncedQuery ? { q: debouncedQuery } : undefined,
    {
      query: {
        enabled: Boolean(isSignedIn && open && debouncedQuery),
        refetchOnMount: "always",
      },
    },
  );

  const markdownQuery = useGetMarkdownApiV1SoulsDirectoryHandleSlugGet<
    getMarkdownApiV1SoulsDirectoryHandleSlugGetResponse,
    ApiError
  >(selectedSoul?.handle ?? "", selectedSoul?.slug ?? "", {
    query: {
      enabled: Boolean(isSignedIn && selectedSoul),
      refetchOnMount: "always",
    },
  });

  const souls = useMemo(() => {
    if (searchResultsQuery.data?.status === 200) {
      return searchResultsQuery.data.data.items ?? [];
    }
    return [];
  }, [searchResultsQuery.data]);

  const handleApply = (soul: SoulsDirectorySoulRef) => {
    setSelectedSoul(soul);
  };

  const handleConfirm = () => {
    if (markdownQuery.data?.status === 200) {
      const content = markdownQuery.data.data.content ?? "";
      onSelect(content);
      handleClose();
    }
  };

  const handleClose = () => {
    onOpenChange(false);
    setSearchQuery("");
    setSelectedSoul(null);
  };

  const isLoading = searchResultsQuery.isFetching;
  const isLoadingContent = markdownQuery.isFetching;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent aria-label="Select soul template" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import from souls directory</DialogTitle>
          <DialogDescription>
            Search and select a soul template to import.
          </DialogDescription>
        </DialogHeader>

        {selectedSoul ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
              <p className="text-sm font-medium text-blue-900">
                Selected: {selectedSoul.slug}
              </p>
              <p className="mt-1 text-xs text-blue-700">@{selectedSoul.handle}</p>
            </div>
            {isLoadingContent ? (
              <div className="p-4 text-center text-sm text-slate-500">
                Loading content...
              </div>
            ) : markdownQuery.error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
                {markdownQuery.error.message}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search souls..."
                className="pl-10"
              />
            </div>

            <div className="max-h-[300px] overflow-y-auto">
              {isLoading ? (
                <div className="p-4 text-center text-sm text-slate-500">
                  Searching...
                </div>
              ) : !debouncedQuery ? (
                <div className="p-4 text-center text-sm text-slate-500">
                  Enter a search query to find souls.
                </div>
              ) : souls.length === 0 ? (
                <div className="p-4 text-center text-sm text-slate-500">
                  No souls found matching &quot;{debouncedQuery}&quot;.
                </div>
              ) : (
                <div className="grid gap-3">
                  {souls.map((soul) => (
                    <SoulPreviewCard
                      key={`${soul.handle}/${soul.slug}`}
                      soul={soul}
                      showApply
                      onApply={handleApply}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          {selectedSoul ? (
            <>
              <Button variant="outline" onClick={() => setSelectedSoul(null)}>
                Back
              </Button>
              <Button
                onClick={handleConfirm}
                disabled={isLoadingContent || !!markdownQuery.error}
              >
                {isLoadingContent ? "Loading..." : "Import template"}
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
