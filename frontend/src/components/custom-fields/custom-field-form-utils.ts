import type {
  BoardRead,
  TaskCustomFieldDefinitionCreate,
  TaskCustomFieldDefinitionRead,
  TaskCustomFieldDefinitionUpdate,
} from "@/api/generated/model";
import { ApiError } from "@/api/mutator";

import {
  type CustomFieldFormMode,
  type CustomFieldFormState,
  type CustomFieldType,
  STRING_VALIDATION_FIELD_TYPES,
} from "./custom-field-form-types";

export type ParsedDefaultValue = {
  value: unknown | null;
  error: string | null;
};

export type NormalizedCustomFieldFormValues = {
  fieldKey: string;
  label: string;
  fieldType: CustomFieldType;
  uiVisibility: CustomFieldFormState["uiVisibility"];
  validationRegex: string | null;
  description: string | null;
  required: boolean;
  defaultValue: unknown | null;
  boardIds: string[];
};

type NormalizeCustomFieldFormInputArgs = {
  mode: CustomFieldFormMode;
  formState: CustomFieldFormState;
  selectedBoardIds: Iterable<string>;
};

type NormalizeCustomFieldFormInputResult =
  | { value: NormalizedCustomFieldFormValues; error: null }
  | { value: null; error: string };

const canonicalJson = (value: unknown): string =>
  JSON.stringify(value) ?? "undefined";

const areSortedStringArraysEqual = (
  left: readonly string[],
  right: readonly string[],
): boolean =>
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

export const parseCustomFieldDefaultValue = (
  fieldType: CustomFieldType,
  value: string,
): ParsedDefaultValue => {
  const trimmed = value.trim();
  if (!trimmed) return { value: null, error: null };

  if (fieldType === "text" || fieldType === "text_long") {
    return { value: trimmed, error: null };
  }

  if (fieldType === "integer") {
    if (!/^-?\d+$/.test(trimmed)) {
      return { value: null, error: "Default value must be a valid integer." };
    }
    return { value: Number.parseInt(trimmed, 10), error: null };
  }

  if (fieldType === "decimal") {
    if (!/^-?\d+(\.\d+)?$/.test(trimmed)) {
      return { value: null, error: "Default value must be a valid decimal." };
    }
    return { value: Number.parseFloat(trimmed), error: null };
  }

  if (fieldType === "boolean") {
    if (trimmed.toLowerCase() === "true") return { value: true, error: null };
    if (trimmed.toLowerCase() === "false") return { value: false, error: null };
    return { value: null, error: "Default value must be true or false." };
  }

  if (
    fieldType === "date" ||
    fieldType === "date_time" ||
    fieldType === "url"
  ) {
    return { value: trimmed, error: null };
  }

  if (fieldType === "json") {
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed === null || typeof parsed !== "object") {
        return {
          value: null,
          error: "Default value must be valid JSON (object or array).",
        };
      }
      return { value: parsed, error: null };
    } catch {
      return {
        value: null,
        error: "Default value must be valid JSON (object or array).",
      };
    }
  }

  try {
    return { value: JSON.parse(trimmed), error: null };
  } catch {
    return { value: trimmed, error: null };
  }
};

export const formatCustomFieldDefaultValue = (
  value: unknown,
  options: { pretty?: boolean } = {},
): string => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return options.pretty
      ? JSON.stringify(value, null, 2)
      : JSON.stringify(value);
  } catch {
    return String(value);
  }
};

export const filterBoardsBySearch = (
  boards: BoardRead[],
  query: string,
): BoardRead[] => {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return boards;
  return boards.filter(
    (board) =>
      board.name.toLowerCase().includes(normalizedQuery) ||
      board.slug.toLowerCase().includes(normalizedQuery),
  );
};

