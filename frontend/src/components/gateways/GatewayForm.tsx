import type { FormEvent } from "react";

import type { GatewayCheckStatus } from "@/lib/gateway-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type GatewayFormProps = {
  name: string;
  gatewayUrl: string;
  gatewayToken: string;
  disableDevicePairing: boolean;
  workspaceRoot: string;
  allowInsecureTls: boolean;
  gatewayUrlError: string | null;
  gatewayCheckStatus: GatewayCheckStatus;
  gatewayCheckMessage: string | null;
  errorMessage: string | null;
  isLoading: boolean;
  canSubmit: boolean;
  workspaceRootPlaceholder: string;
  cancelLabel: string;
  submitLabel: string;
  submitBusyLabel: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
  onNameChange: (next: string) => void;
  onGatewayUrlChange: (next: string) => void;
  onGatewayTokenChange: (next: string) => void;
  onDisableDevicePairingChange: (next: boolean) => void;
  onWorkspaceRootChange: (next: string) => void;
  onAllowInsecureTlsChange: (next: boolean) => void;
};

export function GatewayForm({
  name,
  gatewayUrl,
  gatewayToken,
  disableDevicePairing,
  workspaceRoot,
  allowInsecureTls,
  gatewayUrlError,
  gatewayCheckStatus,
  gatewayCheckMessage,
  errorMessage,
  isLoading,
  canSubmit,
  workspaceRootPlaceholder,
  cancelLabel,
  submitLabel,
  submitBusyLabel,
  onSubmit,
  onCancel,
  onNameChange,
  onGatewayUrlChange,
  onGatewayTokenChange,
  onDisableDevicePairingChange,
  onWorkspaceRootChange,
  onAllowInsecureTlsChange,
}: GatewayFormProps) {
  return (
    <form
      onSubmit={onSubmit}
      className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-900">
          Gateway name <span className="text-red-500">*</span>
        </label>
        <Input
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
          placeholder="Primary gateway"
          disabled={isLoading}
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Gateway URL <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <Input
              value={gatewayUrl}
              onChange={(event) => onGatewayUrlChange(event.target.value)}
              placeholder="ws://gateway:18789"
              disabled={isLoading}
              className={gatewayUrlError ? "border-red-500" : undefined}
            />
          </div>
          {gatewayUrlError ? (
            <p className="text-xs text-red-500">{gatewayUrlError}</p>
          ) : gatewayCheckStatus === "error" && gatewayCheckMessage ? (
            <p className="text-xs text-red-500">{gatewayCheckMessage}</p>
          ) : null}
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Gateway token
          </label>
          <Input
            value={gatewayToken}
            onChange={(event) => onGatewayTokenChange(event.target.value)}
            placeholder="Bearer token"
            disabled={isLoading}
          />
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Workspace root <span className="text-red-500">*</span>
          </label>
          <Input
            value={workspaceRoot}
            onChange={(event) => onWorkspaceRootChange(event.target.value)}
            placeholder={workspaceRootPlaceholder}
            disabled={isLoading}
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Disable device pairing
          </label>
          <label className="flex h-10 items-center gap-3 px-1 text-sm text-slate-900">
            <button
              type="button"
              role="switch"
              aria-checked={disableDevicePairing}
              aria-label="Disable device pairing"
              onClick={() =>
                onDisableDevicePairingChange(!disableDevicePairing)
              }
              disabled={isLoading}
              className={`inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition ${
                disableDevicePairing
                  ? "border-emerald-600 bg-emerald-600"
                  : "border-slate-300 bg-slate-200"
              } ${isLoading ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
            >
              <span
                className={`inline-block h-5 w-5 rounded-full bg-white shadow-sm transition ${
                  disableDevicePairing ? "translate-x-5" : "translate-x-0.5"
                }`}
              />
            </button>
          </label>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-900">
          Allow self-signed TLS certificates
        </label>
        <label className="flex h-10 items-center gap-3 px-1 text-sm text-slate-900">
          <button
            type="button"
            role="switch"
            aria-checked={allowInsecureTls}
            aria-label="Allow self-signed TLS certificates"
            onClick={() => onAllowInsecureTlsChange(!allowInsecureTls)}
            disabled={isLoading}
            className={`inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition ${
              allowInsecureTls
                ? "border-emerald-600 bg-emerald-600"
                : "border-slate-300 bg-slate-200"
            } ${isLoading ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
          >
            <span
              className={`inline-block h-5 w-5 rounded-full bg-white shadow-sm transition ${
                allowInsecureTls ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </label>
      </div>

      {errorMessage ? (
        <p className="text-sm text-red-500">{errorMessage}</p>
      ) : null}

      <div className="flex justify-end gap-3">
        <Button
          type="button"
          variant="ghost"
          onClick={onCancel}
          disabled={isLoading}
        >
          {cancelLabel}
        </Button>
        <Button type="submit" disabled={isLoading || !canSubmit}>
          {isLoading ? submitBusyLabel : submitLabel}
        </Button>
      </div>
    </form>
  );
}
