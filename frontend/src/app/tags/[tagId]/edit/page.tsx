"use client";

export const dynamic = "force-dynamic";

import { useMemo } from "react";
import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type getTagApiV1TagsTagIdGetResponse,
  useGetTagApiV1TagsTagIdGet,
  useUpdateTagApiV1TagsTagIdPatch,
} from "@/api/generated/tags/tags";
import { TagForm } from "@/components/tags/TagForm";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

export default function EditTagPage() {
  const router = useRouter();
  const params = useParams();
  const tagIdParam = params?.tagId;
  const tagId = Array.isArray(tagIdParam) ? tagIdParam[0] : tagIdParam;
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const tagQuery = useGetTagApiV1TagsTagIdGet<
    getTagApiV1TagsTagIdGetResponse,
    ApiError
  >(tagId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && tagId),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const updateMutation = useUpdateTagApiV1TagsTagIdPatch<ApiError>({
    mutation: {
      retry: false,
    },
  });

  const tag = useMemo(
    () => (tagQuery.data?.status === 200 ? tagQuery.data.data : null),
    [tagQuery.data],
  );

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to edit tags.",
        forceRedirectUrl: `/tags/${tagId ?? ""}/edit`,
        signUpForceRedirectUrl: `/tags/${tagId ?? ""}/edit`,
      }}
      title={tag ? `Edit ${tag.name}` : "Edit tag"}
      description="Update tag details used across task boards."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can manage tags."
    >
      {tagQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          Loading tag…
        </div>
      ) : tagQuery.error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700 shadow-sm">
          {tagQuery.error.message}
        </div>
      ) : !tag ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          Tag not found.
        </div>
      ) : (
        <TagForm
          initialValues={{
            name: tag.name,
            slug: tag.slug,
            color: tag.color ?? "9e9e9e",
            description: tag.description ?? "",
          }}
          isSubmitting={updateMutation.isPending}
          submitLabel="Save changes"
          submittingLabel="Saving…"
          onCancel={() => router.push("/tags")}
          onSubmit={async (values) => {
            const result = await updateMutation.mutateAsync({
              tagId: tag.id,
              data: values,
            });
            if (result.status !== 200) {
              throw new Error("Unable to update tag.");
            }
            router.push("/tags");
          }}
        />
      )}
    </DashboardPageLayout>
  );
}