export const normalizeCustomFieldFormInput = ({
  mode,
  formState,
  selectedBoardIds,
}: NormalizeCustomFieldFormInputArgs): NormalizeCustomFieldFormInputResult => {
  const trimmedFieldKey = formState.fieldKey.trim();
  const trimmedLabel = formState.label.trim();
  const trimmedValidationRegex = formState.validationRegex.trim();
  const boardIds = Array.from(selectedBoardIds);

  if (mode === "create" && !trimmedFieldKey) {
    return { value: null, error: "Field key is required." };
  }
  if (!trimmedLabel) return { value: null, error: "Label is required." };
  if (boardIds.length === 0) {
    return { value: null, error: "Select at least one board." };
  }
  if (
    trimmedValidationRegex &&
    !STRING_VALIDATION_FIELD_TYPES.has(formState.fieldType)
  ) {
    return {
      value: null,
      error: "Validation regex is only supported for string field types.",
    };
  }

  const parsedDefaultValue = parseCustomFieldDefaultValue(
    formState.fieldType,
    formState.defaultValue,
  );
  if (parsedDefaultValue.error) {
    return { value: null, error: parsedDefaultValue.error };
  }

  return {
    value: {
      fieldKey: trimmedFieldKey,
      label: trimmedLabel,
      fieldType: formState.fieldType,
      uiVisibility: formState.uiVisibility,
      validationRegex: trimmedValidationRegex || null,
      description: formState.description.trim() || null,
      required: formState.required,
      defaultValue: parsedDefaultValue.value,
      boardIds,
    },
    error: null,
  };
};

export const createCustomFieldPayload = (
  values: NormalizedCustomFieldFormValues,
): TaskCustomFieldDefinitionCreate => ({
  field_key: values.fieldKey,
  label: values.label,
  field_type: values.fieldType,
  ui_visibility: values.uiVisibility,
  validation_regex: values.validationRegex,
  description: values.description,
  required: values.required,
  default_value: values.defaultValue,
  board_ids: values.boardIds,
});

export const buildCustomFieldUpdatePayload = (
  field: TaskCustomFieldDefinitionRead,
  values: NormalizedCustomFieldFormValues,
): TaskCustomFieldDefinitionUpdate => {
  const updates: TaskCustomFieldDefinitionUpdate = {};

  if (values.label !== (field.label ?? field.field_key)) {
    updates.label = values.label;
  }
  if (values.fieldType !== (field.field_type ?? "text")) {
    updates.field_type = values.fieldType;
  }
  if (values.uiVisibility !== (field.ui_visibility ?? "always")) {
    updates.ui_visibility = values.uiVisibility;
  }
  if (values.validationRegex !== (field.validation_regex ?? null)) {
    updates.validation_regex = values.validationRegex;
  }
  if (values.description !== (field.description ?? null)) {
    updates.description = values.description;
  }
  if (values.required !== (field.required === true)) {
    updates.required = values.required;
  }
  if (
    canonicalJson(values.defaultValue) !== canonicalJson(field.default_value)
  ) {
    updates.default_value = values.defaultValue;
  }

  const currentBoardIds = [...(field.board_ids ?? [])].sort();
  const nextBoardIds = [...values.boardIds].sort();
  if (!areSortedStringArraysEqual(currentBoardIds, nextBoardIds)) {
    updates.board_ids = values.boardIds;
  }

  return updates;
};

export const deriveFormStateFromCustomField = (
  field: TaskCustomFieldDefinitionRead,
): CustomFieldFormState => ({
  fieldKey: field.field_key,
  label: field.label ?? field.field_key,
  fieldType: field.field_type ?? "text",
  uiVisibility: field.ui_visibility ?? "always",
  validationRegex: field.validation_regex ?? "",
  description: field.description ?? "",
  required: field.required === true,
  defaultValue: formatCustomFieldDefaultValue(field.default_value, {
    pretty: true,
  }),
});

export const extractApiErrorMessage = (
  error: unknown,
  fallback: string,
): string => {
  if (error instanceof ApiError) return error.message || fallback;
  if (error instanceof Error) return error.message || fallback;
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  if (detail) return String(detail);
  return fallback;
};
