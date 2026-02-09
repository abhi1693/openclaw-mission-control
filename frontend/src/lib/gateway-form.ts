import { gatewaysStatusApiV1GatewaysStatusGet } from "@/api/generated/gateways/gateways";

export const DEFAULT_WORKSPACE_ROOT = "~/.openclaw";

export type GatewayCheckStatus = "idle" | "checking" | "success" | "error";

export const validateGatewayUrl = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return "Gateway URL is required.";
  try {
    const url = new URL(trimmed);
    if (url.protocol !== "ws:" && url.protocol !== "wss:") {
      return "Gateway URL must start with ws:// or wss://.";
    }
    if (!url.port) {
      return "Gateway URL must include an explicit port.";
    }
    return null;
  } catch {
    return "Enter a valid gateway URL including port.";
  }
};

export async function checkGatewayConnection(params: {
  gatewayUrl: string;
  gatewayToken: string;
}): Promise<{ ok: boolean; message: string }> {
  try {
    const requestParams: Record<string, string> = {
      gateway_url: params.gatewayUrl.trim(),
    };
    if (params.gatewayToken.trim()) {
      requestParams.gateway_token = params.gatewayToken.trim();
    }

    const response = await gatewaysStatusApiV1GatewaysStatusGet(requestParams);
    if (response.status !== 200) {
      return { ok: false, message: "Unable to reach gateway." };
    }
    const data = response.data;
    if (!data.connected) {
      return { ok: false, message: data.error ?? "Unable to reach gateway." };
    }
    return { ok: true, message: "Gateway reachable." };
  } catch (error) {
    return {
      ok: false,
      message:
        error instanceof Error ? error.message : "Unable to reach gateway.",
    };
  }
}
