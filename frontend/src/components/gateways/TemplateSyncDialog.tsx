"use client";

import { useState, useMemo } from "react";

import { ApiError } from "@/api/mutator";
import {
  type syncGatewayTemplatesApiV1GatewaysGatewayIdTemplatesSyncPostResponse,
  useSyncGatewayTemplatesApiV1GatewaysGatewayIdTemplatesSyncPost,
} from "@/api/generated/gateways/gateways";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { useAuth } from "@/auth/clerk";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import SearchableSelect, {
  type SearchableSelectOption,
} from "@/components/ui/searchable-select";

interface TemplateSyncDialogProps {
  gatewayId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface SyncResult {
  agents_updated: number;
  agents_skipped: number;
  main_updated: boolean;
  errors?: Array<{ agent_id: string; error: string }>;
}

export function TemplateSyncDialog({
  gatewayId,
  open,
  onOpenChange,
}: TemplateSyncDialogProps) {
  const { isSignedIn } = useAuth();

  const [includeMain, setIncludeMain] = useState(true);
  const [leadOnly, setLeadOnly] = useState(false);
  const [resetSessions, setResetSessions] = useState(false);
  const [rotateTokens, setRotateTokens] = useState(false);
  const [forceBootstrap, setForceBootstrap] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [boardId, setBoardId] = useState<string>("");
  const [result, setResult] = useState<SyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && open),
      refetchOnMount: "always",
    },
  });

  const boards = useMemo(
    () =>
      boardsQuery.data?.status === 200
        ? (boardsQuery.data.data.items ?? [])
        : [],
    [boardsQuery.data],
  );

  const boardOptions: SearchableSelectOption[] = useMemo(
    () => [
      { value: "", label: "All boards" },
      ...boards.map((board) => ({
        value: board.id,
        label: board.name,
      })),
    ],
    [boards],
  );

  const syncMutation =
    useSyncGatewayTemplatesApiV1GatewaysGatewayIdTemplatesSyncPost<
      ApiError,
      syncGatewayTemplatesApiV1GatewaysGatewayIdTemplatesSyncPostResponse
    >({
      mutation: {
        onSuccess: (response) => {
          if (response.status === 200) {
            setResult(response.data as SyncResult);
            setError(null);
          }
        },
        onError: (err) => {
          setError(err.message || "Something went wrong.");
          setResult(null);
        },
      },
    });

  const handleSync = () => {
    setError(null);
    setResult(null);
    syncMutation.mutate({
      gatewayId,
      params: {
        include_main: includeMain,
        lead_only: leadOnly,
        reset_sessions: resetSessions,
        rotate_tokens: rotateTokens,
        force_bootstrap: forceBootstrap,
        overwrite,
        board_id: boardId || null,
      },
    });
  };

  const handleClose = () => {
    onOpenChange(false);
    setResult(null);
    setError(null);
  };

  const isLoading = syncMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent aria-label="Sync templates">
        <DialogHeader>
          <DialogTitle>Sync templates</DialogTitle>
          <DialogDescription>
            Push template updates to agents connected to this gateway.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-sm font-medium text-emerald-800">
                Sync completed successfully
              </p>
              <ul className="mt-2 space-y-1 text-sm text-emerald-700">
                <li>Agents updated: {result.agents_updated}</li>
                <li>Agents skipped: {result.agents_skipped}</li>
                <li>Main agent updated: {result.main_updated ? "Yes" : "No"}</li>
              </ul>
            </div>
            {result.errors && result.errors.length > 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-medium text-amber-800">
                  Some agents had errors
                </p>
                <ul className="mt-2 space-y-1 text-sm text-amber-700">
                  {result.errors.map((err, index) => (
                    <li key={index}>
                      {err.agent_id}: {err.error}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-3">
              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-200"
                  checked={includeMain}
                  onChange={(e) => setIncludeMain(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="block font-medium text-slate-900">
                    Include main agent
                  </span>
                  <span className="block text-xs text-slate-500">
                    Update templates for the gateway main agent.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-200"
                  checked={leadOnly}
                  onChange={(e) => setLeadOnly(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="block font-medium text-slate-900">
                    Lead agents only
                  </span>
                  <span className="block text-xs text-slate-500">
                    Only update lead agents, skip regular agents.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-200"
                  checked={resetSessions}
                  onChange={(e) => setResetSessions(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="block font-medium text-slate-900">
                    Reset agent sessions
                  </span>
                  <span className="block text-xs text-slate-500">
                    Clear and restart agent sessions after sync.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-200"
                  checked={rotateTokens}
                  onChange={(e) => setRotateTokens(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="block font-medium text-slate-900">
                    Rotate auth tokens
                  </span>
                  <span className="block text-xs text-slate-500">
                    Generate new authentication tokens for agents.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-200"
                  checked={forceBootstrap}
                  onChange={(e) => setForceBootstrap(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="block font-medium text-slate-900">
                    Force bootstrap
                  </span>
                  <span className="block text-xs text-slate-500">
                    Force re-bootstrap agents even if already bootstrapped.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-200"
                  checked={overwrite}
                  onChange={(e) => setOverwrite(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="block font-medium text-slate-900">
                    Overwrite USER.md and MEMORY.md
                  </span>
                  <span className="block text-xs text-slate-500">
                    Replace existing user and memory files.
                  </span>
                </span>
              </label>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Filter by board
              </label>
              <SearchableSelect
                ariaLabel="Select board filter"
                value={boardId}
                onValueChange={setBoardId}
                options={boardOptions}
                placeholder="All boards"
                searchPlaceholder="Search boards..."
                emptyMessage="No matching boards."
                triggerClassName="w-full h-10 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                contentClassName="rounded-xl border border-slate-200 shadow-lg"
                itemClassName="px-4 py-2.5 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                disabled={isLoading}
              />
              <p className="text-xs text-slate-500">
                Optionally limit sync to agents on a specific board.
              </p>
            </div>
          </div>
        )}

        {error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {result ? "Close" : "Cancel"}
          </Button>
          {!result ? (
            <Button onClick={handleSync} disabled={isLoading}>
              {isLoading ? "Syncing..." : "Sync templates"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
