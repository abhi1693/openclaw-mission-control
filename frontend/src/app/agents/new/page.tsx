"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { useCreateAgentApiV1AgentsPost } from "@/api/generated/agents/agents";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import type { BoardRead } from "@/api/generated/model";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import SearchableSelect, {
  type SearchableSelectOption,
} from "@/components/ui/searchable-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DEFAULT_IDENTITY_PROFILE } from "@/lib/agent-templates";
import { SoulSelectorDialog } from "@/components/souls/SoulSelectorDialog";

type IdentityProfile = {
  role: string;
  communication_style: string;
  emoji: string;
  intake_checklist: string;
  execution_protocol: string;
  verification_commands: string;
  escalation_triggers: string;
  purpose: string;
  personality: string;
  custom_instructions: string;
};

const EMOJI_OPTIONS = [
  { value: ":gear:", label: "Gear", glyph: "⚙️" },
  { value: ":sparkles:", label: "Sparkles", glyph: "✨" },
  { value: ":rocket:", label: "Rocket", glyph: "🚀" },
  { value: ":megaphone:", label: "Megaphone", glyph: "📣" },
  { value: ":chart_with_upwards_trend:", label: "Growth", glyph: "📈" },
  { value: ":bulb:", label: "Idea", glyph: "💡" },
  { value: ":wrench:", label: "Builder", glyph: "🔧" },
  { value: ":shield:", label: "Shield", glyph: "🛡️" },
  { value: ":memo:", label: "Notes", glyph: "📝" },
  { value: ":brain:", label: "Brain", glyph: "🧠" },
];

const getBoardOptions = (boards: BoardRead[]): SearchableSelectOption[] =>
  boards.map((board) => ({
    value: board.id,
    label: board.name,
  }));

const normalizeProtocolBlock = (value: string): string =>
  value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");

const normalizeIdentityProfile = (
  profile: IdentityProfile,
): IdentityProfile | null => {
  const normalized: IdentityProfile = {
    role: profile.role.trim(),
    communication_style: profile.communication_style.trim(),
    emoji: profile.emoji.trim(),
    intake_checklist: normalizeProtocolBlock(profile.intake_checklist),
    execution_protocol: normalizeProtocolBlock(profile.execution_protocol),
    verification_commands: normalizeProtocolBlock(profile.verification_commands),
    escalation_triggers: normalizeProtocolBlock(profile.escalation_triggers),
    purpose: profile.purpose.trim(),
    personality: profile.personality.trim(),
    custom_instructions: profile.custom_instructions.trim(),
  };
  const hasValue = Object.values(normalized).some((value) => value.length > 0);
  return hasValue ? normalized : null;
};

