"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const MENTION_MAX_OPTIONS = 8;
const MENTION_PATTERN = /(?:^|\s)@([A-Za-z0-9_-]{0,31})$/;

type MentionTarget = {
  start: number;
  end: number;
  query: string;
};

type BoardChatComposerProps = {
  placeholder?: string;
  isSending?: boolean;
  disabled?: boolean;
  mentionSuggestions?: string[];
  onSend: (content: string) => Promise<boolean>;
};

const normalizeMentionHandle = (raw: string): string | null => {
  const trimmed = raw.trim().replace(/^@+/, "");
  if (!trimmed) return null;
  const token = trimmed.split(/\s+/)[0]?.replace(/[^A-Za-z0-9_-]/g, "") ?? "";
  if (!token) return null;
  if (!/^[A-Za-z]/.test(token)) return null;
  return token.slice(0, 32).toLowerCase();
};

const findMentionTarget = (
  text: string,
  caret: number,
): MentionTarget | null => {
  if (caret < 0 || caret > text.length) return null;
  const prefix = text.slice(0, caret);
  const match = prefix.match(MENTION_PATTERN);
  if (!match) return null;
  const query = (match[1] ?? "").toLowerCase();
  const start = caret - query.length - 1;
  return { start, end: caret, query };
};

function BoardChatComposerImpl({
  placeholder = "Message the board lead. Tag agents with @name.",
  isSending = false,
  disabled = false,
  mentionSuggestions,
  onSend,
}: BoardChatComposerProps) {
  const [value, setValue] = useState("");
  const [mentionTarget, setMentionTarget] = useState<MentionTarget | null>(
    null,
  );
  const [activeMentionIndex, setActiveMentionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const closeMenuTimeoutRef = useRef<number | null>(null);
  const shouldFocusAfterSendRef = useRef(false);

  const mentionOptions = useMemo(() => {
    const handles = new Set<string>(["lead"]);
    (mentionSuggestions ?? []).forEach((candidate) => {
      const handle = normalizeMentionHandle(candidate);
      if (handle) {
        handles.add(handle);
      }
    });
    return [...handles];
  }, [mentionSuggestions]);

  const filteredMentionOptions = useMemo(() => {
    if (!mentionTarget) return [];
    const query = mentionTarget.query;
    const startsWithMatches = mentionOptions.filter((option) =>
      option.startsWith(query),
    );
    return startsWithMatches.slice(0, MENTION_MAX_OPTIONS);
  }, [mentionOptions, mentionTarget]);

  const activeIndex =
    filteredMentionOptions.length > 0
      ? Math.min(activeMentionIndex, filteredMentionOptions.length - 1)
      : 0;

  useEffect(() => {
    if (isSending) return;
    if (!shouldFocusAfterSendRef.current) return;
    shouldFocusAfterSendRef.current = false;
    textareaRef.current?.focus();
  }, [isSending]);

  useEffect(() => {
    return () => {
      if (closeMenuTimeoutRef.current !== null) {
        window.clearTimeout(closeMenuTimeoutRef.current);
      }
    };
  }, []);

  const refreshMentionTarget = useCallback(
    (nextValue: string, caret: number) => {
      const nextTarget = findMentionTarget(nextValue, caret);
      setMentionTarget(nextTarget);
    },
    [],
  );

  const applyMentionSelection = useCallback(
    (handle: string) => {
      const textarea = textareaRef.current;
      if (!textarea || !mentionTarget) return;
      const replacement = `@${handle} `;
      const nextValue =
        value.slice(0, mentionTarget.start) +
        replacement +
        value.slice(mentionTarget.end);
      setValue(nextValue);
      setMentionTarget(null);
      setActiveMentionIndex(0);
      window.requestAnimationFrame(() => {
        const nextCaret = mentionTarget.start + replacement.length;
        textarea.focus();
        textarea.setSelectionRange(nextCaret, nextCaret);
      });
    },
    [mentionTarget, value],
  );

  const send = useCallback(async () => {
    if (isSending || disabled) return;
    const trimmed = value.trim();
    if (!trimmed) return;
    const ok = await onSend(trimmed);
    shouldFocusAfterSendRef.current = true;
    if (ok) {
      setValue("");
      setMentionTarget(null);
      setActiveMentionIndex(0);
    }
  }, [disabled, isSending, onSend, value]);

  return (
    <div className="mt-4 space-y-2">
      <div className="relative">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => {
            const nextValue = event.target.value;
            setValue(nextValue);
            refreshMentionTarget(
              nextValue,
              event.target.selectionStart ?? nextValue.length,
            );
          }}
          onClick={(event) => {
            refreshMentionTarget(
              value,
              event.currentTarget.selectionStart ?? value.length,
            );
          }}
          onKeyUp={(event) => {
            refreshMentionTarget(
              value,
              event.currentTarget.selectionStart ?? value.length,
            );
          }}
          onBlur={() => {
            if (closeMenuTimeoutRef.current !== null) {
              window.clearTimeout(closeMenuTimeoutRef.current);
            }
            closeMenuTimeoutRef.current = window.setTimeout(() => {
              setMentionTarget(null);
              setActiveMentionIndex(0);
            }, 120);
          }}
          onFocus={(event) => {
            refreshMentionTarget(
              value,
              event.currentTarget.selectionStart ?? value.length,
            );
          }}
          onKeyDown={(event) => {
            if (filteredMentionOptions.length > 0 && mentionTarget) {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveMentionIndex(
                  (prev) => (prev + 1) % filteredMentionOptions.length,
                );
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveMentionIndex(
                  (prev) =>
                    (prev - 1 + filteredMentionOptions.length) %
                    filteredMentionOptions.length,
                );
                return;
              }
              if (event.key === "Enter" || event.key === "Tab") {
                event.preventDefault();
                const selected = filteredMentionOptions[activeIndex];
                if (selected) {
                  applyMentionSelection(selected);
                }
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setMentionTarget(null);
                setActiveMentionIndex(0);
                return;
              }
            }
            if (event.key !== "Enter") return;
            if (event.nativeEvent.isComposing) return;
            if (event.shiftKey) return;
            event.preventDefault();
            void send();
          }}
          placeholder={placeholder}
          className="min-h-[120px]"
          disabled={isSending || disabled}
        />
        {mentionTarget && filteredMentionOptions.length > 0 ? (
          <div className="absolute bottom-full left-0 z-20 mb-2 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
            <div className="max-h-52 overflow-y-auto py-1">
              {filteredMentionOptions.map((option, index) => (
                <button
                  key={option}
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    applyMentionSelection(option);
                  }}
                  className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition ${
                    index === activeIndex
                      ? "bg-slate-100 text-slate-900"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="font-mono">@{option}</span>
                  <span className="text-xs text-slate-400">mention</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
      <div className="flex justify-end">
        <Button
          onClick={() => void send()}
          disabled={isSending || disabled || !value.trim()}
        >
          {isSending ? "Sending…" : "Send"}
        </Button>
      </div>
    </div>
  );
}

export const BoardChatComposer = memo(BoardChatComposerImpl);
BoardChatComposer.displayName = "BoardChatComposer";
