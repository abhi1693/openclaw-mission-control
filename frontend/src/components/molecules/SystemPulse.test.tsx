import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { SystemStatusResponse } from "@/api/generated/model/systemStatusResponse";

const useSystemStatusMock = vi.fn();

vi.mock("@/api/generated/system/system", () => ({
  useGetSystemStatusApiV1SystemStatusGet: (...args: unknown[]) =>
    useSystemStatusMock(...args),
}));

import { SystemPulse } from "./SystemPulse";

const success = (data: SystemStatusResponse) => ({
  data: { data, status: 200 },
  isLoading: false,
  error: null,
});

const baseStatus = (overrides: Partial<SystemStatusResponse> = {}): SystemStatusResponse => ({
  queue: { name: "default", depth: 0, scheduled_depth: 0 },
  agents: { total: 1, online: 1, offline: 0 },
  gateways: { total: 1 },
  ...overrides,
});

describe("SystemPulse", () => {
  beforeEach(() => {
    useSystemStatusMock.mockReset();
  });

  it("renders Healthy when queue is empty and all agents online", () => {
    useSystemStatusMock.mockReturnValue(success(baseStatus()));

    render(<SystemPulse />);

    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("1/1")).toBeInTheDocument();
    expect(screen.getByText("0 ready")).toBeInTheDocument();
  });

  it("renders Degraded when at least one agent is offline", () => {
    useSystemStatusMock.mockReturnValue(
      success(
        baseStatus({
          agents: { total: 23, online: 1, offline: 22 },
        }),
      ),
    );

    render(<SystemPulse />);

    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("1/23")).toBeInTheDocument();
    expect(screen.getByText("22 offline")).toBeInTheDocument();
  });

  it("renders Degraded when queue depth is at or above the warn threshold", () => {
    useSystemStatusMock.mockReturnValue(
      success(
        baseStatus({
          queue: { name: "default", depth: 25, scheduled_depth: 0 },
        }),
      ),
    );

    render(<SystemPulse />);

    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
  });

  it("renders Attention required when no agents are online but agents exist", () => {
    useSystemStatusMock.mockReturnValue(
      success(
        baseStatus({
          agents: { total: 5, online: 0, offline: 5 },
        }),
      ),
    );

    render(<SystemPulse />);

    expect(screen.getByText("Attention required")).toBeInTheDocument();
    expect(screen.getByText("0/5")).toBeInTheDocument();
  });

  it("shows the loading state on first fetch", () => {
    useSystemStatusMock.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    });

    render(<SystemPulse />);

    expect(screen.getByLabelText("System pulse loading")).toBeInTheDocument();
  });

  it("shows the unavailable banner when the request errors", () => {
    useSystemStatusMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("nope"),
    });

    render(<SystemPulse />);

    expect(screen.getByLabelText("System pulse unavailable")).toBeInTheDocument();
  });

  it("surfaces both ready and scheduled queue depth in the hint when scheduled is non-zero", () => {
    useSystemStatusMock.mockReturnValue(
      success(
        baseStatus({
          queue: { name: "default", depth: 3, scheduled_depth: 7 },
        }),
      ),
    );

    render(<SystemPulse />);

    expect(screen.getByText("3 ready · 7 scheduled")).toBeInTheDocument();
  });

  it("forwards the enabled flag and refetchInterval to the underlying query hook", () => {
    useSystemStatusMock.mockReturnValue(success(baseStatus()));

    render(<SystemPulse enabled={false} />);

    expect(useSystemStatusMock).toHaveBeenCalledWith(
      expect.objectContaining({
        query: expect.objectContaining({
          enabled: false,
          refetchInterval: 15_000,
        }),
      }),
    );
  });
});
