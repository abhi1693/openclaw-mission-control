import { beforeEach, describe, expect, it, vi } from "vitest";

import { gatewaysStatusApiV1GatewaysStatusGet } from "@/api/generated/gateways/gateways";

import { checkGatewayConnection, validateGatewayUrl } from "./gateway-form";

vi.mock("@/api/generated/gateways/gateways", () => ({
  gatewaysStatusApiV1GatewaysStatusGet: vi.fn(),
}));

const mockedGatewaysStatusApiV1GatewaysStatusGet = vi.mocked(
  gatewaysStatusApiV1GatewaysStatusGet,
);

describe("validateGatewayUrl", () => {
  it("accepts ws:// with explicit non-default port", () => {
    expect(validateGatewayUrl("ws://localhost:18789")).toBeNull();
  });

  it("accepts wss:// with explicit non-default port", () => {
    expect(validateGatewayUrl("wss://gateway.example.com:8443")).toBeNull();
  });

  it("accepts wss:// with explicit default port 443", () => {
    expect(validateGatewayUrl("wss://devbot.tailcc2080.ts.net:443")).toBeNull();
  });

  it("accepts ws:// with explicit default port 80", () => {
    expect(validateGatewayUrl("ws://localhost:80")).toBeNull();
  });

  it("accepts URLs with a path after the port", () => {
    expect(validateGatewayUrl("wss://host.example.com:443/gateway")).toBeNull();
  });

  it("trims surrounding whitespace before validating", () => {
    expect(validateGatewayUrl("  wss://host:443  ")).toBeNull();
  });

  it("accepts IPv6 URLs with explicit non-default port", () => {
    expect(validateGatewayUrl("wss://[::1]:8080")).toBeNull();
  });

  it("accepts IPv6 URLs with explicit default port", () => {
    expect(validateGatewayUrl("wss://[2001:db8::1]:443")).toBeNull();
  });

  it("accepts userinfo URLs with explicit port", () => {
    expect(
      validateGatewayUrl("ws://user:pass@gateway.example.com:8080"),
    ).toBeNull();
  });

  it("accepts userinfo URLs with IPv6 host and explicit port", () => {
    expect(validateGatewayUrl("wss://user@[::1]:443")).toBeNull();
  });

  it("rejects empty string", () => {
    expect(validateGatewayUrl("")).toBe("Gateway URL is required.");
  });

  it("rejects wss:// with no port at all", () => {
    expect(validateGatewayUrl("wss://gateway.example.com")).toBe(
      "Gateway URL must include an explicit port.",
    );
  });

  it("rejects ws:// with no port at all", () => {
    expect(validateGatewayUrl("ws://localhost")).toBe(
      "Gateway URL must include an explicit port.",
    );
  });

  it("rejects https:// scheme", () => {
    expect(validateGatewayUrl("https://gateway.example.com:443")).toBe(
      "Gateway URL must start with ws:// or wss://.",
    );
  });

  it("rejects http:// scheme", () => {
    expect(validateGatewayUrl("http://localhost:8080")).toBe(
      "Gateway URL must start with ws:// or wss://.",
    );
  });

  it("rejects completely invalid URL", () => {
    expect(validateGatewayUrl("not-a-url")).toBe(
      "Enter a valid gateway URL including port.",
    );
  });

  it("rejects out-of-range ports", () => {
    expect(validateGatewayUrl("wss://gateway.example.com:65536")).toBe(
      "Enter a valid gateway URL including port.",
    );
  });

  it("rejects userinfo URLs with no explicit port", () => {
    expect(validateGatewayUrl("ws://user:pass@gateway.example.com")).toBe(
      "Gateway URL must include an explicit port.",
    );
  });

  it("rejects URL with only whitespace", () => {
    expect(validateGatewayUrl("   ")).toBe("Gateway URL is required.");
  });
});

describe("checkGatewayConnection", () => {
  beforeEach(() => {
    mockedGatewaysStatusApiV1GatewaysStatusGet.mockReset();
  });

  it("passes pairing and TLS toggles to gateway status API", async () => {
    mockedGatewaysStatusApiV1GatewaysStatusGet.mockResolvedValue({
      status: 200,
      data: { connected: true },
    } as never);

    const result = await checkGatewayConnection({
      gatewayUrl: "ws://gateway.example:18789",
      gatewayToken: "secret-token",
      gatewayDisableDevicePairing: true,
      gatewayAllowInsecureTls: true,
    });

    expect(mockedGatewaysStatusApiV1GatewaysStatusGet).toHaveBeenCalledWith({
      gateway_url: "ws://gateway.example:18789",
      gateway_token: "secret-token",
      gateway_disable_device_pairing: true,
      gateway_allow_insecure_tls: true,
    });
    expect(result).toEqual({ ok: true, message: "Gateway reachable." });
  });

  it("returns gateway-provided error message when offline", async () => {
    mockedGatewaysStatusApiV1GatewaysStatusGet.mockResolvedValue({
      status: 200,
      data: {
        connected: false,
        error: "missing required scope",
      },
    } as never);

    const result = await checkGatewayConnection({
      gatewayUrl: "ws://gateway.example:18789",
      gatewayToken: "",
      gatewayDisableDevicePairing: false,
      gatewayAllowInsecureTls: false,
    });

    expect(result).toEqual({ ok: false, message: "missing required scope" });
  });
});
