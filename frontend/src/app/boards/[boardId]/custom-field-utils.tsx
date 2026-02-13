import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";

import type { TaskCustomFieldDefinitionRead } from "@/api/generated/model";
import { parseApiDatetime } from "@/lib/datetime";

export type TaskCustomFieldValues = Record<string, unknown>;

const isRecordObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export const normalizeCustomFieldValues = (
  value: unknown,
): TaskCustomFieldValues => {
  if (!isRecordObject(value)) return {};
  const entries = Object.entries(value);
  if (entries.length === 0) return {};
  return entries
    .sort(([left], [right]) => left.localeCompare(right))
    .reduce((acc, [key, rawValue]) => {
      if (isRecordObject(rawValue)) {
        acc[key] = normalizeCustomFieldValues(rawValue);
        return acc;
      }
      if (Array.isArray(rawValue)) {
        acc[key] = rawValue.map((item) =>
          isRecordObject(item) ? normalizeCustomFieldValues(item) : item,
        );
        return acc;
      }
      acc[key] = rawValue;
      return acc;
    }, {} as TaskCustomFieldValues);
};

export const canonicalizeCustomFieldValues = (value: unknown): string =>
  JSON.stringify(normalizeCustomFieldValues(value));

export const customFieldInputText = (value: unknown): string => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const formatDateOnlyValue = (value: string): string => {
  const trimmed = value.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (match) {
    const year = Number.parseInt(match[1], 10);
    const month = Number.parseInt(match[2], 10);
    const day = Number.parseInt(match[3], 10);
    const parsed = new Date(year, month - 1, day);
    if (
      parsed.getFullYear() === year &&
      parsed.getMonth() === month - 1 &&
      parsed.getDate() === day
    ) {
      return parsed.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    }
  }
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return trimmed;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
};

const formatDateTimeValue = (value: string): string => {
  const parsed = parseApiDatetime(value) ?? new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const formatCustomFieldDetailValue = (
  definition: TaskCustomFieldDefinitionRead,
  value: unknown,
): ReactNode => {
  if (value === null || value === undefined) return "—";

  const fieldType = definition.field_type ?? "text";
  if (fieldType === "boolean") {
    if (value === true) return "True";
    if (value === false) return "False";
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (normalized === "true") return "True";
      if (normalized === "false") return "False";
    }
    return customFieldInputText(value) || "—";
  }

  if (fieldType === "integer" || fieldType === "decimal") {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value.toLocaleString();
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) return "—";
      const parsed = Number(trimmed);
      if (Number.isFinite(parsed)) return parsed.toLocaleString();
      return trimmed;
    }
    return customFieldInputText(value) || "—";
  }

  if (fieldType === "date") {
    if (typeof value !== "string") return customFieldInputText(value) || "—";
    if (!value.trim()) return "—";
    return formatDateOnlyValue(value);
  }

  if (fieldType === "date_time") {
    if (typeof value !== "string") return customFieldInputText(value) || "—";
    if (!value.trim()) return "—";
    return formatDateTimeValue(value);
  }

  if (fieldType === "url") {
    if (typeof value !== "string") return customFieldInputText(value) || "—";
    const trimmed = value.trim();
    if (!trimmed) return "—";
    try {
      const parsedUrl = new URL(trimmed);
      return (
        <a
          href={parsedUrl.toString()}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-blue-700 underline decoration-blue-300 underline-offset-2 hover:text-blue-800"
        >
          <span className="break-all">{parsedUrl.toString()}</span>
          <ArrowUpRight className="h-3.5 w-3.5 flex-shrink-0" />
        </a>
      );
    } catch {
      return trimmed;
    }
  }

  if (fieldType === "json") {
    try {
      const normalized = typeof value === "string" ? JSON.parse(value) : value;
      return (
        <pre className="whitespace-pre-wrap break-words rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs leading-relaxed text-slate-800">
          {JSON.stringify(normalized, null, 2)}
        </pre>
      );
    } catch {
      return customFieldInputText(value) || "—";
    }
  }

  if (fieldType === "text_long") {
    const text = customFieldInputText(value);
    return text ? (
      <span className="whitespace-pre-wrap break-words">{text}</span>
    ) : (
      "—"
    );
  }

  return customFieldInputText(value) || "—";
};

