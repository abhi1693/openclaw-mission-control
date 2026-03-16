"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type getGatewayApiV1GatewaysGatewayIdGetResponse,
  useGetGatewayApiV1GatewaysGatewayIdGet,
  useUpdateGatewayApiV1GatewaysGatewayIdPatch,
} from "@/api/generated/gateways/gateways";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type { GatewayUpdate } from "@/api/generated/model";
import { GatewayForm } from "@/components/gateways/GatewayForm";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import {
  DEFAULT_WORKSPACE_ROOT,
  checkGatewayConnection,
  type GatewayCheckStatus,
  validateGatewayUrl,
} from "@/lib/gateway-form";

export default function EditGatewayPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const params = useParams();
  const gatewayIdParam = params?.gatewayId;
  const gatewayId = Array.isArray(gatewayIdParam)
    ? gatewayIdParam[0]
    : gatewayIdParam;

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [name, setName] = useState<string | undefined>(undefined);
  const [gatewayUrl, setGatewayUrl] = useState<string | undefined>(undefined);
  const [gatewayToken, setGatewayToken] = useState<string | undefined>(
    undefined,
  );
  const [disableDevicePairing, setDisableDevicePairing] = useState<
    boolean | undefined
  >(undefined);
  const [workspaceRoot, setWorkspaceRoot] = useState<string | undefined>(
    undefined,
  );
  const [allowInsecureTls, setAllowInsecureTls] = useState<boolean | undefined>(
    undefined,
  );

  const [gatewayUrlError, setGatewayUrlError] = useState<string | null>(null);
  const [gatewayCheckStatus, setGatewayCheckStatus] =
    useState<GatewayCheckStatus>("idle");
  const [gatewayCheckMessage, setGatewayCheckMessage] = useState<string | null>(
    null,
  );

  const [error, setError] = useState<string | null>(null);

  const gatewayQuery = useGetGatewayApiV1GatewaysGatewayIdGet<
    getGatewayApiV1GatewaysGatewayIdGetResponse,
    ApiError
  >(gatewayId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && gatewayId),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const updateMutation = useUpdateGatewayApiV1GatewaysGatewayIdPatch<ApiError>({
    mutation: {
      onSuccess: (result) => {
        if (result.status === 200) {
          router.push(`/gateways/${result.data.id}`);
        }
      },
      onError: (err) => {
        setError(err.message || "Something went wrong.");
      },
    },
  });

  const loadedGateway =
    gatewayQuery.data?.status === 200 ? gatewayQuery.data.data : null;
  const resolvedName = name ?? loadedGateway?.name ?? "";
  const resolvedGatewayUrl = gatewayUrl ?? loadedGateway?.url ?? "";
  const resolvedGatewayToken = gatewayToken ?? loadedGateway?.token ?? "";
  const resolvedDisableDevicePairing =
    disableDevicePairing ?? loadedGateway?.disable_device_pairing ?? false;
  const resolvedWorkspaceRoot =
    workspaceRoot ?? loadedGateway?.workspace_root ?? DEFAULT_WORKSPACE_ROOT;
  const resolvedAllowInsecureTls =
    allowInsecureTls ?? loadedGateway?.allow_insecure_tls ?? false;

  const isLoading =
    gatewayQuery.isLoading ||
    updateMutation.isPending ||
    gatewayCheckStatus === "checking";
  const errorMessage = error ?? gatewayQuery.error?.message ?? null;

  const canSubmit =
    Boolean(resolvedName.trim()) &&
    Boolean(resolvedGatewayUrl.trim()) &&
    Boolean(resolvedWorkspaceRoot.trim());

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn || !gatewayId) return;

    if (!resolvedName.trim()) {
      setError("Gateway name is required.");
      return;
    }
    const gatewayValidation = validateGatewayUrl(resolvedGatewayUrl);
    setGatewayUrlError(gatewayValidation);
    if (gatewayValidation) {
      setGatewayCheckStatus("error");
      setGatewayCheckMessage(gatewayValidation);
      return;
    }
    if (!resolvedWorkspaceRoot.trim()) {
      setError("Workspace root is required.");
      return;
    }

    setGatewayCheckStatus("checking");
    setGatewayCheckMessage(null);
    const { ok, message } = await checkGatewayConnection({
      gatewayUrl: resolvedGatewayUrl,
      gatewayToken: resolvedGatewayToken,
      gatewayDisableDevicePairing: resolvedDisableDevicePairing,
      gatewayAllowInsecureTls: resolvedAllowInsecureTls,
    });
    setGatewayCheckStatus(ok ? "success" : "error");
    setGatewayCheckMessage(message);
    if (!ok) {
      return;
    }

    setError(null);

    const payload: GatewayUpdate = {
      name: resolvedName.trim(),
      url: resolvedGatewayUrl.trim(),
      token: resolvedGatewayToken.trim() || null,
      disable_device_pairing: resolvedDisableDevicePairing,
      workspace_root: resolvedWorkspaceRoot.trim(),
      allow_insecure_tls: resolvedAllowInsecureTls,
    };

    updateMutation.mutate({ gatewayId, data: payload });
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to edit a gateway.",
        forceRedirectUrl: `/gateways/${gatewayId}/edit`,
      }}
      title={
        resolvedName.trim()
          ? `Edit gateway — ${resolvedName.trim()}`
          : "Edit gateway"
      }
      description="Update connection settings for this OpenClaw gateway."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can edit gateways."
    >
      <GatewayForm
        name={resolvedName}
        gatewayUrl={resolvedGatewayUrl}
        gatewayToken={resolvedGatewayToken}
        disableDevicePairing={resolvedDisableDevicePairing}
        workspaceRoot={resolvedWorkspaceRoot}
        allowInsecureTls={resolvedAllowInsecureTls}
        gatewayUrlError={gatewayUrlError}
        gatewayCheckStatus={gatewayCheckStatus}
        gatewayCheckMessage={gatewayCheckMessage}
        errorMessage={errorMessage}
        isLoading={isLoading}
        canSubmit={canSubmit}
        workspaceRootPlaceholder={DEFAULT_WORKSPACE_ROOT}
        cancelLabel="Back"
        submitLabel="Save changes"
        submitBusyLabel="Saving…"
        onSubmit={handleSubmit}
        onCancel={() => router.push("/gateways")}
        onNameChange={setName}
        onGatewayUrlChange={(next) => {
          setGatewayUrl(next);
          setGatewayUrlError(null);
          setGatewayCheckStatus("idle");
          setGatewayCheckMessage(null);
        }}
        onGatewayTokenChange={(next) => {
          setGatewayToken(next);
          setGatewayCheckStatus("idle");
          setGatewayCheckMessage(null);
        }}
        onDisableDevicePairingChange={(next) => {
          setDisableDevicePairing(next);
          setGatewayCheckStatus("idle");
          setGatewayCheckMessage(null);
        }}
        onWorkspaceRootChange={setWorkspaceRoot}
        onAllowInsecureTlsChange={(next) => {
          setAllowInsecureTls(next);
          setGatewayCheckStatus("idle");
          setGatewayCheckMessage(null);
        }}
      />
    </DashboardPageLayout>
  );
}
