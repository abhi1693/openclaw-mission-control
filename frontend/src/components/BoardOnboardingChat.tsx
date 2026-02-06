"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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

const normalizeQuestion = (value: unknown): Question | null => {
  if (!value || typeof value !== "object") return null;
  const data = value as { question?: unknown; options?: unknown };
  if (typeof data.question !== "string" || !Array.isArray(data.options)) return null;
  const options: QuestionOption[] = data.options
    .map((option, index) => {
      if (typeof option === "string") {
        return { id: String(index + 1), label: option };
      }
      if (option && typeof option === "object") {
        const raw = option as { id?: unknown; label?: unknown };
        const label =
          typeof raw.label === "string" ? raw.label : typeof raw.id === "string" ? raw.id : null;
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

const parseQuestion = (messages?: NormalizedMessage[] | null) => {
  if (!messages?.length) return null;
  const lastAssistant = [...messages].reverse().find((msg) => msg.role === "assistant");
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
  const [session, setSession] = useState<BoardOnboardingRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [otherText, setOtherText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);

  const normalizedMessages = useMemo(
    () => normalizeMessages(session?.messages),
    [session?.messages],
  );
  const question = useMemo(() => parseQuestion(normalizedMessages), [normalizedMessages]);
  const draft: BoardOnboardingAgentComplete | null = session?.draft_goal ?? null;

  useEffect(() => {
    setSelectedOptions([]);
    setOtherText("");
  }, [question?.question]);

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
      setError(err instanceof Error ? err.message : "Failed to start onboarding.");
    } finally {
      setLoading(false);
    }
  }, [boardId]);

  const refreshSession = useCallback(async () => {
    try {
      const result = await getOnboardingApiV1BoardsBoardIdOnboardingGet(boardId);
      if (result.status !== 200) return;
      setSession(result.data);
    } catch {
      // ignore
    }
  }, [boardId]);

  useEffect(() => {
    startSession();
    const interval = setInterval(refreshSession, 2000);
    return () => clearInterval(interval);
  }, [startSession, refreshSession]);

  const handleAnswer = useCallback(
    async (value: string, freeText?: string) => {
      setLoading(true);
      setError(null);
      try {
        const result = await answerOnboardingApiV1BoardsBoardIdOnboardingAnswerPost(
          boardId,
          {
            answer: value,
            other_text: freeText ?? null,
          },
        );
        if (result.status !== 200) throw new Error("Unable to submit answer.");
        setSession(result.data);
        setOtherText("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to submit answer.");
      } finally {
        setLoading(false);
      }
    },
    [boardId],
  );

  const toggleOption = useCallback((label: string) => {
    setSelectedOptions((prev) =>
      prev.includes(label) ? prev.filter((item) => item !== label) : [...prev, label]
    );
  }, []);

  const submitAnswer = useCallback(() => {
    const trimmedOther = otherText.trim();
    if (selectedOptions.length === 0 && !trimmedOther) return;
    const answer =
      selectedOptions.length > 0 ? selectedOptions.join(", ") : "Other";
    void handleAnswer(answer, trimmedOther || undefined);
  }, [handleAnswer, otherText, selectedOptions]);

  const confirmGoal = async () => {
    if (!draft) return;
    setLoading(true);
    setError(null);
    try {
      const result = await confirmOnboardingApiV1BoardsBoardIdOnboardingConfirmPost(
        boardId,
        {
          board_type: draft.board_type ?? "goal",
          objective: draft.objective ?? null,
          success_metrics: draft.success_metrics ?? null,
          target_date: draft.target_date ?? null,
        },
      );
      if (result.status !== 200) throw new Error("Unable to confirm board goal.");
      onConfirmed(result.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm board goal.");
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
	                <p className="mt-4 font-semibold text-slate-900">User profile</p>
	                <p className="text-slate-700">
	                  <span className="font-medium text-slate-900">Preferred name:</span>{" "}
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
	                  {draft.lead_agent.identity_profile?.communication_style || "—"}
	                </p>
	                <p className="text-slate-700">
	                  <span className="font-medium text-slate-900">Emoji:</span>{" "}
	                  {draft.lead_agent.identity_profile?.emoji || "—"}
	                </p>
	                <p className="text-slate-700">
	                  <span className="font-medium text-slate-900">Autonomy:</span>{" "}
	                  {draft.lead_agent.autonomy_level || "—"}
	                </p>
	                <p className="text-slate-700">
	                  <span className="font-medium text-slate-900">Verbosity:</span>{" "}
	                  {draft.lead_agent.verbosity || "—"}
	                </p>
	                <p className="text-slate-700">
	                  <span className="font-medium text-slate-900">
	                    Output format:
	                  </span>{" "}
	                  {draft.lead_agent.output_format || "—"}
	                </p>
	                <p className="text-slate-700">
	                  <span className="font-medium text-slate-900">
	                    Update cadence:
	                  </span>{" "}
	                  {draft.lead_agent.update_cadence || "—"}
	                </p>
	                {draft.lead_agent.custom_instructions ? (
	                  <>
	                    <p className="mt-3 font-semibold text-slate-900">
	                      Custom instructions
	                    </p>
	                    <pre className="mt-1 whitespace-pre-wrap text-xs text-slate-600">
	                      {draft.lead_agent.custom_instructions}
	                    </pre>
	                  </>
	                ) : null}
	              </>
	            ) : null}
	          </div>
          <DialogFooter>
            <Button onClick={confirmGoal} disabled={loading}>
              Confirm goal
            </Button>
          </DialogFooter>
        </div>
      ) : question ? (
        <div className="space-y-3">
          <p className="text-sm font-medium text-slate-900">{question.question}</p>
          <div className="space-y-2">
            {question.options.map((option) => {
              const isSelected = selectedOptions.includes(option.label);
              return (
                <Button
                  key={option.id}
                  variant={isSelected ? "primary" : "secondary"}
                  className="w-full justify-start"
                  onClick={() => toggleOption(option.label)}
                  disabled={loading}
                >
                  {option.label}
                </Button>
              );
            })}
          </div>
          <div className="space-y-2">
            <Input
              placeholder="Other..."
              value={otherText}
              onChange={(event) => setOtherText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                if (loading) return;
                submitAnswer();
              }}
            />
            <Button
              variant="outline"
              onClick={submitAnswer}
              disabled={
                loading ||
                (selectedOptions.length === 0 && !otherText.trim())
              }
            >
              {loading ? "Sending..." : "Next"}
            </Button>
            {loading ? (
              <p className="text-xs text-slate-500">Sending your answer…</p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          {loading ? "Waiting for the lead agent..." : "Preparing onboarding..."}
        </div>
      )}
    </div>
  );
}
