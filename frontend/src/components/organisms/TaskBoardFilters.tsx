"use client";

import { memo, useMemo } from "react";
import { X } from "lucide-react";

import DropdownSelect from "@/components/ui/dropdown-select";
import type { DropdownSelectOption } from "@/components/ui/dropdown-select";
import { cn } from "@/lib/utils";

/** Filter keys matching custom field field_key values. */
export const FILTER_FIELD_KEYS = ["sprint", "type", "epic"] as const;
export type FilterFieldKey = (typeof FILTER_FIELD_KEYS)[number];

/** Filter keys for top-level task properties (assignee, priority, tag). */
export const TASK_PROP_FILTER_KEYS = [
  "assignee",
  "priority",
  "tag",
] as const;
export type TaskPropFilterKey = (typeof TASK_PROP_FILTER_KEYS)[number];

export type AllFilterKey = FilterFieldKey | TaskPropFilterKey;

export type TaskBoardFilterValues = Partial<Record<AllFilterKey, string>>;

export const ALL_FILTER_KEYS: readonly AllFilterKey[] = [
  ...TASK_PROP_FILTER_KEYS,
  ...FILTER_FIELD_KEYS,
];

type TaskTag = { id: string; name: string; color: string };

type FilterableTask = {
  custom_field_values?: Record<string, unknown> | null;
  assignee?: string | null;
  priority?: string | null;
  tags?: TaskTag[];
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract unique option values for a given custom field key across all tasks.
 */
const extractFieldOptions = (
  tasks: FilterableTask[],
  fieldKey: string,
): DropdownSelectOption[] => {
  const values = new Set<string>();
  for (const task of tasks) {
    const raw = task.custom_field_values?.[fieldKey];
    if (raw === null || raw === undefined) continue;
    const text = typeof raw === "string" ? raw.trim() : String(raw).trim();
    if (text.length > 0) {
      values.add(text);
    }
  }
  return [...values]
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value, label: value }));
};

/**
 * Extract unique assignee values from tasks.
 */
const extractAssigneeOptions = (
  tasks: FilterableTask[],
): DropdownSelectOption[] => {
  const values = new Set<string>();
  for (const task of tasks) {
    const assignee = task.assignee;
    if (assignee && assignee.trim().length > 0) {
      values.add(assignee.trim());
    }
  }
  return [...values]
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value, label: value }));
};

/**
 * Extract unique priority values from tasks.
 */
const extractPriorityOptions = (
  tasks: FilterableTask[],
): DropdownSelectOption[] => {
  const order = ["critical", "high", "medium", "low"];
  const values = new Set<string>();
  for (const task of tasks) {
    const priority = task.priority;
    if (priority && priority.trim().length > 0) {
      values.add(priority.trim());
    }
  }
  return [...values]
    .sort((a, b) => {
      const ai = order.indexOf(a.toLowerCase());
      const bi = order.indexOf(b.toLowerCase());
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    })
    .map((value) => ({
      value,
      label: value.charAt(0).toUpperCase() + value.slice(1),
    }));
};

/**
 * Extract unique tag values from tasks.
 */
const extractTagOptions = (
  tasks: FilterableTask[],
): DropdownSelectOption[] => {
  const seen = new Map<string, string>(); // name -> name (preserving case)
  for (const task of tasks) {
    if (!task.tags) continue;
    for (const tag of task.tags) {
      if (tag.name && tag.name.trim().length > 0) {
        seen.set(tag.name.trim(), tag.name.trim());
      }
    }
  }
  return [...seen.values()]
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value, label: value }));
};

