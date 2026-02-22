import { describe, expect, it } from "vitest";
import { validateGatewayUrl } from "./gateway-form";

describe("validateGatewayUrl", () => {
  // --- Valid URLs (should return null) ---

  it("accepts ws:// with explicit non-default port", () => {
    expect(validateGatewayUrl("ws://localhost:18789")).toBeNull();
  });

  it("accepts wss:// with explicit non-default port", () => {
    expect(validateGatewayUrl("wss://gateway.example.com:8443")).toBeNull();
  });

  it("accepts wss:// with explicit default port 443", () => {
    // JavaScript URL API returns url.port="" for :443 — this must still be accepted
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

  // --- Invalid URLs (should return an error string) ---

  it("rejects empty string", () => {
    expect(validateGatewayUrl("")).toBe("Gateway URL is required.");
  });

  it("rejects wss:// with no port at all", () => {
    // This is the regression case: url.port=="" for both :443 and missing port
    expect(validateGatewayUrl("wss://gateway.example.com")).toBe(
      "Gateway URL must include an explicit port."
    );
  });

  it("rejects ws:// with no port at all", () => {
    expect(validateGatewayUrl("ws://localhost")).toBe(
      "Gateway URL must include an explicit port."
    );
  });

  it("rejects https:// scheme", () => {
    expect(validateGatewayUrl("https://gateway.example.com:443")).toBe(
      "Gateway URL must start with ws:// or wss://."
    );
  });

  it("rejects http:// scheme", () => {
    expect(validateGatewayUrl("http://localhost:8080")).toBe(
      "Gateway URL must start with ws:// or wss://."
    );
  });

  it("rejects completely invalid URL", () => {
    expect(validateGatewayUrl("not-a-url")).toBe(
      "Enter a valid gateway URL including port."
    );
  });

  it("rejects URL with only whitespace", () => {
    expect(validateGatewayUrl("   ")).toBe("Gateway URL is required.");
  });
});
