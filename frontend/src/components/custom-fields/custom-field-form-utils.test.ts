import { describe, expect, it } from "vitest";

import type { TaskCustomFieldDefinitionRead } from "@/api/generated/model";
import { DEFAULT_CUSTOM_FIELD_FORM_STATE } from "./custom-field-form-types";
import {
  buildCustomFieldUpdatePayload,
  createCustomFieldPayload,
  formatCustomFieldDefaultValue,
  normalizeCustomFieldFormInput,
  parseCustomFieldDefaultValue,
} from "./custom-field-form-utils";

const buildField = (
  overrides: Partial<TaskCustomFieldDefinitionRead> = {},
): TaskCustomFieldDefinitionRead => ({
  id: "field-1",
  organization_id: "org-1",
  field_key: "client_name",
  label: "Client Name",
  field_type: "text",
  ui_visibility: "always",
  board_ids: ["board-1"],
  required: false,
  description: "Client display name",
  default_value: "Acme",
  validation_regex: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("parseCustomFieldDefaultValue", () => {
  it("parses primitive and json field types", () => {
    expect(parseCustomFieldDefaultValue("integer", "42")).toEqual({
      value: 42,
      error: null,
    });
    expect(parseCustomFieldDefaultValue("decimal", "-12.5")).toEqual({
      value: -12.5,
      error: null,
    });
    expect(parseCustomFieldDefaultValue("boolean", "TRUE")).toEqual({
      value: true,
      error: null,
    });
    expect(parseCustomFieldDefaultValue("json", '{"a":1}')).toEqual({
      value: { a: 1 },
      error: null,
    });
  });

  it("returns validation errors for invalid defaults", () => {
    expect(parseCustomFieldDefaultValue("integer", "42.5").error).toMatch(
      /valid integer/i,
    );
    expect(parseCustomFieldDefaultValue("boolean", "yes").error).toMatch(
      /true or false/i,
    );
    expect(parseCustomFieldDefaultValue("json", '"string"').error).toMatch(
      /object or array/i,
    );
  });
});

describe("normalizeCustomFieldFormInput", () => {
  it("validates create requirements", () => {
    const result = normalizeCustomFieldFormInput({
      mode: "create",
      formState: {
        ...DEFAULT_CUSTOM_FIELD_FORM_STATE,
        label: "Client Name",
      },
      selectedBoardIds: [],
    });

    expect(result.value).toBeNull();
    expect(result.error).toBe("Field key is required.");
  });

  it("normalizes and trims valid create input", () => {
    const result = normalizeCustomFieldFormInput({
      mode: "create",
      formState: {
        ...DEFAULT_CUSTOM_FIELD_FORM_STATE,
        fieldKey: "  client_name ",
        label: " Client Name ",
        fieldType: "integer",
        uiVisibility: "if_set",
        validationRegex: "",
        description: " Primary client ",
        required: true,
        defaultValue: " 7 ",
      },
      selectedBoardIds: ["board-1", "board-2"],
    });

    expect(result.error).toBeNull();
    expect(result.value).toEqual({
      fieldKey: "client_name",
      label: "Client Name",
      fieldType: "integer",
      uiVisibility: "if_set",
      validationRegex: null,
      description: "Primary client",
      required: true,
      defaultValue: 7,
      boardIds: ["board-1", "board-2"],
    });
  });
});

describe("payload helpers", () => {
  it("builds create payload from normalized values", () => {
    const payload = createCustomFieldPayload({
      fieldKey: "client_name",
      label: "Client Name",
      fieldType: "text",
      uiVisibility: "always",
      validationRegex: "^[A-Z]+$",
      description: "Display name",
      required: false,
      defaultValue: "ACME",
      boardIds: ["board-1"],
    });

    expect(payload).toEqual({
      field_key: "client_name",
      label: "Client Name",
      field_type: "text",
      ui_visibility: "always",
      validation_regex: "^[A-Z]+$",
      description: "Display name",
      required: false,
      default_value: "ACME",
      board_ids: ["board-1"],
    });
  });

  it("only includes changed fields in update payload", () => {
    const field = buildField();
    const updates = buildCustomFieldUpdatePayload(field, {
      fieldKey: "client_name",
      label: "Client Name",
      fieldType: "text",
      uiVisibility: "always",
      validationRegex: null,
      description: "Client display name",
      required: true,
      defaultValue: "ACME",
      boardIds: ["board-1"],
    });

    expect(updates).toEqual({
      required: true,
      default_value: "ACME",
    });
  });
});

describe("formatCustomFieldDefaultValue", () => {
  it("formats objects as minified or pretty json", () => {
    expect(formatCustomFieldDefaultValue({ a: 1 })).toBe('{"a":1}');
    expect(formatCustomFieldDefaultValue({ a: 1 }, { pretty: true })).toBe(
      '{\n  "a": 1\n}',
    );
  });
});
