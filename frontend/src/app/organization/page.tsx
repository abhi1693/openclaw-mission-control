"use client";

export const dynamic = "force-dynamic";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { SignedIn, SignedOut, useAuth } from "@/auth/clerk";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, UserPlus, Users } from "lucide-react";

import { ApiError, customFetch } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  type getMyOrgApiV1OrganizationsMeGetResponse,
  type getMyMembershipApiV1OrganizationsMeMemberGetResponse,
  type getOrgMemberApiV1OrganizationsMeMembersMemberIdGetResponse,
  getListMyOrganizationsApiV1OrganizationsMeListGetQueryKey,
  type listOrgInvitesApiV1OrganizationsMeInvitesGetResponse,
  type listOrgMembersApiV1OrganizationsMeMembersGetResponse,
  getGetOrgMemberApiV1OrganizationsMeMembersMemberIdGetQueryKey,
  getListOrgInvitesApiV1OrganizationsMeInvitesGetQueryKey,
  getListOrgMembersApiV1OrganizationsMeMembersGetQueryKey,
  useCreateOrgInviteApiV1OrganizationsMeInvitesPost,
  useGetMyOrgApiV1OrganizationsMeGet,
  useGetMyMembershipApiV1OrganizationsMeMemberGet,
  useGetOrgMemberApiV1OrganizationsMeMembersMemberIdGet,
  useListOrgInvitesApiV1OrganizationsMeInvitesGet,
  useListOrgMembersApiV1OrganizationsMeMembersGet,
  useRevokeOrgInviteApiV1OrganizationsMeInvitesInviteIdDelete,
  useUpdateMemberAccessApiV1OrganizationsMeMembersMemberIdAccessPut,
  useUpdateOrgMemberApiV1OrganizationsMeMembersMemberIdPatch,
} from "@/api/generated/organizations/organizations";
import type {
  BoardRead,
  OrganizationBoardAccessSpec,
  OrganizationInviteRead,
} from "@/api/generated/model";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { BoardAccessTable } from "@/components/organization/BoardAccessTable";
import { MembersInvitesTable } from "@/components/organization/MembersInvitesTable";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmActionDialog } from "@/components/ui/confirm-action-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { cn } from "@/lib/utils";

type AccessScope = "all" | "custom";

type BoardAccessState = Record<string, { read: boolean; write: boolean }>;

const buildAccessList = (
  access: BoardAccessState,
): OrganizationBoardAccessSpec[] =>
  Object.entries(access)
    .filter(([, entry]) => entry.read || entry.write)
    .map(([boardId, entry]) => ({
      board_id: boardId,
      can_read: entry.read || entry.write,
      can_write: entry.write,
    }));

const defaultBoardAccess: BoardAccessState = {};

