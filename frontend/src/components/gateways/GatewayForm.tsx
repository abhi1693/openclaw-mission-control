import type { FormEvent } from "react";
import { CheckCircle2, RefreshCcw, XCircle } from "lucide-react";

import type { GatewayCheckStatus } from "@/lib/gateway-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type GatewayFormProps = {
  name: string;
  gatewayUrl: string;
  gatewayToken: string;
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
  onRunGatewayCheck: () => Promise<void>;
  onNameChange: (next: string) => void;
  onGatewayUrlChange: (next: string) => void;
  onGatewayTokenChange: (next: string) => void;
  onWorkspaceRootChange: (next: string) => void;
  onAllowInsecureTlsChange: (next: boolean) => void;
};

export function GatewayForm({
  name,
  gatewayUrl,
  gatewayToken,
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
  onRunGatewayCheck,
  onNameChange,
  onGatewayUrlChange,
  onGatewayTokenChange,
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
              onBlur={onRunGatewayCheck}
              placeholder="ws://gateway:18789"
              disabled={isLoading}
              className={gatewayUrlError ? "border-red-500" : undefined}
            />
            <button
              type="button"
              onClick={() => void onRunGatewayCheck()}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              aria-label="Check gateway connection"
            >
              {gatewayCheckStatus === "checking" ? (
                <RefreshCcw className="h-4 w-4 animate-spin" />
              ) : gatewayCheckStatus === "success" ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              ) : gatewayCheckStatus === "error" ? (
                <XCircle className="h-4 w-4 text-red-500" />
              ) : (
                <RefreshCcw className="h-4 w-4" />
              )}
            </button>
          </div>
          {gatewayUrlError ? (
            <p className="text-xs text-red-500">{gatewayUrlError}</p>
          ) : gatewayCheckMessage ? (
            <p
              className={
                gatewayCheckStatus === "success"
                  ? "text-xs text-emerald-600"
                  : "text-xs text-red-500"
              }
            >
              {gatewayCheckMessage}
            </p>
          ) : null}
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-900">
            Gateway token
          </label>
          <Input
            value={gatewayToken}
            onChange={(event) => onGatewayTokenChange(event.target.value)}
            onBlur={onRunGatewayCheck}
            placeholder="Bearer token"
            disabled={isLoading}
          />
        </div>
      </div>

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

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="allow-insecure-tls"
          className="h-4 w-4 rounded border-slate-300 text-blue-600"
          checked={allowInsecureTls}
          onChange={(event) => onAllowInsecureTlsChange(event.target.checked)}
          disabled={isLoading}
        />
        <label
          htmlFor="allow-insecure-tls"
          className="text-sm text-slate-700 cursor-pointer"
        >
          Allow self-signed TLS certificates (for localhost or trusted local
          networks)
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
