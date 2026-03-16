"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCcw } from "lucide-react";

import {
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { usePageActive } from "@/hooks/usePageActive";

import {
  answerOnboardingApiV1BoardsBoardIdOnboardingAnswerPost,
  confirmOnboardingApiV1BoardsBoardIdOnboardingConfirmPost,
  getOnboardingApiV1BoardsBoardIdOnboardingGet,
  startOnboardingApiV1BoardsBoardIdOnboardingStartPost,
} from "@/api/generated/board-onboarding/board-onboarding";
import type {
  BoardOnboardingAgentComplete,
  BoardOnboardingRead,
  BoardOnboardingReadMessages,
  BoardRead,
} from "@/api/generated/model";

type NormalizedMessage = {
  role: string;
  content: string;
};

/**
 * Normalize backend onboarding messages into a strict `{role, content}` list.
 *
 * The server stores messages as untyped JSON; this protects the UI from partial
 * or malformed entries.
 */
const normalizeMessages = (
  value?: BoardOnboardingReadMessages,
): NormalizedMessage[] | null => {
  if (!value) return null;
  if (!Array.isArray(value)) return null;
  const items: NormalizedMessage[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object") continue;
    const raw = entry as Record<string, unknown>;
    const role = typeof raw.role === "string" ? raw.role : null;
    const content = typeof raw.content === "string" ? raw.content : null;
    if (!role || !content) continue;
    items.push({ role, content });
  }
  return items.length ? items : null;
};

type QuestionOption = { id: string; label: string };

type Question = {
  question: string;
  options: QuestionOption[];
};

const FREE_TEXT_OPTION_RE =
  /(i'?ll type|i will type|type it|type my|other|custom|free\\s*text)/i;

const isFreeTextOption = (label: string) => FREE_TEXT_OPTION_RE.test(label);

/**
 * Best-effort parser for assistant-produced question payloads.
 *
 * During onboarding, the assistant can respond with either:
 * - raw JSON (ideal)
 * - a fenced ```json block
 * - slightly-structured objects
 *
 * This function validates shape and normalizes option ids/labels.
 */
const normalizeQuestion = (value: unknown): Question | null => {
  if (!value || typeof value !== "object") return null;
  const data = value as { question?: unknown; options?: unknown };
  if (typeof data.question !== "string" || !Array.isArray(data.options))
    return null;
  const options: QuestionOption[] = data.options
    .map((option, index) => {
      if (typeof option === "string") {
        return { id: String(index + 1), label: option };
      }
      if (option && typeof option === "object") {
        const raw = option as { id?: unknown; label?: unknown };
        const label =
          typeof raw.label === "string"
            ? raw.label
            : typeof raw.id === "string"
              ? raw.id
              : null;
        if (!label) return null;
        return {
          id: typeof raw.id === "string" ? raw.id : String(index + 1),
          label,
        };
      }
      return null;
    })
    .filter((option): option is QuestionOption => Boolean(option));
  if (!options.length) return null;
  return { question: data.question, options };
};

/**
 * Extract the most recent assistant question from the transcript.
 *
 * We intentionally only inspect the last assistant message: the user may have
 * typed arbitrary text between questions.
 */
const parseQuestion = (messages?: NormalizedMessage[] | null) => {
  if (!messages?.length) return null;
  const lastAssistant = [...messages]
    .reverse()
    .find((msg) => msg.role === "assistant");
  if (!lastAssistant?.content) return null;
  try {
    return normalizeQuestion(JSON.parse(lastAssistant.content));
  } catch {
    const match = lastAssistant.content.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (match) {
      try {
        return normalizeQuestion(JSON.parse(match[1]));
      } catch {
        return null;
      }
    }
  }
  return null;
};

export function BoardOnboardingChat({
  boardId,
  onConfirmed,
}: {
  boardId: string;
  onConfirmed: (board: BoardRead) => void;
}) {
  const isPageActive = usePageActive();
  const [session, setSession] = useState<BoardOnboardingRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [awaitingAssistantFingerprint, setAwaitingAssistantFingerprint] =
    useState<string | null>(null);
  const [awaitingKind, setAwaitingKind] = useState<
    "answer" | "extra_context" | null
  >(null);
  const [lastSubmittedAnswer, setLastSubmittedAnswer] = useState<string | null>(
    null,
  );
  const [otherText, setOtherText] = useState("");
  const [extraContext, setExtraContext] = useState("");
  const [extraContextOpen, setExtraContextOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);
  const freeTextRef = useRef<HTMLTextAreaElement | null>(null);
  const extraContextRef = useRef<HTMLTextAreaElement | null>(null);

  const normalizedMessages = useMemo(
    () => normalizeMessages(session?.messages),
    [session?.messages],
  );
  const lastAssistantFingerprint = useMemo(() => {
    const rawMessages = session?.messages;
    if (!rawMessages || !Array.isArray(rawMessages)) return "";
    for (let idx = rawMessages.length - 1; idx >= 0; idx -= 1) {
      const entry = rawMessages[idx];
      if (!entry || typeof entry !== "object") continue;
      const raw = entry as Record<string, unknown>;
      if (raw.role !== "assistant") continue;
      const content = typeof raw.content === "string" ? raw.content : "";
      const timestamp = typeof raw.timestamp === "string" ? raw.timestamp : "";
      return `${timestamp}|${content}`;
    }
    return "";
  }, [session?.messages]);
  const question = useMemo(
    () => parseQuestion(normalizedMessages),
    [normalizedMessages],
  );
  const draft: BoardOnboardingAgentComplete | null =
    session?.draft_goal ?? null;

  const isAwaitingAgent = useMemo(() => {
    if (!awaitingAssistantFingerprint) return false;
    return lastAssistantFingerprint === awaitingAssistantFingerprint;
  }, [awaitingAssistantFingerprint, lastAssistantFingerprint]);

  const wantsFreeText = useMemo(
    () => selectedOptions.some((label) => isFreeTextOption(label)),
    [selectedOptions],
  );

  useEffect(() => {
    if (!wantsFreeText) return;
    freeTextRef.current?.focus();
  }, [wantsFreeText]);

  useEffect(() => {
    if (!extraContextOpen) return;
    extraContextRef.current?.focus();
  }, [extraContextOpen]);

  useEffect(() => {
    setSelectedOptions([]);
    setOtherText("");
  }, [question?.question]);

  useEffect(() => {
    if (!wantsFreeText) setOtherText("");
  }, [wantsFreeText]);

  const startSession = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await startOnboardingApiV1BoardsBoardIdOnboardingStartPost(
        boardId,
        {},
      );
      if (result.status !== 200) throw new Error("Unable to start onboarding.");
      setSession(result.data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start onboarding.",
      );
    } finally {
      setLoading(false);
    }
  }, [boardId]);

  const refreshSession = useCallback(async () => {
    try {
      const result =
        await getOnboardingApiV1BoardsBoardIdOnboardingGet(boardId);
      if (result.status !== 200) return;
      setSession(result.data);
    } catch {
      // ignore
    }
  }, [boardId]);

  useEffect(() => {
    void startSession();
  }, [startSession]);

  const shouldPollSession =
    isPageActive && (loading || isAwaitingAgent || (!question && !draft));

  useEffect(() => {
    if (!shouldPollSession) return;
    void refreshSession();
    const interval = setInterval(() => {
      void refreshSession();
    }, 2000);
    return () => clearInterval(interval);
  }, [refreshSession, shouldPollSession]);

  const handleAnswer = useCallback(
    async (value: string, freeText?: string) => {
      const fingerprintBefore = lastAssistantFingerprint;
      setLoading(true);
      setError(null);
      setAwaitingAssistantFingerprint(null);
      setAwaitingKind(null);
      setLastSubmittedAnswer(null);
      try {
        const result =
          await answerOnboardingApiV1BoardsBoardIdOnboardingAnswerPost(
            boardId,
            {
              answer: value,
              other_text: freeText ?? null,
            },
          );
        if (result.status !== 200) throw new Error("Unable to submit answer.");
        setSession(result.data);
        setOtherText("");
        setSelectedOptions([]);
        setAwaitingAssistantFingerprint(fingerprintBefore);
        setAwaitingKind("answer");
        setLastSubmittedAnswer(freeText ? `${value}: ${freeText}` : value);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to submit answer.",
        );
      } finally {
        setLoading(false);
      }
    },
    [boardId, lastAssistantFingerprint],
  );

  const toggleOption = useCallback((label: string) => {
    setSelectedOptions((prev) =>
      prev.includes(label)
        ? prev.filter((item) => item !== label)
        : [...prev, label],
    );
  }, []);

  const submitExtraContext = useCallback(async () => {
    const trimmed = extraContext.trim();
    if (!trimmed) return;
    const fingerprintBefore = lastAssistantFingerprint;
    setLoading(true);
    setError(null);
    setAwaitingAssistantFingerprint(null);
    setAwaitingKind(null);
    setLastSubmittedAnswer(null);
    try {
      const result =
        await answerOnboardingApiV1BoardsBoardIdOnboardingAnswerPost(boardId, {
          answer: "Additional context",
          other_text: trimmed,
        });
      if (result.status !== 200)
        throw new Error("Unable to submit extra context.");
      setSession(result.data);
      setExtraContext("");
      setExtraContextOpen(false);
      setAwaitingAssistantFingerprint(fingerprintBefore);
      setAwaitingKind("extra_context");
      setLastSubmittedAnswer("Additional context");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to submit extra context.",
      );
    } finally {
      setLoading(false);
    }
  }, [boardId, extraContext, lastAssistantFingerprint]);

  const submitAnswer = useCallback(() => {
    const trimmedOther = otherText.trim();
    if (selectedOptions.length === 0) return;
    if (wantsFreeText && !trimmedOther) return;
    const answer = selectedOptions.join(", ");
    void handleAnswer(answer, wantsFreeText ? trimmedOther : undefined);
  }, [handleAnswer, otherText, selectedOptions, wantsFreeText]);

  useEffect(() => {
    if (!awaitingAssistantFingerprint) return;
    if (lastAssistantFingerprint !== awaitingAssistantFingerprint) {
      setAwaitingAssistantFingerprint(null);
      setAwaitingKind(null);
      setLastSubmittedAnswer(null);
    }
  }, [awaitingAssistantFingerprint, lastAssistantFingerprint]);

  const confirmGoal = async () => {
    if (!draft) return;
    setLoading(true);
    setError(null);
    try {
      const result =
        await confirmOnboardingApiV1BoardsBoardIdOnboardingConfirmPost(
          boardId,
          {
            board_type: draft.board_type ?? "goal",
            objective: draft.objective ?? null,
            success_metrics: draft.success_metrics ?? null,
            target_date: draft.target_date ?? null,
          },
        );
      if (result.status !== 200)
        throw new Error("Unable to confirm board goal.");
      onConfirmed(result.data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to confirm board goal.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <DialogHeader>
        <DialogTitle>Board onboarding</DialogTitle>
      </DialogHeader>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {draft ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Review the lead agent draft and confirm.
          </p>
          {isAwaitingAgent ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <div className="flex items-center gap-2 font-medium text-slate-900">
                <RefreshCcw className="h-4 w-4 animate-spin text-slate-500" />
                <span>
                  {awaitingKind === "extra_context"
                    ? "Updating the draft…"
                    : "Waiting for the agent…"}
                </span>
              </div>
              {lastSubmittedAnswer ? (
                <p className="mt-2 text-xs text-slate-600">
                  Sent:{" "}
                  <span className="font-medium text-slate-900">
                    {lastSubmittedAnswer}
                  </span>
                </p>
              ) : null}
              <p className="mt-1 text-xs text-slate-500">
                This usually takes a few seconds.
              </p>
            </div>
          ) : null}
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="font-semibold text-slate-900">Objective</p>
            <p className="text-slate-700">{draft.objective || "—"}</p>
            <p className="mt-3 font-semibold text-slate-900">Success metrics</p>
            <pre className="mt-1 whitespace-pre-wrap text-xs text-slate-600">
              {JSON.stringify(draft.success_metrics ?? {}, null, 2)}
            </pre>
            <p className="mt-3 font-semibold text-slate-900">Target date</p>
            <p className="text-slate-700">{draft.target_date || "—"}</p>
            <p className="mt-3 font-semibold text-slate-900">Board type</p>
            <p className="text-slate-700">{draft.board_type || "goal"}</p>
            {draft.user_profile ? (
              <>
                <p className="mt-4 font-semibold text-slate-900">
                  User profile
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">
                    Preferred name:
                  </span>{" "}
                  {draft.user_profile.preferred_name || "—"}
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">Pronouns:</span>{" "}
                  {draft.user_profile.pronouns || "—"}
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">Timezone:</span>{" "}
                  {draft.user_profile.timezone || "—"}
                </p>
              </>
            ) : null}
            {draft.lead_agent ? (
              <>
                <p className="mt-4 font-semibold text-slate-900">
                  Lead agent preferences
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">Name:</span>{" "}
                  {draft.lead_agent.name || "—"}
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">Role:</span>{" "}
                  {draft.lead_agent.identity_profile?.role || "—"}
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">
                    Communication:
                  </span>{" "}
                  {draft.lead_agent.identity_profile?.communication_style ||
                    "—"}
                </p>
                <p className="text-slate-700">
                  <span className="font-medium text-slate-900">Emoji:</span>{" "}
                  {draft.lead_agent.identity_profile?.emoji || "—"}
                </p>
              </>
            ) : null}
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-semibold text-slate-900">
                Extra context (optional)
              </p>
              <Button
                variant="ghost"
                size="sm"
                type="button"
                onClick={() => setExtraContextOpen((prev) => !prev)}
                disabled={loading || isAwaitingAgent}
              >
                {extraContextOpen ? "Hide" : "Add"}
              </Button>
            </div>
            {extraContextOpen ? (
              <div className="mt-2 space-y-2">
                <Textarea
                  ref={extraContextRef}
                  className="min-h-[84px]"
                  placeholder="Anything else the agent should know before you confirm? (constraints, context, preferences, links, etc.)"
                  value={extraContext}
                  onChange={(event) => setExtraContext(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter") return;
                    if (event.nativeEvent.isComposing) return;
                    if (event.shiftKey) return;
                    event.preventDefault();
                    if (loading || isAwaitingAgent) return;
                    void submitExtraContext();
                  }}
                  disabled={loading || isAwaitingAgent}
                />
                <div className="flex items-center justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    onClick={() => void submitExtraContext()}
                    disabled={
                      loading || isAwaitingAgent || !extraContext.trim()
                    }
                  >
                    {loading
                      ? "Sending..."
                      : isAwaitingAgent
                        ? "Waiting..."
                        : "Send context"}
                  </Button>
                </div>
                <p className="text-xs text-slate-500">
                  Tip: press Enter to send. Shift+Enter for a newline.
                </p>
              </div>
            ) : (
              <p className="mt-2 text-xs text-slate-600">
                Add anything that wasn&apos;t covered in the agent&apos;s
                questions.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              onClick={confirmGoal}
              disabled={loading || isAwaitingAgent}
              type="button"
            >
              Confirm goal
            </Button>
          </DialogFooter>
        </div>
      ) : question ? (
        <div className="space-y-3">
          <p className="text-sm font-medium text-slate-900">
            {question.question}
          </p>
          {isAwaitingAgent ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <div className="flex items-center gap-2 font-medium text-slate-900">
                <RefreshCcw className="h-4 w-4 animate-spin text-slate-500" />
                <span>
                  {awaitingKind === "extra_context"
                    ? "Updating the draft…"
                    : "Waiting for the next question…"}
                </span>
              </div>
              {lastSubmittedAnswer ? (
                <p className="mt-2 text-xs text-slate-600">
                  Sent:{" "}
                  <span className="font-medium text-slate-900">
                    {lastSubmittedAnswer}
                  </span>
                </p>
              ) : null}
              <p className="mt-1 text-xs text-slate-500">
                This usually takes a few seconds.
              </p>
            </div>
          ) : null}
          <div className="space-y-2">
            {question.options.map((option) => {
              const isSelected = selectedOptions.includes(option.label);
              return (
                <Button
                  key={option.id}
                  variant={isSelected ? "primary" : "secondary"}
                  className="w-full justify-start"
                  onClick={() => toggleOption(option.label)}
                  disabled={loading || isAwaitingAgent}
                  type="button"
                >
                  {option.label}
                </Button>
              );
            })}
          </div>
          {wantsFreeText ? (
            <div className="space-y-2">
              <Textarea
                ref={freeTextRef}
                className="min-h-[84px]"
                placeholder="Type your answer..."
                value={otherText}
                onChange={(event) => setOtherText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  if (event.nativeEvent.isComposing) return;
                  if (event.shiftKey) return;
                  event.preventDefault();
                  if (loading || isAwaitingAgent) return;
                  submitAnswer();
                }}
                disabled={loading || isAwaitingAgent}
              />
              <p className="text-xs text-slate-500">
                Tip: press Enter to send. Shift+Enter for a newline.
              </p>
            </div>
          ) : null}
          <div className="space-y-2">
            <Button
              variant="outline"
              onClick={submitAnswer}
              type="button"
              disabled={
                loading ||
                isAwaitingAgent ||
                selectedOptions.length === 0 ||
                (wantsFreeText && !otherText.trim())
              }
            >
              {loading ? "Sending..." : isAwaitingAgent ? "Waiting..." : "Next"}
            </Button>
            {loading ? (
              <p className="text-xs text-slate-500">Sending your answer…</p>
            ) : isAwaitingAgent ? (
              <p className="text-xs text-slate-500">
                Waiting for the agent to respond…
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          {loading
            ? "Waiting for the lead agent..."
            : "Preparing onboarding..."}
        </div>
      )}
    </div>
  );
}