const isCustomFieldValueSet = (value: unknown): boolean => {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isRecordObject(value)) return Object.keys(value).length > 0;
  return true;
};

export const isCustomFieldVisible = (
  definition: TaskCustomFieldDefinitionRead,
  value: unknown,
): boolean => {
  if (definition.ui_visibility === "hidden") return false;
  if (definition.ui_visibility === "if_set")
    return isCustomFieldValueSet(value);
  return true;
};

export const parseCustomFieldInputValue = (
  definition: TaskCustomFieldDefinitionRead,
  text: string,
): unknown | null => {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (
    definition.field_type === "text" ||
    definition.field_type === "text_long"
  ) {
    return trimmed;
  }
  if (definition.field_type === "integer") {
    if (!/^-?\d+$/.test(trimmed)) return trimmed;
    return Number.parseInt(trimmed, 10);
  }
  if (definition.field_type === "decimal") {
    if (!/^-?\d+(\.\d+)?$/.test(trimmed)) return trimmed;
    return Number.parseFloat(trimmed);
  }
  if (definition.field_type === "boolean") {
    if (trimmed.toLowerCase() === "true") return true;
    if (trimmed.toLowerCase() === "false") return false;
    return trimmed;
  }
  if (
    definition.field_type === "date" ||
    definition.field_type === "date_time" ||
    definition.field_type === "url"
  ) {
    return trimmed;
  }
  if (definition.field_type === "json") {
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed === null || typeof parsed !== "object") {
        return trimmed;
      }
      return parsed;
    } catch {
      return trimmed;
    }
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
};

export const boardCustomFieldValues = (
  definitions: TaskCustomFieldDefinitionRead[],
  value: unknown,
): TaskCustomFieldValues => {
  const source = normalizeCustomFieldValues(value);
  return definitions.reduce((acc, definition) => {
    const key = definition.field_key;
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      acc[key] = source[key];
      return acc;
    }
    acc[key] = definition.default_value ?? null;
    return acc;
  }, {} as TaskCustomFieldValues);
};

export const customFieldPayload = (
  definitions: TaskCustomFieldDefinitionRead[],
  values: TaskCustomFieldValues,
): TaskCustomFieldValues =>
  definitions.reduce((acc, definition) => {
    const key = definition.field_key;
    acc[key] =
      Object.prototype.hasOwnProperty.call(values, key) &&
      values[key] !== undefined
        ? values[key]
        : null;
    return acc;
  }, {} as TaskCustomFieldValues);

const canonicalizeCustomFieldValue = (value: unknown): string => {
  if (value === undefined) return "__undefined__";
  if (value === null) return "__null__";
  if (isRecordObject(value)) {
    return JSON.stringify(normalizeCustomFieldValues(value));
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

export const customFieldPatchPayload = (
  definitions: TaskCustomFieldDefinitionRead[],
  currentValues: TaskCustomFieldValues,
  nextValues: TaskCustomFieldValues,
): TaskCustomFieldValues =>
  definitions.reduce((acc, definition) => {
    const key = definition.field_key;
    const currentValue = Object.prototype.hasOwnProperty.call(
      currentValues,
      key,
    )
      ? currentValues[key]
      : null;
    const nextValue = Object.prototype.hasOwnProperty.call(nextValues, key)
      ? nextValues[key]
      : null;
    if (
      canonicalizeCustomFieldValue(currentValue) ===
      canonicalizeCustomFieldValue(nextValue)
    ) {
      return acc;
    }
    acc[key] = nextValue ?? null;
    return acc;
  }, {} as TaskCustomFieldValues);

export const firstMissingRequiredCustomField = (
  definitions: TaskCustomFieldDefinitionRead[],
  values: TaskCustomFieldValues,
): string | null => {
  for (const definition of definitions) {
    if (definition.required !== true) continue;
    const value = values[definition.field_key];
    if (value !== null && value !== undefined) continue;
    return definition.label || definition.field_key;
  }
  return null;
};
