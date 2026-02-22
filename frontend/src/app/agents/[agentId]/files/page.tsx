"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type getAgentApiV1AgentsAgentIdGetResponse,
  useGetAgentApiV1AgentsAgentIdGet,
} from "@/api/generated/agents/agents";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type { AgentRead } from "@/api/generated/model";

type AgentFile = {
  name: string;
  editable: boolean;
};

export default function AgentFilesPage() {
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const params = useParams();
  const agentIdParam = params?.agentId;
  const agentId = Array.isArray(agentIdParam) ? agentIdParam[0] : agentIdParam;

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [files, setFiles] = useState<AgentFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importFileName, setImportFileName] = useState("");
  const [importFileContent, setImportFileContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const agentQuery = useGetAgentApiV1AgentsAgentIdGet<
    getAgentApiV1AgentsAgentIdGetResponse,
    ApiError
  >(agentId ?? "", {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && agentId),
      refetchOnMount: "always",
      retry: false,
    },
  });

  const agent: AgentRead | null =
    agentQuery.data?.status === 200 ? agentQuery.data.data : null;

  const loadFiles = async () => {
    if (!agentId || !agent?.board_id) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/agent/boards/${agent.board_id}/agents/${agentId}/files`,
        {
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
      if (!response.ok) {
        throw new Error(`Failed to load files: ${response.statusText}`);
      }
      const data = await response.json();
      setFiles(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    } finally {
      setLoading(false);
    }
  };

  const handleFileClick = async (fileName: string) => {
    if (!agentId || !agent?.board_id) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/agent/boards/${agent.board_id}/agents/${agentId}/files/${fileName}`,
        {
          headers: {
            Accept: "text/plain",
          },
        }
      );
      if (!response.ok) {
        throw new Error(`Failed to load file: ${response.statusText}`);
      }
      const fileContent = await response.text();
      setSelectedFile(fileName);
      setFileContent(fileContent);
      setEditDialogOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load file");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveFile = async () => {
    if (!agentId || !agent?.board_id || !selectedFile) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/agent/boards/${agent.board_id}/agents/${agentId}/files/${selectedFile}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            content: fileContent,
            reason: "Updated via Mission Control UI",
          }),
        }
      );
      if (!response.ok) {
        throw new Error(`Failed to save file: ${response.statusText}`);
      }
      setEditDialogOpen(false);
      setSelectedFile(null);
      setFileContent("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save file");
    } finally {
      setLoading(false);
    }
  };

  const handleImportFile = async () => {
    if (!agentId || !agent?.board_id || !importFileName) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/agent/boards/${agent.board_id}/agents/${agentId}/files/${importFileName}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            content: importFileContent,
            reason: "Imported via Mission Control UI",
          }),
        }
      );
      if (!response.ok) {
        throw new Error(`Failed to import file: ${response.statusText}`);
      }
      setImportDialogOpen(false);
      setImportFileName("");
      setImportFileContent("");
      await loadFiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import file");
    } finally {
      setLoading(false);
    }
  };

  // Load files when component mounts
  useEffect(() => {
    if (agent?.board_id) {
      void loadFiles();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.board_id]);

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to manage agent files.",
        forceRedirectUrl: `/agents/${agentId}/files`,
        signUpForceRedirectUrl: `/agents/${agentId}/files`,
      }}
      title={agent?.name ? `${agent.name} - Files` : "Agent Files"}
      description="Manage and edit agent markdown files"
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can manage agent files."
    >
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Agent Files</h2>
            <p className="mt-1 text-sm text-slate-600">
              View and edit agent configuration files
            </p>
          </div>
          <div className="flex gap-3">
            <Button onClick={() => setImportDialogOpen(true)}>
              Import File
            </Button>
            <Button
              variant="outline"
              onClick={() => router.push(`/agents/${agentId}`)}
            >
              Back to Agent
            </Button>
          </div>
        </div>

        {error ? (
          <div className="rounded-lg border border-slate-200 bg-red-50 p-3 text-sm text-red-600">
            {error}
          </div>
        ) : null}

        {loading && files.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-sm text-slate-600">
            Loading files…
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="divide-y divide-slate-200">
              {files.length === 0 ? (
                <div className="p-8 text-center">
                  <p className="text-sm text-slate-600">No files found</p>
                  <p className="mt-1 text-xs text-slate-500">
                    Agent files will appear here once provisioned
                  </p>
                </div>
              ) : (
                files.map((file) => (
                  <div
                    key={file.name}
                    className="flex items-center justify-between p-4 hover:bg-slate-50"
                  >
                    <div>
                      <p className="font-medium text-slate-900">{file.name}</p>
                      <p className="text-xs text-slate-500">
                        {file.editable ? "Editable" : "Read-only"}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void handleFileClick(file.name)}
                      >
                        {file.editable ? "Edit" : "View"}
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Edit/View Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>
              {selectedFile &&
              files.find((f) => f.name === selectedFile)?.editable
                ? "Edit"
                : "View"}{" "}
              {selectedFile}
            </DialogTitle>
            <DialogDescription>
              {selectedFile &&
              files.find((f) => f.name === selectedFile)?.editable
                ? "Make changes to the file content below"
                : "This file is read-only"}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Textarea
              value={fileContent}
              onChange={(e) => setFileContent(e.target.value)}
              className="min-h-[400px] font-mono text-sm"
              disabled={
                !selectedFile ||
                !files.find((f) => f.name === selectedFile)?.editable
              }
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setEditDialogOpen(false);
                setSelectedFile(null);
                setFileContent("");
              }}
            >
              Cancel
            </Button>
            {selectedFile &&
            files.find((f) => f.name === selectedFile)?.editable ? (
              <Button onClick={() => void handleSaveFile()} disabled={loading}>
                {loading ? "Saving…" : "Save Changes"}
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Import Dialog */}
      <Dialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Import Agent File</DialogTitle>
            <DialogDescription>
              Upload an existing agent markdown file to Mission Control
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                File name <span className="text-red-500">*</span>
              </label>
              <Input
                value={importFileName}
                onChange={(e) => setImportFileName(e.target.value)}
                placeholder="e.g., IDENTITY.md, SOUL.md, BOOTSTRAP.md"
              />
              <p className="text-xs text-slate-500">
                Use standard OpenClaw file names (IDENTITY.md, SOUL.md, etc.)
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                File content <span className="text-red-500">*</span>
              </label>
              <Textarea
                value={importFileContent}
                onChange={(e) => setImportFileContent(e.target.value)}
                className="min-h-[400px] font-mono text-sm"
                placeholder="Paste your agent file content here..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setImportDialogOpen(false);
                setImportFileName("");
                setImportFileContent("");
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleImportFile()}
              disabled={loading || !importFileName || !importFileContent}
            >
              {loading ? "Importing…" : "Import File"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardPageLayout>
  );
}
