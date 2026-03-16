"use client";

export const dynamic = "force-dynamic";

import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type getSkillPackApiV1SkillsPacksPackIdGetResponse,
  useGetSkillPackApiV1SkillsPacksPackIdGet,
  useUpdateSkillPackApiV1SkillsPacksPackIdPatch,
} from "@/api/generated/skills/skills";
import { MarketplaceSkillForm } from "@/components/skills/MarketplaceSkillForm";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

export default function EditSkillPackPage() {
  const router = useRouter();
  const params = useParams();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const packIdParam = params?.packId;
  const packId = Array.isArray(packIdParam) ? packIdParam[0] : packIdParam;

  const packQuery = useGetSkillPackApiV1SkillsPacksPackIdGet<
    getSkillPackApiV1SkillsPacksPackIdGetResponse,
    ApiError
  >(packId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && packId),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const pack = packQuery.data?.status === 200 ? packQuery.data.data : null;

  const saveMutation =
    useUpdateSkillPackApiV1SkillsPacksPackIdPatch<ApiError>();

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to edit skill packs.",
        forceRedirectUrl: `/skills/packs/${packId ?? ""}/edit`,
      }}
      title={pack ? `Edit ${pack.name}` : "Edit skill pack"}
      description="Update skill URL pack details."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can manage skill packs."
      stickyHeader
    >
      {packQuery.isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          Loading pack...
        </div>
      ) : packQuery.error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700 shadow-sm">
          {packQuery.error.message}
        </div>
      ) : !pack ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          Pack not found.
        </div>
      ) : (
        <MarketplaceSkillForm
          key={pack.id}
          initialValues={{
            sourceUrl: pack.source_url,
            name: pack.name,
            description: pack.description ?? "",
            branch: pack.branch || "main",
          }}
          sourceLabel="Pack URL"
          nameLabel="Pack name (optional)"
          descriptionLabel="Pack description (optional)"
          branchLabel="Pack branch (optional)"
          branchPlaceholder="main"
          showBranch
          descriptionPlaceholder="Short summary shown in the packs list."
          requiredUrlMessage="Pack URL is required."
          invalidUrlMessage="Pack URL must be a GitHub repository URL (https://github.com/<owner>/<repo>)."
          submitLabel="Save changes"
          submittingLabel="Saving..."
          isSubmitting={saveMutation.isPending}
          onCancel={() => router.push("/skills/packs")}
          onSubmit={async (values) => {
            const result = await saveMutation.mutateAsync({
              packId: pack.id,
              data: {
                source_url: values.sourceUrl,
                name: values.name || undefined,
                description: values.description || undefined,
                branch: values.branch || "main",
                metadata: pack.metadata || {},
              },
            });
            if (result.status !== 200) {
              throw new Error("Unable to update pack.");
            }
            router.push("/skills/packs");
          }}
        />
      )}
    </DashboardPageLayout>
  );
}