const FILTER_LABELS: Record<AllFilterKey, string> = {
  assignee: "Assignee",
  priority: "Priority",
  tag: "Tag",
  sprint: "Sprint",
  type: "Type",
  epic: "Epic",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type TaskBoardFiltersProps = {
  /** All tasks (unfiltered) used to derive dropdown options. */
  tasks: FilterableTask[];
  /** Currently applied filter values. */
  filters: TaskBoardFilterValues;
  /** Called when any filter value changes. */
  onFiltersChange: (next: TaskBoardFilterValues) => void;
};

/**
 * Kanban board filter bar with Assignee / Priority / Tag / Sprint / Type / Epic
 * dropdowns.
 *
 * Designed as a self-contained component so it can sit alongside `TaskBoard`
 * without modifying it, minimising merge conflicts with parallel kanban work
 * (S33-8).
 */
export const TaskBoardFilters = memo(function TaskBoardFilters({
  tasks,
  filters,
  onFiltersChange,
}: TaskBoardFiltersProps) {
  // --- task-property options ---
  const assigneeOptions = useMemo(
    () => extractAssigneeOptions(tasks),
    [tasks],
  );
  const priorityOptions = useMemo(
    () => extractPriorityOptions(tasks),
    [tasks],
  );
  const tagOptions = useMemo(() => extractTagOptions(tasks), [tasks]);

  // --- custom-field options ---
  const sprintOptions = useMemo(
    () => extractFieldOptions(tasks, "sprint"),
    [tasks],
  );
  const typeOptions = useMemo(
    () => extractFieldOptions(tasks, "type"),
    [tasks],
  );
  const epicOptions = useMemo(
    () => extractFieldOptions(tasks, "epic"),
    [tasks],
  );

  const optionsMap: Record<AllFilterKey, DropdownSelectOption[]> = useMemo(
    () => ({
      assignee: assigneeOptions,
      priority: priorityOptions,
      tag: tagOptions,
      sprint: sprintOptions,
      type: typeOptions,
      epic: epicOptions,
    }),
    [
      assigneeOptions,
      priorityOptions,
      tagOptions,
      sprintOptions,
      typeOptions,
      epicOptions,
    ],
  );

  const activeFilterCount = ALL_FILTER_KEYS.filter(
    (key) => !!filters[key],
  ).length;

  const handleChange = (key: AllFilterKey, value: string) => {
    // If the same value is selected again, treat it as deselect.
    const next = { ...filters };
    if (next[key] === value) {
      delete next[key];
    } else {
      next[key] = value;
    }
    onFiltersChange(next);
  };

  const handleClearAll = () => {
    onFiltersChange({});
  };

  // Don't render the filter bar when there are no tasks at all.
  if (tasks.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-3"
      role="group"
      aria-label="Task board filters"
    >
      {ALL_FILTER_KEYS.map((key) => {
        const options = optionsMap[key];

        // Always render task-property filters (assignee, priority, tag) even when empty
        // so users always see the 3 core filters. Only hide custom-field filters
        // (sprint, type, epic) when they have no configured values yet.
        const isTaskPropFilter = (TASK_PROP_FILTER_KEYS as readonly string[]).includes(key);
        if (!isTaskPropFilter && options.length === 0) return null;

        const allOption: DropdownSelectOption = {
          value: "__all__",
          label: `All ${FILTER_LABELS[key]}s`,
        };
        const dropdownOptions = [allOption, ...options];

        return (
          <DropdownSelect
            key={key}
            value={filters[key] ?? "__all__"}
            onValueChange={(value) => {
              if (value === "__all__") {
                const next = { ...filters };
                delete next[key];
                onFiltersChange(next);
              } else {
                handleChange(key, value);
              }
            }}
            options={dropdownOptions}
            ariaLabel={`Filter by ${FILTER_LABELS[key]}`}
            placeholder={FILTER_LABELS[key]}
            searchEnabled={options.length > 6}
            disabled={options.length === 0}
            triggerClassName={cn(
              "h-9 text-sm",
              filters[key] &&
                "border-slate-900 bg-slate-900 text-white hover:bg-slate-800",
              options.length === 0 && "opacity-50 cursor-not-allowed",
            )}
          />
        );
      })}

      {activeFilterCount > 0 ? (
        <button
          type="button"
          onClick={handleClearAll}
          className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-400"
          aria-label="Clear all filters"
        >
          <X className="h-3.5 w-3.5" />
          <span>Clear all</span>
          <span
            className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700"
            aria-label={`${activeFilterCount} active filters`}
          >
            {activeFilterCount}
          </span>
        </button>
      ) : null}
    </div>
  );
});

TaskBoardFilters.displayName = "TaskBoardFilters";

// ---------------------------------------------------------------------------
// Filter logic (pure function, usable outside the component)
// ---------------------------------------------------------------------------

/**
 * Apply AND-combined filters to a list of tasks.
 *
 * Handles both custom-field filters (sprint, type, epic) and top-level
 * task-property filters (assignee, priority, tag).
 */
export const applyTaskBoardFilters = <
  T extends FilterableTask,
>(
  tasks: T[],
  filters: TaskBoardFilterValues,
): T[] => {
  const activeEntries = ALL_FILTER_KEYS.filter((key) => !!filters[key]).map(
    (key) => [key, filters[key] as string] as const,
  );

  if (activeEntries.length === 0) return tasks;

  return tasks.filter((task) =>
    activeEntries.every(([key, expected]) => {
      // Top-level property filters
      if (key === "assignee") {
        return (task.assignee ?? "").trim() === expected;
      }
      if (key === "priority") {
        return (task.priority ?? "").trim() === expected;
      }
      if (key === "tag") {
        return task.tags?.some((t) => t.name.trim() === expected) ?? false;
      }

      // Custom field filters (sprint, type, epic)
      const raw = task.custom_field_values?.[key];
      if (raw === null || raw === undefined) return false;
      const text = typeof raw === "string" ? raw.trim() : String(raw).trim();
      return text === expected;
    }),
  );
};
