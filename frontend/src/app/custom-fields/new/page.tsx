"use client";

export const dynamic = "force-dynamic";

import { useMemo } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  getListOrgCustomFieldsApiV1OrganizationsMeCustomFieldsGetQueryKey,
  useCreateOrgCustomFieldApiV1OrganizationsMeCustomFieldsPost,
} from "@/api/generated/org-custom-fields/org-custom-fields";
import { CustomFieldForm } from "@/components/custom-fields/CustomFieldForm";
import { DEFAULT_CUSTOM_FIELD_FORM_STATE } from "@/components/custom-fields/custom-field-form-types";
import {
  createCustomFieldPayload,
  type NormalizedCustomFieldFormValues,
} from "@/components/custom-fields/custom-field-form-utils";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

export default function NewCustomFieldPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const queryClient = useQueryClient();

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchOnMount: "always",
        retry: false,
      },
    },
  );

  const boards = useMemo(
    () =>
      boardsQuery.data?.status === 200
        ? (boardsQuery.data.data.items ?? [])
        : [],
    [boardsQuery.data],
  );

  const createMutation =
    useCreateOrgCustomFieldApiV1OrganizationsMeCustomFieldsPost<ApiError>();
  const customFieldsKey =
    getListOrgCustomFieldsApiV1OrganizationsMeCustomFieldsGetQueryKey();

  const handleSubmit = async (values: NormalizedCustomFieldFormValues) => {
    await createMutation.mutateAsync({
      data: createCustomFieldPayload(values),
    });
    await queryClient.invalidateQueries({ queryKey: customFieldsKey });
    router.push("/custom-fields");
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to manage custom fields.",
        forceRedirectUrl: "/custom-fields",
        signUpForceRedirectUrl: "/custom-fields",
      }}
      title="Add custom field"
      description="Create an organization-level custom field and bind it to one or more boards."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can manage custom fields."
      stickyHeader
    >
      <CustomFieldForm
        mode="create"
        initialFormState={DEFAULT_CUSTOM_FIELD_FORM_STATE}
        boards={boards}
        boardsLoading={boardsQuery.isLoading}
        boardsError={boardsQuery.error?.message ?? null}
        isSubmitting={createMutation.isPending}
        submitLabel="Create field"
        submittingLabel="Creating..."
        submitErrorFallback="Failed to create custom field."
        onSubmit={handleSubmit}
      />
    </DashboardPageLayout>
  );
}
