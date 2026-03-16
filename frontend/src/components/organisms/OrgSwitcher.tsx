"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import {
  type listMyOrganizationsApiV1OrganizationsMeListGetResponse,
  useCreateOrganizationApiV1OrganizationsPost,
  useListMyOrganizationsApiV1OrganizationsMeListGet,
  useSetActiveOrgApiV1OrganizationsMeActivePatch,
} from "@/api/generated/organizations/organizations";
import { Button } from "@/components/ui/button";
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
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function OrgSwitcher() {
  const { isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [orgError, setOrgError] = useState<string | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("BroadcastChannel" in window)) return;
    const channel = new BroadcastChannel("org-switch");
    channelRef.current = channel;
    return () => {
      channel.close();
      channelRef.current = null;
    };
  }, []);

  const orgsQuery = useListMyOrganizationsApiV1OrganizationsMeListGet<
    listMyOrganizationsApiV1OrganizationsMeListGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn),
      refetchOnMount: "always",
      retry: false,
    },
  });
  const orgs = orgsQuery.data?.status === 200 ? orgsQuery.data.data : [];
  const activeOrg = orgs.find((item) => item.is_active) ?? null;
  const orgValue = activeOrg?.id ?? "personal";

  const announceOrgSwitch = (orgId: string) => {
    if (typeof window === "undefined") return;
    const payload = JSON.stringify({ orgId, ts: Date.now() });
    try {
      window.localStorage.setItem("openclaw_org_switch", payload);
    } catch {
      // Ignore storage failures.
    }
    channelRef.current?.postMessage(payload);
  };

  const setActiveOrgMutation =
    useSetActiveOrgApiV1OrganizationsMeActivePatch<ApiError>({
      mutation: {
        onSuccess: (_result, variables) => {
          const orgId = variables?.data?.organization_id;
          if (orgId) {
            announceOrgSwitch(orgId);
          }
          window.location.reload();
        },
        onError: (err) => {
          setOrgError(err.message || "Unable to switch organization.");
        },
      },
    });

  const createOrgMutation =
    useCreateOrganizationApiV1OrganizationsPost<ApiError>({
      mutation: {
        onSuccess: () => {
          setOrgName("");
          setOrgError(null);
          setCreateOpen(false);
          queryClient.invalidateQueries({
            queryKey: ["/api/v1/organizations/me/list"],
          });
          if (typeof window !== "undefined") {
            announceOrgSwitch("new");
          }
          window.location.reload();
        },
        onError: (err) => {
          setOrgError(err.message || "Unable to create organization.");
        },
      },
    });

  const handleOrgChange = (value: string) => {
    if (value === "__create__") {
      setOrgError(null);
      setCreateOpen(true);
      return;
    }
    if (!value || value === orgValue) {
      return;
    }
    setActiveOrgMutation.mutate({
      data: { organization_id: value },
    });
  };

  const handleCreateOrg = () => {
    const trimmed = orgName.trim();
    if (!trimmed) {
      setOrgError("Organization name is required.");
      return;
    }
    createOrgMutation.mutate({
      data: { name: trimmed },
    });
  };

  if (!isSignedIn) {
    return null;
  }

  return (
    <div className="relative">
      <Select value={orgValue} onValueChange={handleOrgChange}>
        <SelectTrigger className="h-9 w-[220px] rounded-md border-slate-200 bg-white px-3 text-sm font-medium text-slate-900 shadow-none focus:ring-2 focus:ring-blue-500/30 focus:ring-offset-0">
          <span className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-slate-400" />
            <SelectValue placeholder="Select organization" />
          </span>
        </SelectTrigger>
        <SelectContent className="min-w-[220px] rounded-md border-slate-200 p-1 shadow-xl">
          <div className="px-3 pb-2 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Org switcher
          </div>
          {orgs.length ? (
            orgs.map((org) => (
              <SelectItem
                key={org.id}
                value={org.id}
                className="rounded-md py-2 pl-7 pr-3 text-sm text-slate-700 data-[state=checked]:bg-slate-50 data-[state=checked]:text-slate-900 focus:bg-slate-100"
              >
                {org.name}
              </SelectItem>
            ))
          ) : (
            <SelectItem
              value={orgValue}
              className="rounded-md py-2 pl-7 pr-3 text-sm text-slate-700"
            >
              Organization
            </SelectItem>
          )}
          <SelectSeparator className="my-2" />
          <SelectItem
            value="__create__"
            className="rounded-md py-2 pl-3 pr-3 text-sm font-medium text-slate-600 hover:text-slate-900 focus:bg-slate-100 [&>span:first-child]:hidden"
          >
            <span className="flex items-center gap-2">
              <Plus className="h-4 w-4 text-slate-400" />
              Create new org
            </span>
          </SelectItem>
        </SelectContent>
      </Select>
      {orgError && !createOpen ? (
        <p className="absolute left-0 top-full mt-1 text-xs text-rose-500">
          {orgError}
        </p>
      ) : null}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent aria-label="Create organization">
          <DialogHeader>
            <DialogTitle>Create a new organization</DialogTitle>
            <DialogDescription>
              This will switch you to the new organization as soon as it is
              created.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-2">
            <label
              htmlFor="org-name"
              className="text-xs font-semibold uppercase tracking-wide text-muted"
            >
              Organization name
            </label>
            <Input
              id="org-name"
              placeholder="Acme Robotics"
              value={orgName}
              onChange={(event) => setOrgName(event.target.value)}
            />
            {orgError ? (
              <p className="text-sm text-rose-500">{orgError}</p>
            ) : null}
          </div>
          <DialogFooter className="mt-6">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleCreateOrg}
              disabled={createOrgMutation.isPending}
            >
              {createOrgMutation.isPending ? "Creating..." : "Create org"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
