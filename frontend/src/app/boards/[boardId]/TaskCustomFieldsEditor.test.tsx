import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TaskCustomFieldDefinitionRead } from "@/api/generated/model";
import { TaskCustomFieldsEditor } from "./TaskCustomFieldsEditor";

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

describe("TaskCustomFieldsEditor", () => {
  it("renders loading and empty states", () => {
    const { rerender } = render(
      <TaskCustomFieldsEditor
        definitions={[]}
        values={{}}
        setValues={vi.fn()}
        isLoading
        disabled={false}
      />,
    );

    expect(screen.getByText("Loading custom fields…")).toBeInTheDocument();

    rerender(
      <TaskCustomFieldsEditor
        definitions={[]}
        values={{}}
        setValues={vi.fn()}
        isLoading={false}
        disabled={false}
      />,
    );

    expect(
      screen.getByText("No custom fields configured for this board."),
    ).toBeInTheDocument();
  });

  it("updates field values and respects visibility rules", () => {
    const setValues = vi.fn();
    render(
      <TaskCustomFieldsEditor
        definitions={[
          buildDefinition({
            field_key: "hidden_if_unset",
            ui_visibility: "if_set",
          }),
          buildDefinition({ id: "field-2", field_key: "client_name" }),
        ]}
        values={{}}
        setValues={setValues}
        isLoading={false}
        disabled={false}
      />,
    );

    expect(screen.queryByText("hidden_if_unset")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Acme Corp" },
    });

    const updater = setValues.mock.calls.at(-1)?.[0] as (
      prev: Record<string, unknown>,
    ) => Record<string, unknown>;
    expect(updater({})).toEqual({ client_name: "Acme Corp" });
  });
});
