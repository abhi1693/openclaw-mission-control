"use client";

export const dynamic = "force-dynamic";

import { useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { Copy, ArrowLeft } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import {
  type getMarkdownApiV1SoulsDirectoryHandleSlugGetResponse,
  useGetMarkdownApiV1SoulsDirectoryHandleSlugGet,
} from "@/api/generated/souls-directory/souls-directory";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/ui/markdown";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

export default function SoulDetailPage() {
  const router = useRouter();
  const params = useParams();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const handleParam = params?.handle;
  const slugParam = params?.slug;
  const handle = Array.isArray(handleParam) ? handleParam[0] : handleParam ?? "";
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam ?? "";

  const markdownQuery = useGetMarkdownApiV1SoulsDirectoryHandleSlugGet<
    getMarkdownApiV1SoulsDirectoryHandleSlugGetResponse,
    ApiError
  >(handle, slug, {
    query: {
      enabled: Boolean(isSignedIn && handle && slug),
      refetchOnMount: "always",
    },
  });

  const content = useMemo(() => {
    if (markdownQuery.data?.status === 200) {
      return markdownQuery.data.data.content ?? "";
    }
    return "";
  }, [markdownQuery.data]);

  const handleCopyRef = () => {
    navigator.clipboard.writeText(`${handle}/${slug}`);
  };

  const handleCopyContent = () => {
    navigator.clipboard.writeText(content);
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view soul details.",
        forceRedirectUrl: `/souls/${handle}/${slug}`,
      }}
      title={slug}
      description={`@${handle}`}
      headerActions={
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => router.push("/souls")}>
            <ArrowLeft className="mr-1.5 h-4 w-4" />
            Back to directory
          </Button>
          <Button variant="outline" onClick={handleCopyRef}>
            <Copy className="mr-1.5 h-4 w-4" />
            Copy ref
          </Button>
          <Button onClick={handleCopyContent} disabled={!content}>
            <Copy className="mr-1.5 h-4 w-4" />
            Copy content
          </Button>
        </div>
      }
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can view soul details."
    >
      {markdownQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500 shadow-sm">
          Loading soul content...
        </div>
      ) : markdownQuery.error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
          {markdownQuery.error.message}
        </div>
      ) : !content ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-600">
            No content found for this soul.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="prose prose-slate max-w-none">
            <Markdown content={content} variant="prose" />
          </div>
        </div>
      )}
    </DashboardPageLayout>
  );
}