function BoardAccessEditor({
  boards,
  scope,
  onScopeChange,
  allRead,
  allWrite,
  onAllReadChange,
  onAllWriteChange,
  access,
  onAccessChange,
  disabled,
  emptyMessage,
}: {
  boards: BoardRead[];
  scope: AccessScope;
  onScopeChange: (scope: AccessScope) => void;
  allRead: boolean;
  allWrite: boolean;
  onAllReadChange: (next: boolean) => void;
  onAllWriteChange: (next: boolean) => void;
  access: BoardAccessState;
  onAccessChange: (next: BoardAccessState) => void;
  disabled?: boolean;
  emptyMessage?: string;
}) {
  const handleAllReadToggle = () => {
    if (disabled) return;
    const next = !allRead;
    onAllReadChange(next);
    if (!next && allWrite) {
      onAllWriteChange(false);
    }
  };

  const handleAllWriteToggle = () => {
    if (disabled) return;
    const next = !allWrite;
    onAllWriteChange(next);
    if (next && !allRead) {
      onAllReadChange(true);
    }
  };

  const updateBoardAccess = (
    boardId: string,
    next: { read: boolean; write: boolean },
  ) => {
    onAccessChange({
      ...access,
      [boardId]: {
        read: next.read || next.write,
        write: next.write,
      },
    });
  };

  const handleBoardReadToggle = (boardId: string) => {
    if (disabled) return;
    const current = access[boardId] ?? { read: false, write: false };
    const nextRead = !current.read;
    const nextWrite = nextRead ? current.write : false;
    updateBoardAccess(boardId, { read: nextRead, write: nextWrite });
  };

  const handleBoardWriteToggle = (boardId: string) => {
    if (disabled) return;
    const current = access[boardId] ?? { read: false, write: false };
    const nextWrite = !current.write;
    const nextRead = nextWrite ? true : current.read;
    updateBoardAccess(boardId, { read: nextRead, write: nextWrite });
  };

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Board access
        </p>
        <div className="mt-3 inline-flex rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-1">
          <button
            type="button"
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-semibold transition",
              scope === "all"
                ? "bg-[var(--surface)] text-[var(--text)] shadow-sm"
                : "text-[var(--text-muted)] hover:text-[var(--text)]",
            )}
            onClick={() => onScopeChange("all")}
            disabled={disabled}
          >
            All boards
          </button>
          <button
            type="button"
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-semibold transition",
              scope === "custom"
                ? "bg-[var(--surface)] text-[var(--text)] shadow-sm"
                : "text-[var(--text-muted)] hover:text-[var(--text)]",
            )}
            onClick={() => onScopeChange("custom")}
            disabled={disabled}
          >
            Selected boards
          </button>
        </div>
      </div>

      {scope === "all" ? (
        <div className="surface-card flex flex-wrap items-center gap-6 rounded-xl px-4 py-2.5 text-sm">
          <label className="flex items-center gap-2 text-[var(--text-muted)]">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={allRead}
              onChange={handleAllReadToggle}
              disabled={disabled}
            />
            Read
          </label>
          <label className="flex items-center gap-2 text-[var(--text-muted)]">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={allWrite}
              onChange={handleAllWriteToggle}
              disabled={disabled}
            />
            Write
          </label>
          <span className="text-xs text-[var(--text-muted)]">
            Write access implies read permissions.
          </span>
        </div>
      ) : (
        <div>
          {boards.length === 0 ? (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-muted)]">
              {emptyMessage ?? "No boards available yet."}
            </div>
          ) : (
            <div className="surface-card overflow-hidden rounded-xl">
              <BoardAccessTable
                boards={boards}
                access={access}
                onToggleRead={handleBoardReadToggle}
                onToggleWrite={handleBoardWriteToggle}
                disabled={disabled}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function OrganizationPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteScope, setInviteScope] = useState<AccessScope>("all");
  const [inviteAllRead, setInviteAllRead] = useState(true);
  const [inviteAllWrite, setInviteAllWrite] = useState(false);
  const [inviteAccess, setInviteAccess] =
    useState<BoardAccessState>(defaultBoardAccess);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [copiedInviteId, setCopiedInviteId] = useState<string | null>(null);

  const [accessDialogOpen, setAccessDialogOpen] = useState(false);
  const [activeMemberId, setActiveMemberId] = useState<string | null>(null);
  const [accessScope, setAccessScope] = useState<AccessScope | null>(null);
  const [accessAllRead, setAccessAllRead] = useState<boolean | null>(null);
  const [accessAllWrite, setAccessAllWrite] = useState<boolean | null>(null);
  const [accessRole, setAccessRole] = useState<string | null>(null);
  const [accessMap, setAccessMap] = useState<BoardAccessState | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [deleteOrgOpen, setDeleteOrgOpen] = useState(false);
  const [removeMemberOpen, setRemoveMemberOpen] = useState(false);

  const orgQuery = useGetMyOrgApiV1OrganizationsMeGet<
    getMyOrgApiV1OrganizationsMeGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
    },
  });

  const membersQuery = useListOrgMembersApiV1OrganizationsMeMembersGet<
    listOrgMembersApiV1OrganizationsMeMembersGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchOnMount: "always",
      },
    },
  );

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn),
        refetchOnMount: "always",
      },
    },
  );

  const membershipQuery = useGetMyMembershipApiV1OrganizationsMeMemberGet<
    getMyMembershipApiV1OrganizationsMeMemberGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
    },
  });

  const membershipRole =
    membershipQuery.data?.status === 200
      ? membershipQuery.data.data.role
      : null;
  const isOwner = membershipRole === "owner";
  const isAdmin = membershipRole === "admin" || membershipRole === "owner";

  const invitesQuery = useListOrgInvitesApiV1OrganizationsMeInvitesGet<
    listOrgInvitesApiV1OrganizationsMeInvitesGetResponse,
    ApiError
  >(
    { limit: 200 },
    {
      query: {
        enabled: Boolean(isSignedIn && isAdmin),
        refetchOnMount: "always",
        retry: false,
      },
    },
  );

  const members = useMemo(() => {
    if (membersQuery.data?.status !== 200) return [];
    return membersQuery.data.data.items ?? [];
  }, [membersQuery.data]);

  const invites = useMemo<OrganizationInviteRead[]>(() => {
    if (invitesQuery.data?.status !== 200) return [];
    return invitesQuery.data.data.items ?? [];
  }, [invitesQuery.data]);

  const boards = useMemo<BoardRead[]>(() => {
    if (boardsQuery.data?.status !== 200) return [];
    return boardsQuery.data.data.items ?? [];
  }, [boardsQuery.data]);

  const memberDetailsQuery =
    useGetOrgMemberApiV1OrganizationsMeMembersMemberIdGet<
      getOrgMemberApiV1OrganizationsMeMembersMemberIdGetResponse,
      ApiError
    >(activeMemberId ?? "", {
      query: {
        enabled: Boolean(activeMemberId && accessDialogOpen),
      },
    });

  const memberDetails =
    memberDetailsQuery.data?.status === 200
      ? memberDetailsQuery.data.data
      : null;

  const defaultAccess = useMemo(() => {
    if (!memberDetails) {
      return {
        role: "member",
        scope: "all" as AccessScope,
        allRead: false,
        allWrite: false,
        access: {},
      };
    }
    const isAll =
      memberDetails.all_boards_read || memberDetails.all_boards_write;
    const nextAccess: BoardAccessState = {};
    for (const entry of memberDetails.board_access ?? []) {
      nextAccess[entry.board_id] = {
        read: entry.can_read || entry.can_write,
        write: entry.can_write,
      };
    }
    return {
      role: memberDetails.role,
      scope: isAll ? "all" : ("custom" as AccessScope),
      allRead: memberDetails.all_boards_read,
      allWrite: memberDetails.all_boards_write,
      access: nextAccess,
    };
  }, [memberDetails]);

  const resolvedAccessRole = accessRole ?? defaultAccess.role;
  const resolvedAccessScope = accessScope ?? defaultAccess.scope;
  const resolvedAccessAllRead = accessAllRead ?? defaultAccess.allRead;
  const resolvedAccessAllWrite = accessAllWrite ?? defaultAccess.allWrite;
  const resolvedAccessMap = accessMap ?? defaultAccess.access;

  const createInviteMutation =
    useCreateOrgInviteApiV1OrganizationsMeInvitesPost<ApiError>({
      mutation: {
        onSuccess: (result) => {
          if (result.status === 200) {
            setInviteEmail("");
            setInviteRole("member");
            setInviteScope("all");
            setInviteAllRead(true);
            setInviteAllWrite(false);
            setInviteAccess(defaultBoardAccess);
            setInviteError(null);
            queryClient.invalidateQueries({
              queryKey: getListOrgInvitesApiV1OrganizationsMeInvitesGetQueryKey(
                {
                  limit: 200,
                },
              ),
            });
            setInviteDialogOpen(false);
          }
        },
        onError: (err) => {
          setInviteError(err.message || "Unable to create invite.");
        },
      },
    });

  const revokeInviteMutation =
    useRevokeOrgInviteApiV1OrganizationsMeInvitesInviteIdDelete<ApiError>({
      mutation: {
        onSuccess: () => {
          queryClient.invalidateQueries({
            queryKey: getListOrgInvitesApiV1OrganizationsMeInvitesGetQueryKey({
              limit: 200,
            }),
          });
        },
      },
    });

  const updateMemberAccessMutation =
    useUpdateMemberAccessApiV1OrganizationsMeMembersMemberIdAccessPut<ApiError>(
      {
        mutation: {
          onSuccess: () => {
            queryClient.invalidateQueries({
              queryKey: getListOrgMembersApiV1OrganizationsMeMembersGetQueryKey(
                {
                  limit: 200,
                },
              ),
            });
            if (activeMemberId) {
              queryClient.invalidateQueries({
                queryKey:
                  getGetOrgMemberApiV1OrganizationsMeMembersMemberIdGetQueryKey(
                    activeMemberId,
                  ),
              });
            }
          },
        },
      },
    );

  const updateMemberRoleMutation =
    useUpdateOrgMemberApiV1OrganizationsMeMembersMemberIdPatch<ApiError>({
      mutation: {
        onSuccess: () => {
          queryClient.invalidateQueries({
            queryKey: getListOrgMembersApiV1OrganizationsMeMembersGetQueryKey({
              limit: 200,
            }),
          });
        },
      },
    });

  const deleteOrganizationMutation = useMutation<
    { data: unknown; status: number; headers: Headers },
    ApiError
  >({
    mutationFn: async () =>
      customFetch<{ data: unknown; status: number; headers: Headers }>(
        "/api/v1/organizations/me",
        { method: "DELETE" },
      ),
    onSuccess: async () => {
      setDeleteOrgOpen(false);
      await queryClient.invalidateQueries({
        queryKey: getListMyOrganizationsApiV1OrganizationsMeListGetQueryKey(),
      });
      router.push("/dashboard");
      router.refresh();
    },
  });

  const removeMemberMutation = useMutation<
    { data: unknown; status: number; headers: Headers },
    ApiError,
    { memberId: string }
  >({
    mutationFn: async ({ memberId }) =>
      customFetch<{ data: unknown; status: number; headers: Headers }>(
        `/api/v1/organizations/me/members/${memberId}`,
        { method: "DELETE" },
      ),
    onSuccess: async () => {
      setRemoveMemberOpen(false);
      setAccessDialogOpen(false);
      setActiveMemberId(null);
      await queryClient.invalidateQueries({
        queryKey: getListOrgMembersApiV1OrganizationsMeMembersGetQueryKey({
          limit: 200,
        }),
      });
    },
  });

  const resetAccessState = () => {
    setAccessRole(null);
    setAccessScope(null);
    setAccessAllRead(null);
    setAccessAllWrite(null);
    setAccessMap(null);
    setAccessError(null);
  };

  const handleAccessDialogChange = (open: boolean) => {
    setAccessDialogOpen(open);
    if (!open) {
      setActiveMemberId(null);
      setAccessError(null);
      return;
    }
    resetAccessState();
  };

  const handleInviteDialogChange = (open: boolean) => {
    setInviteDialogOpen(open);
    if (!open) {
      setInviteError(null);
    }
  };

  const orgName =
    orgQuery.data?.status === 200 ? orgQuery.data.data.name : "Organization";

  const handleInviteSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn || !isAdmin) return;

    const trimmedEmail = inviteEmail.trim().toLowerCase();
    if (!trimmedEmail || !trimmedEmail.includes("@")) {
      setInviteError("Enter a valid email address.");
      return;
    }

    const hasAllAccess =
      inviteScope === "all" && (inviteAllRead || inviteAllWrite);
    const inviteAccessList = buildAccessList(inviteAccess);
    const hasCustomAccess =
      inviteScope === "custom" && inviteAccessList.length > 0;

    if (!hasAllAccess && !hasCustomAccess) {
      setInviteError("Select read or write access for at least one board.");
      return;
    }

    setInviteError(null);
    createInviteMutation.mutate({
      data: {
        invited_email: trimmedEmail,
        role: inviteRole,
        all_boards_read: inviteScope === "all" ? inviteAllRead : false,
        all_boards_write: inviteScope === "all" ? inviteAllWrite : false,
        board_access: inviteScope === "custom" ? inviteAccessList : [],
      },
    });
  };

  const handleCopyInvite = async (invite: OrganizationInviteRead) => {
    try {
      const baseUrl =
        typeof window !== "undefined" ? window.location.origin : "";
      const inviteUrl = baseUrl
        ? `${baseUrl}/invite?token=${invite.token}`
        : invite.token;
      let copied = false;

      if (typeof navigator !== "undefined" && navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(inviteUrl);
          copied = true;
        } catch {
          copied = false;
        }
      }

      if (!copied && typeof document !== "undefined") {
        const textarea = document.createElement("textarea");
        textarea.value = inviteUrl;
        textarea.setAttribute("readonly", "true");
        textarea.style.position = "absolute";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        copied = document.execCommand("copy");
        document.body.removeChild(textarea);
      }

      if (copied) {
        setCopiedInviteId(invite.id);
        setTimeout(() => setCopiedInviteId(null), 2000);
        return;
      }

      if (typeof window !== "undefined") {
        window.prompt("Copy invite link:", inviteUrl);
      }
    } catch {
      setCopiedInviteId(null);
    }
  };

  const openAccessDialog = (memberId: string) => {
    setActiveMemberId(memberId);
    setAccessDialogOpen(true);
    resetAccessState();
  };

  const handleSaveAccess = async () => {
    if (!activeMemberId || !isAdmin) return;

    const hasAllAccess =
      resolvedAccessScope === "all" &&
      (resolvedAccessAllRead || resolvedAccessAllWrite);
    const accessList = buildAccessList(resolvedAccessMap);
    const hasCustomAccess =
      resolvedAccessScope === "custom" && accessList.length > 0;

    if (!hasAllAccess && !hasCustomAccess) {
      setAccessError("Select read or write access for at least one board.");
      return;
    }

    setAccessError(null);

    try {
      if (memberDetails) {
        if (memberDetails.role !== resolvedAccessRole) {
          await updateMemberRoleMutation.mutateAsync({
            memberId: memberDetails.id,
            data: { role: resolvedAccessRole },
          });
        }
      }

      await updateMemberAccessMutation.mutateAsync({
        memberId: activeMemberId,
        data: {
          all_boards_read:
            resolvedAccessScope === "all" ? resolvedAccessAllRead : false,
          all_boards_write:
            resolvedAccessScope === "all" ? resolvedAccessAllWrite : false,
          board_access: resolvedAccessScope === "custom" ? accessList : [],
        },
      });

      setAccessDialogOpen(false);
    } catch (err) {
      setAccessError(
        err instanceof Error ? err.message : "Unable to update member access.",
      );
    }
  };

  const handleDeleteOrganization = () => {
    if (!isOwner) return;
    deleteOrganizationMutation.mutate();
  };

  const activeMemberCanBeRemoved =
    isAdmin &&
    memberDetails !== null &&
    memberDetails.user_id !== membershipQuery.data?.data.user_id &&
    (isOwner || memberDetails.role !== "owner");

  const handleRemoveMember = () => {
    if (!activeMemberId || !activeMemberCanBeRemoved) return;
    removeMemberMutation.mutate({ memberId: activeMemberId });
  };

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to manage your organization."
          forceRedirectUrl="/organization"
          signUpForceRedirectUrl="/organization"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-[var(--surface-muted)]">
          <div className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--surface)]">
            <div className="px-4 py-4 md:px-8 md:py-6">
              <div className="flex flex-wrap items-center justify-between gap-6">
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <h1 className="text-2xl font-semibold tracking-tight text-[var(--text)]">
                      Organization
                    </h1>
                    <Badge
                      variant="outline"
                      className="flex items-center gap-2"
                    >
                      <Building2 className="h-3.5 w-3.5" />
                      {orgName}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    Manage members and board access across your workspace.
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
                    <span>
                      <strong className="text-[var(--text)]">
                        {members.length}
                      </strong>{" "}
                      members
                    </span>
                    <span>
                      <strong className="text-[var(--text)]">
                        {boards.length}
                      </strong>{" "}
                      boards
                    </span>
                    <span>
                      <strong className="text-[var(--text)]">
                        {invites.length}
                      </strong>{" "}
                      pending
                    </span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {isOwner ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="border-rose-200 text-rose-600 hover:border-rose-300 hover:text-rose-700"
                      onClick={() => {
                        deleteOrganizationMutation.reset();
                        setDeleteOrgOpen(true);
                      }}
                    >
                      Delete organization
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    onClick={() => setInviteDialogOpen(true)}
                    disabled={!isAdmin}
                    title={
                      isAdmin
                        ? undefined
                        : "Only organization admins can invite"
                    }
                  >
                    <UserPlus className="h-4 w-4" />
                    Invite member
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <div className="px-4 py-4 md:px-8 md:py-8">
            <div className="surface-card overflow-hidden rounded-2xl">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--text)]">
                    Members & invites
                  </h2>
                  <p className="text-xs text-[var(--text-muted)]">
                    Invite teammates and tune their board permissions.
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                  <Users className="h-4 w-4" />
                  {members.length + invites.length} total
                </div>
              </div>
              <div className="overflow-x-auto">
                <MembersInvitesTable
                  members={members}
                  invites={isAdmin ? invites : []}
                  isLoading={
                    membersQuery.isLoading ||
                    (isAdmin && invitesQuery.isLoading)
                  }
                  isAdmin={isAdmin}
                  copiedInviteId={copiedInviteId}
                  onManageAccess={openAccessDialog}
                  onCopyInvite={handleCopyInvite}
                  onRevokeInvite={(inviteId) =>
                    revokeInviteMutation.mutate({
                      inviteId,
                    })
                  }
                  isRevoking={revokeInviteMutation.isPending}
                />
              </div>
            </div>
          </div>
        </main>
      </SignedIn>

      <Dialog open={inviteDialogOpen} onOpenChange={handleInviteDialogChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite a member</DialogTitle>
            <DialogDescription>
              Grant access to all boards or select specific workspaces.
            </DialogDescription>
          </DialogHeader>

          {isAdmin ? (
            <form className="space-y-5" onSubmit={handleInviteSubmit}>
              <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Email address
                  </label>
                  <Input
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    placeholder="name@company.com"
                    type="email"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Role
                  </label>
                  <Select value={inviteRole} onValueChange={setInviteRole}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select role" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="member">Member</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <BoardAccessEditor
                boards={boards}
                scope={inviteScope}
                onScopeChange={setInviteScope}
                allRead={inviteAllRead}
                allWrite={inviteAllWrite}
                onAllReadChange={setInviteAllRead}
                onAllWriteChange={setInviteAllWrite}
                access={inviteAccess}
                onAccessChange={setInviteAccess}
                emptyMessage={
                  boardsQuery.isLoading
                    ? "Loading boards..."
                    : "Create a board to start assigning access."
                }
              />

              {inviteError ? (
                <p className="text-sm text-rose-500">{inviteError}</p>
              ) : null}

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setInviteDialogOpen(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={createInviteMutation.isPending}>
                  {createInviteMutation.isPending
                    ? "Sending invite..."
                    : "Send invite"}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-muted)]">
              Only organization admins can invite new members.
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={accessDialogOpen} onOpenChange={handleAccessDialogChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Manage member access</DialogTitle>
            <DialogDescription>
              Adjust board permissions and role for this teammate.
            </DialogDescription>
          </DialogHeader>

          {memberDetailsQuery.isLoading ? (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-muted)]">
              Loading member access...
            </div>
          ) : memberDetailsQuery.data?.status === 200 ? (
            <div className="space-y-6">
              <div className="surface-card rounded-xl px-5 py-4">
                <p className="text-sm font-semibold text-[var(--text)]">
                  {memberDetailsQuery.data.data.user?.name ||
                    memberDetailsQuery.data.data.user?.preferred_name ||
                    memberDetailsQuery.data.data.user?.email ||
                    memberDetailsQuery.data.data.user_id}
                </p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {memberDetailsQuery.data.data.user?.email ??
                    "No email on file"}
                </p>
              </div>

              <div className="space-y-3">
                <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Role
                </label>
                <Select
                  value={resolvedAccessRole}
                  onValueChange={setAccessRole}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select role" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="owner">Owner</SelectItem>
                    <SelectItem value="member">Member</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <BoardAccessEditor
                boards={boards}
                scope={resolvedAccessScope}
                onScopeChange={setAccessScope}
                allRead={resolvedAccessAllRead}
                allWrite={resolvedAccessAllWrite}
                onAllReadChange={setAccessAllRead}
                onAllWriteChange={setAccessAllWrite}
                access={resolvedAccessMap}
                onAccessChange={setAccessMap}
                emptyMessage={
                  boardsQuery.isLoading ? "Loading boards..." : undefined
                }
              />

              {accessError ? (
                <p className="text-sm text-rose-500">{accessError}</p>
              ) : null}
            </div>
          ) : (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-muted)]">
              Unable to load member access.
            </div>
          )}

          <DialogFooter className="pt-2">
            {activeMemberCanBeRemoved ? (
              <Button
                type="button"
                variant="outline"
                className="mr-auto border-rose-200 text-rose-600 hover:border-rose-300 hover:text-rose-700"
                onClick={() => {
                  removeMemberMutation.reset();
                  setRemoveMemberOpen(true);
                }}
              >
                Remove member
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              onClick={() => setAccessDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleSaveAccess}
              disabled={
                updateMemberAccessMutation.isPending ||
                updateMemberRoleMutation.isPending ||
                removeMemberMutation.isPending
              }
            >
              {updateMemberAccessMutation.isPending ||
              updateMemberRoleMutation.isPending
                ? "Saving..."
                : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmActionDialog
        open={deleteOrgOpen}
        onOpenChange={(open) => {
          setDeleteOrgOpen(open);
          if (!open) {
            deleteOrganizationMutation.reset();
          }
        }}
        ariaLabel="Delete organization"
        title="Delete organization"
        description={
          <>
            This will permanently delete <strong>{orgName}</strong>, including
            boards, groups, gateways, members, and invites. This action cannot
            be undone.
          </>
        }
        errorMessage={deleteOrganizationMutation.error?.message}
        onConfirm={handleDeleteOrganization}
        isConfirming={deleteOrganizationMutation.isPending}
        confirmLabel="Delete organization"
        confirmingLabel="Deleting…"
      />
      <ConfirmActionDialog
        open={removeMemberOpen}
        onOpenChange={(open) => {
          setRemoveMemberOpen(open);
          if (!open) {
            removeMemberMutation.reset();
          }
        }}
        ariaLabel="Remove organization member"
        title="Remove member"
        description={
          <>
            Remove{" "}
            <strong>
              {memberDetails?.user?.name ||
                memberDetails?.user?.preferred_name ||
                memberDetails?.user?.email ||
                "this member"}
            </strong>{" "}
            from <strong>{orgName}</strong>? They will lose access immediately.
          </>
        }
        errorMessage={removeMemberMutation.error?.message}
        onConfirm={handleRemoveMember}
        isConfirming={removeMemberMutation.isPending}
        confirmLabel="Remove member"
        confirmingLabel="Removing…"
      />
    </DashboardShell>
  );
}
