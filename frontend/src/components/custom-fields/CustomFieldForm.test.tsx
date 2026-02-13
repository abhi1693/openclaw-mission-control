import type React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardRead } from "@/api/generated/model";
import { CustomFieldForm } from "./CustomFieldForm";
import { DEFAULT_CUSTOM_FIELD_FORM_STATE } from "./custom-field-form-types";

vi.mock("next/link", () => {
  type LinkProps = React.PropsWithChildren<{
    href: string | { pathname?: string };
  }> &
    Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

  return {
    default: ({ href, children, ...props }: LinkProps) => (
      <a href={typeof href === "string" ? href : "#"} {...props}>
        {children}
      </a>
    ),
  };
});

const buildBoard = (overrides: Partial<BoardRead> = {}): BoardRead => ({
  id: "board-1",
  name: "Operations",
  slug: "operations",
  description: "Operations board",
  organization_id: "org-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("CustomFieldForm", () => {
  it("validates board selection on create", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <CustomFieldForm
        mode="create"
        initialFormState={DEFAULT_CUSTOM_FIELD_FORM_STATE}
        boards={[buildBoard()]}
        boardsLoading={false}
        boardsError={null}
        isSubmitting={false}
        submitLabel="Create field"
        submittingLabel="Creating..."
        submitErrorFallback="Failed to create custom field."
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByLabelText("Field key"), {
      target: { value: "client_name" },
    });
    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "Client Name" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create field" }));

    await waitFor(() => {
      expect(
        screen.getByText("Select at least one board."),
      ).toBeInTheDocument();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits normalized values on create", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <CustomFieldForm
        mode="create"
        initialFormState={DEFAULT_CUSTOM_FIELD_FORM_STATE}
        boards={[buildBoard()]}
        boardsLoading={false}
        boardsError={null}
        isSubmitting={false}
        submitLabel="Create field"
        submittingLabel="Creating..."
        submitErrorFallback="Failed to create custom field."
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByLabelText("Field key"), {
      target: { value: "  client_name " },
    });
    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: " Client Name " },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /operations/i }));
    fireEvent.click(screen.getByRole("button", { name: "Create field" }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        fieldKey: "client_name",
        label: "Client Name",
        fieldType: "text",
        uiVisibility: "always",
        validationRegex: null,
        description: null,
        required: false,
        defaultValue: null,
        boardIds: ["board-1"],
      });
    });
  });

  it("locks field key in edit mode", () => {
    render(
      <CustomFieldForm
        mode="edit"
        initialFormState={{
          ...DEFAULT_CUSTOM_FIELD_FORM_STATE,
          fieldKey: "client_name",
          label: "Client Name",
        }}
        initialBoardIds={["board-1"]}
        boards={[buildBoard()]}
        boardsLoading={false}
        boardsError={null}
        isSubmitting={false}
        submitLabel="Save changes"
        submittingLabel="Saving..."
        submitErrorFallback="Failed to update custom field."
        onSubmit={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByDisplayValue("client_name")).toBeDisabled();
    expect(
      screen.getByText("Field key cannot be changed after creation."),
    ).toBeInTheDocument();
  });
});
