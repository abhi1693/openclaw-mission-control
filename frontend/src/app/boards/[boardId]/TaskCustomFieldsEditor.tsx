import type { Dispatch, SetStateAction } from "react";

import type { TaskCustomFieldDefinitionRead } from "@/api/generated/model";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import {
  customFieldInputText,
  isCustomFieldVisible,
  parseCustomFieldInputValue,
  type TaskCustomFieldValues,
} from "./custom-field-utils";

type TaskCustomFieldsEditorProps = {
  definitions: TaskCustomFieldDefinitionRead[];
  values: TaskCustomFieldValues;
  setValues: Dispatch<SetStateAction<TaskCustomFieldValues>>;
  isLoading: boolean;
  disabled: boolean;
  loadingMessage?: string;
  emptyMessage?: string;
};

export function TaskCustomFieldsEditor({
  definitions,
  values,
  setValues,
  isLoading,
  disabled,
  loadingMessage = "Loading custom fields…",
  emptyMessage = "No custom fields configured for this board.",
}: TaskCustomFieldsEditorProps) {
  if (isLoading)
    return <p className="text-xs text-slate-500">{loadingMessage}</p>;
  if (definitions.length === 0) {
    return <p className="text-xs text-slate-500">{emptyMessage}</p>;
  }

  return (
    <div className="space-y-3">
      {definitions.map((definition) => {
        const fieldValue = values[definition.field_key];
        if (!isCustomFieldVisible(definition, fieldValue)) return null;

        return (
          <div key={definition.id} className="space-y-1">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {definition.label || definition.field_key}
              {definition.required === true ? (
                <span className="ml-1 text-rose-600">*</span>
              ) : null}
            </label>

            {definition.field_type === "boolean" ? (
              <Select
                value={
                  fieldValue === true
                    ? "true"
                    : fieldValue === false
                      ? "false"
                      : "unset"
                }
                onValueChange={(value) =>
                  setValues((prev) => ({
                    ...prev,
                    [definition.field_key]:
                      value === "unset" ? null : value === "true",
                  }))
                }
                disabled={disabled}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Optional" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="unset">Optional</SelectItem>
                  <SelectItem value="true">True</SelectItem>
                  <SelectItem value="false">False</SelectItem>
                </SelectContent>
              </Select>
            ) : definition.field_type === "text_long" ||
              definition.field_type === "json" ? (
              <Textarea
                value={customFieldInputText(fieldValue)}
                onChange={(event) => {
                  const nextFieldValue = parseCustomFieldInputValue(
                    definition,
                    event.target.value,
                  );
                  setValues((prev) => ({
                    ...prev,
                    [definition.field_key]: nextFieldValue,
                  }));
                }}
                placeholder={
                  definition.default_value !== undefined &&
                  definition.default_value !== null
                    ? `Default: ${customFieldInputText(definition.default_value)}`
                    : "Optional"
                }
                rows={definition.field_type === "text_long" ? 3 : 4}
                disabled={disabled}
              />
            ) : (
              <Input
                type={
                  definition.field_type === "integer" ||
                  definition.field_type === "decimal"
                    ? "number"
                    : definition.field_type === "date"
                      ? "date"
                      : definition.field_type === "date_time"
                        ? "datetime-local"
                        : definition.field_type === "url"
                          ? "url"
                          : "text"
                }
                step={definition.field_type === "decimal" ? "any" : undefined}
                value={customFieldInputText(fieldValue)}
                onChange={(event) => {
                  const nextFieldValue = parseCustomFieldInputValue(
                    definition,
                    event.target.value,
                  );
                  setValues((prev) => ({
                    ...prev,
                    [definition.field_key]: nextFieldValue,
                  }));
                }}
                placeholder={
                  definition.default_value !== undefined &&
                  definition.default_value !== null
                    ? `Default: ${customFieldInputText(definition.default_value)}`
                    : "Optional"
                }
                disabled={disabled}
              />
            )}

            {definition.description ? (
              <p className="text-xs text-slate-500">{definition.description}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
