import type {
  TaskCustomFieldDefinitionReadFieldType,
  TaskCustomFieldDefinitionReadUiVisibility,
} from "@/api/generated/model";

export type CustomFieldType = TaskCustomFieldDefinitionReadFieldType;
export type CustomFieldVisibility = TaskCustomFieldDefinitionReadUiVisibility;

export type CustomFieldFormMode = "create" | "edit";

export type CustomFieldFormState = {
  fieldKey: string;
  label: string;
  fieldType: CustomFieldType;
  uiVisibility: CustomFieldVisibility;
  validationRegex: string;
  description: string;
  required: boolean;
  defaultValue: string;
};

export const DEFAULT_CUSTOM_FIELD_FORM_STATE: CustomFieldFormState = {
  fieldKey: "",
  label: "",
  fieldType: "text",
  uiVisibility: "always",
  validationRegex: "",
  description: "",
  required: false,
  defaultValue: "",
};

export const CUSTOM_FIELD_TYPE_OPTIONS: ReadonlyArray<{
  value: CustomFieldType;
  label: string;
}> = [
  { value: "text", label: "Text" },
  { value: "text_long", label: "Text (long)" },
  { value: "integer", label: "Integer" },
  { value: "decimal", label: "Decimal" },
  { value: "boolean", label: "Boolean (true/false)" },
  { value: "date", label: "Date" },
  { value: "date_time", label: "Date & time" },
  { value: "url", label: "URL" },
  { value: "json", label: "JSON" },
];

export const CUSTOM_FIELD_VISIBILITY_OPTIONS: ReadonlyArray<{
  value: CustomFieldVisibility;
  label: string;
}> = [
  { value: "always", label: "Always" },
  { value: "if_set", label: "If set" },
  { value: "hidden", label: "Hidden" },
];

export const STRING_VALIDATION_FIELD_TYPES = new Set<CustomFieldType>([
  "text",
  "text_long",
  "date",
  "date_time",
  "url",
]);
