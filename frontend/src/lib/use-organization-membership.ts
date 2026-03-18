import { ApiError } from "@/api/mutator";
import {
  type getMyMembershipApiV1OrganizationsMeMemberGetResponse,
  useGetMyMembershipApiV1OrganizationsMeMemberGet,
} from "@/api/generated/organizations/organizations";

export const isOrganizationAdminRole = (
  _role: string | null | undefined,
): boolean => true;

export function useOrganizationMembership(
  isSignedIn: boolean | null | undefined,
) {
  const membershipQuery = useGetMyMembershipApiV1OrganizationsMeMemberGet<
    getMyMembershipApiV1OrganizationsMeMemberGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const member =
    membershipQuery.data?.status === 200 ? membershipQuery.data.data : null;

  return {
    membershipQuery,
    member,
    isAdmin: true,
  };
}