export default function NewAgentPage() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [name, setName] = useState("");
  const [boardId, setBoardId] = useState<string>("");
  const [heartbeatEvery, setHeartbeatEvery] = useState("10m");
  const [identityProfile, setIdentityProfile] = useState<IdentityProfile>({
    ...DEFAULT_IDENTITY_PROFILE,
    intake_checklist: "",
    execution_protocol: "",
    verification_commands: "",
    escalation_triggers: "",
    purpose: DEFAULT_IDENTITY_PROFILE.purpose,
    personality: DEFAULT_IDENTITY_PROFILE.personality,
    custom_instructions: DEFAULT_IDENTITY_PROFILE.custom_instructions,
  });
  const [soulTemplate, setSoulTemplate] = useState("");
  const [identityTemplate, setIdentityTemplate] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);
  const [soulSelectorOpen, setSoulSelectorOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
    },
  });

  const createAgentMutation = useCreateAgentApiV1AgentsPost<ApiError>({
    mutation: {
      onSuccess: (result) => {
        if (result.status === 200) {
          router.push(`/agents/${result.data.id}`);
        }
      },
      onError: (err) => {
        setError(err.message || "Something went wrong.");
      },
    },
  });

  const boards =
    boardsQuery.data?.status === 200 ? (boardsQuery.data.data.items ?? []) : [];
  const displayBoardId = boardId || boards[0]?.id || "";
  const isLoading = boardsQuery.isLoading || createAgentMutation.isPending;
  const errorMessage = error ?? boardsQuery.error?.message ?? null;

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSignedIn) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Agent name is required.");
      return;
    }
    const resolvedBoardId = displayBoardId;
    if (!resolvedBoardId) {
      setError("Select a board before creating an agent.");
      return;
    }
    setError(null);
    createAgentMutation.mutate({
      data: {
        name: trimmed,
        board_id: resolvedBoardId,
        heartbeat_config: {
          every: heartbeatEvery.trim() || "10m",
          target: "last",
          includeReasoning: false,
        },
        identity_profile: normalizeIdentityProfile(
          identityProfile,
        ) as unknown as Record<string, unknown> | null,
        soul_template: soulTemplate.trim() || null,
        identity_template: identityTemplate.trim() || null,
      },
    });
  };

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to create an agent.",
        forceRedirectUrl: "/agents/new",
        signUpForceRedirectUrl: "/agents/new",
      }}
      title="Create agent"
      description="Agents start in provisioning until they check in."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can create agents."
    >
      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-6"
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Basic configuration
          </p>
          <div className="mt-4 space-y-6">
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Agent name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. Deploy bot"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Role
                </label>
                <Input
                  value={identityProfile.role}
                  onChange={(event) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      role: event.target.value,
                    }))
                  }
                  placeholder="e.g. Founder, Social Media Manager"
                  disabled={isLoading}
                />
              </div>
            </div>
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Board <span className="text-red-500">*</span>
                </label>
                <SearchableSelect
                  ariaLabel="Select board"
                  value={displayBoardId}
                  onValueChange={setBoardId}
                  options={getBoardOptions(boards)}
                  placeholder="Select board"
                  searchPlaceholder="Search boards..."
                  emptyMessage="No matching boards."
                  triggerClassName="w-full h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  contentClassName="rounded-xl border border-slate-200 shadow-lg"
                  itemClassName="px-4 py-3 text-sm text-slate-700 data-[selected=true]:bg-slate-50 data-[selected=true]:text-slate-900"
                  disabled={boards.length === 0}
                />
                {boards.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    Create a board before adding agents.
                  </p>
                ) : null}
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Emoji
                </label>
                <Select
                  value={identityProfile.emoji}
                  onValueChange={(value) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      emoji: value,
                    }))
                  }
                  disabled={isLoading}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select emoji" />
                  </SelectTrigger>
                  <SelectContent>
                    {EMOJI_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.glyph} {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Personality & behavior
          </p>
          <div className="mt-4 space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Communication style
              </label>
              <Input
                value={identityProfile.communication_style}
                onChange={(event) =>
                  setIdentityProfile((current) => ({
                    ...current,
                    communication_style: event.target.value,
                  }))
                }
                disabled={isLoading}
              />
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Intake checklist
                </label>
                <Textarea
                  value={identityProfile.intake_checklist}
                  onChange={(event) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      intake_checklist: event.target.value,
                    }))
                  }
                  placeholder="One step per line"
                  className="min-h-[120px]"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Execution protocol
                </label>
                <Textarea
                  value={identityProfile.execution_protocol}
                  onChange={(event) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      execution_protocol: event.target.value,
                    }))
                  }
                  placeholder="One step per line"
                  className="min-h-[120px]"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Verification commands
                </label>
                <Textarea
                  value={identityProfile.verification_commands}
                  onChange={(event) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      verification_commands: event.target.value,
                    }))
                  }
                  placeholder="One step per line"
                  className="min-h-[120px]"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Escalation triggers
                </label>
                <Textarea
                  value={identityProfile.escalation_triggers}
                  onChange={(event) =>
                    setIdentityProfile((current) => ({
                      ...current,
                      escalation_triggers: event.target.value,
                    }))
                  }
                  placeholder="One step per line"
                  className="min-h-[120px]"
                  disabled={isLoading}
                />
              </div>
            </div>
            <p className="text-xs text-slate-500">
              These steps are shown in the agent UI and stored in the identity profile.
            </p>
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Purpose & personality
          </p>
          <div className="mt-4 space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Purpose
              </label>
              <Textarea
                value={identityProfile.purpose}
                onChange={(event) =>
                  setIdentityProfile((current) => ({
                    ...current,
                    purpose: event.target.value,
                  }))
                }
                placeholder="What is this agent's mission?"
                className="min-h-[80px]"
                disabled={isLoading}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Personality
              </label>
              <Textarea
                value={identityProfile.personality}
                onChange={(event) =>
                  setIdentityProfile((current) => ({
                    ...current,
                    personality: event.target.value,
                  }))
                }
                placeholder="Describe personality traits"
                className="min-h-[80px]"
                disabled={isLoading}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Custom instructions
              </label>
              <Textarea
                value={identityProfile.custom_instructions}
                onChange={(event) =>
                  setIdentityProfile((current) => ({
                    ...current,
                    custom_instructions: event.target.value,
                  }))
                }
                placeholder="Additional instructions for this agent"
                className="min-h-[120px]"
                disabled={isLoading}
              />
            </div>
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Schedule & notifications
          </p>
          <div className="mt-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-900">
                Interval
              </label>
              <Input
                value={heartbeatEvery}
                onChange={(event) => setHeartbeatEvery(event.target.value)}
                placeholder="e.g. 10m"
                disabled={isLoading}
              />
              <p className="text-xs text-slate-500">
                How often this agent runs HEARTBEAT.md (10m, 30m, 2h).
              </p>
            </div>
          </div>
        </div>

        <div>
          <button
            type="button"
            className="flex w-full items-center justify-between text-left"
            onClick={() => setShowTemplates(!showTemplates)}
          >
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Templates (Advanced)
            </p>
            <span className="text-xs text-slate-400">
              {showTemplates ? "Hide" : "Show"}
            </span>
          </button>
          {showTemplates ? (
            <div className="mt-4 space-y-6">
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-500">
                  Override default templates. Leave blank to use defaults.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  type="button"
                  onClick={() => setSoulSelectorOpen(true)}
                >
                  Import from souls directory
                </Button>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Soul template
                </label>
                <Textarea
                  value={soulTemplate}
                  onChange={(event) => setSoulTemplate(event.target.value)}
                  placeholder="Custom SOUL.md content (Markdown)"
                  className="min-h-[200px] font-mono text-sm"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-900">
                  Identity template
                </label>
                <Textarea
                  value={identityTemplate}
                  onChange={(event) => setIdentityTemplate(event.target.value)}
                  placeholder="Custom IDENTITY.md content (Markdown)"
                  className="min-h-[200px] font-mono text-sm"
                  disabled={isLoading}
                />
              </div>
            </div>
          ) : null}

          <SoulSelectorDialog
            open={soulSelectorOpen}
            onOpenChange={setSoulSelectorOpen}
            onSelect={(content) => setSoulTemplate(content)}
          />
        </div>

        {errorMessage ? (
          <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600 shadow-sm">
            {errorMessage}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={isLoading}>
            {isLoading ? "Creating…" : "Create agent"}
          </Button>
          <Button
            variant="outline"
            type="button"
            onClick={() => router.push("/agents")}
          >
            Back to agents
          </Button>
        </div>
      </form>
    </DashboardPageLayout>
  );
}
