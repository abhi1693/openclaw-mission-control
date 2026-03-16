import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { TaskCustomFieldDefinitionRead } from "@/api/generated/model";
import {
  boardCustomFieldValues,
  canonicalizeCustomFieldValues,
  customFieldPayload,
  customFieldPatchPayload,
  firstMissingRequiredCustomField,
  formatCustomFieldDetailValue,
  isCustomFieldVisible,
  parseCustomFieldInputValue,
  type TaskCustomFieldValues,
} from "./custom-field-utils";

const buildDefinition = (
  overrides: Partial<TaskCustomFieldDefinitionRead> = {},
): TaskCustomFieldDefinitionRead => ({
  id: "field-1",
  organization_id: "org-1",
  field_key: "client_name",
  field_type: "text",
  ui_visibility: "always",
  label: "Client name",
  required: false,
  default_value: null,
  description: null,
  validation_regex: null,
  board_ids: ["board-1"],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("custom-field-utils", () => {
  it("normalizes board field values with defaults", () => {
    const definitions = [
      buildDefinition({ field_key: "priority", default_value: "medium" }),
      buildDefinition({
        id: "field-2",
        field_key: "estimate",
        default_value: 1,
      }),
    ];

    expect(boardCustomFieldValues(definitions, { priority: "high" })).toEqual({
      priority: "high",
      estimate: 1,
    });
  });

  it("builds payload and patch payload with only changed keys", () => {
    const definitions = [
      buildDefinition({ field_key: "priority" }),
      buildDefinition({
        id: "field-2",
        field_key: "estimate",
        field_type: "integer",
      }),
    ];
    const currentValues: TaskCustomFieldValues = {
      priority: "high",
      estimate: 2,
    };
    const nextPayload = customFieldPayload(definitions, {
      priority: "high",
      estimate: 3,
    });

    expect(nextPayload).toEqual({ priority: "high", estimate: 3 });
    expect(
      customFieldPatchPayload(definitions, currentValues, nextPayload),
    ).toEqual({
      estimate: 3,
    });
  });

  it("finds the first missing required custom field", () => {
    const definitions = [
      buildDefinition({
        field_key: "required_a",
        label: "Required A",
        required: true,
      }),
      buildDefinition({
        id: "field-2",
        field_key: "required_b",
        label: "Required B",
        required: true,
      }),
    ];

    expect(
      firstMissingRequiredCustomField(definitions, { required_a: "value" }),
    ).toBe("Required B");
  });

  it("parses typed custom-field input values", () => {
    expect(
      parseCustomFieldInputValue(
        buildDefinition({ field_type: "integer" }),
        "42",
      ),
    ).toBe(42);
    expect(
      parseCustomFieldInputValue(
        buildDefinition({ field_type: "boolean" }),
        "false",
      ),
    ).toBe(false);
    expect(
      parseCustomFieldInputValue(
        buildDefinition({ field_type: "json" }),
        '{"a":1}',
      ),
    ).toEqual({ a: 1 });
  });

  it("handles visibility and canonicalization", () => {
    expect(
      isCustomFieldVisible(
        buildDefinition({ ui_visibility: "hidden" }),
        "value",
      ),
    ).toBe(false);
    expect(
      isCustomFieldVisible(buildDefinition({ ui_visibility: "if_set" }), ""),
    ).toBe(false);
    expect(canonicalizeCustomFieldValues({ b: 2, a: { z: 1, y: 2 } })).toBe(
      canonicalizeCustomFieldValues({ a: { y: 2, z: 1 }, b: 2 }),
    );
  });

  it("renders url detail values as links", () => {
    const definition = buildDefinition({
      field_type: "url",
      field_key: "website",
    });
    const node = formatCustomFieldDetailValue(
      definition,
      "https://example.com",
    );
    render(<>{node}</>);

    expect(
      screen.getByRole("link", { name: /https:\/\/example.com/i }),
    ).toHaveAttribute("href", "https://example.com/");
  });
});
