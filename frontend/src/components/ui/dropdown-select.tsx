"use client";

import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

export type DropdownSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
  icon?: React.ElementType<{ className?: string }>;
  iconClassName?: string;
};

type DropdownSelectProps = {
  value?: string;
  onValueChange: (value: string) => void;
  options: DropdownSelectOption[];
  placeholder?: string;
  ariaLabel: string;
  disabled?: boolean;
  triggerClassName?: string;
  contentClassName?: string;
  itemClassName?: string;
  searchEnabled?: boolean;
  searchPlaceholder?: string;
  emptyMessage?: string;
};

/**
 * Derive a human-friendly trigger placeholder from an accessible `ariaLabel`.
 *
 * Keeps placeholder strings consistent even when callers only provide aria text.
 */
const resolvePlaceholder = (ariaLabel: string, placeholder?: string) => {
  if (placeholder) {
    return placeholder;
  }
  const trimmed = ariaLabel.trim();
  if (!trimmed) {
    return "Select an option";
  }
  return trimmed.endsWith("...") ? trimmed : `${trimmed}...`;
};

/**
 * Search input placeholder derived from `ariaLabel`.
 *
 * Example: ariaLabel="Select agent" -> "Search agent...".
 */
const resolveSearchPlaceholder = (
  ariaLabel: string,
  searchPlaceholder?: string,
) => {
  if (searchPlaceholder) {
    return searchPlaceholder;
  }
  const cleaned = ariaLabel.replace(/^select\\s+/i, "").trim();
  if (!cleaned) {
    return "Search...";
  }
  const value = `Search ${cleaned}`;
  return value.endsWith("...") ? value : `${value}...`;
};

export default function DropdownSelect({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  disabled = false,
  triggerClassName,
  contentClassName,
  itemClassName,
  searchEnabled = true,
  searchPlaceholder,
  emptyMessage,
}: DropdownSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const selectedOption = options.find((option) => option.value === value);
  const resolvedPlaceholder = resolvePlaceholder(ariaLabel, placeholder);
  const triggerLabel = selectedOption?.label ?? value ?? "";
  const SelectedIcon = selectedOption?.icon;
  const selectedIconClassName = selectedOption?.iconClassName;
  const showPlaceholder = !triggerLabel;
  const resolvedSearchPlaceholder = searchEnabled
    ? resolveSearchPlaceholder(ariaLabel, searchPlaceholder)
    : "";

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setSearchValue("");
    }
  };

  const handleSelect = (nextValue: string) => {
    if (nextValue !== value) {
      onValueChange(nextValue);
    }
    handleOpenChange(false);
  };

  // Reset list scroll when opening or refining search so results start at the top.
  React.useEffect(() => {
    if (!open) {
      return;
    }
    if (listRef.current) {
      listRef.current.scrollTop = 0;
    }
  }, [open, searchValue]);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-haspopup="listbox"
          disabled={disabled}
          className={cn(
            "inline-flex h-10 w-auto cursor-pointer items-center justify-between gap-2 rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-sm font-medium text-[var(--text)] shadow-[var(--shadow-card)] transition-colors hover:bg-[var(--surface-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--input-focus-ring)] focus:border-transparent disabled:cursor-not-allowed disabled:opacity-50",
            open && "bg-[var(--surface-muted)]",
            triggerClassName,
          )}
        >
          <span
            className={cn(
              "flex min-w-0 items-center gap-2 truncate",
              showPlaceholder && "text-[var(--text-muted)]",
            )}
          >
            {SelectedIcon ? (
              <SelectedIcon
                className={cn("h-4 w-4 text-[var(--text-muted)]", selectedIconClassName)}
              />
            ) : null}
            <span className="truncate">
              {showPlaceholder ? resolvedPlaceholder : triggerLabel}
            </span>
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-[var(--text-quiet)] transition-transform",
              open && "rotate-180",
            )}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className={cn(
          "w-[var(--radix-popover-trigger-width)] min-w-[12rem] overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface)] p-0 text-[var(--text)] shadow-[var(--shadow-panel)]",
          contentClassName,
        )}
      >
        <Command label={ariaLabel} className="w-full">
          {searchEnabled ? (
            <CommandInput
              value={searchValue}
              onValueChange={setSearchValue}
              placeholder={resolvedSearchPlaceholder}
              autoFocus
              className="text-sm"
            />
          ) : null}
          <CommandList ref={listRef} className="max-h-64 p-1">
            <CommandEmpty className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
              {emptyMessage ?? "No results found."}
            </CommandEmpty>
            {options.map((option) => {
              const isSelected = value === option.value;
              const OptionIcon = option.icon;
              return (
                <CommandItem
                  key={option.value}
                  value={option.value}
                  keywords={[option.label, option.value]}
                  disabled={option.disabled}
                  onSelect={handleSelect}
                  className={cn(
                    "flex items-center justify-between gap-2 rounded-lg px-4 py-3 text-sm text-[var(--text)] transition-colors data-[selected=true]:bg-[var(--surface-muted)] data-[selected=true]:text-[var(--text)]",
                    isSelected && "font-semibold",
                    !isSelected && "hover:bg-[var(--surface-muted)]",
                    itemClassName,
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {OptionIcon ? (
                      <OptionIcon
                        className={cn(
                          "h-4 w-4",
                          isSelected ? "text-[var(--text)]" : "text-[var(--text-muted)]",
                          option.iconClassName,
                        )}
                      />
                    ) : null}
                    <span className="truncate font-medium">{option.label}</span>
                  </span>
                  {isSelected ? (
                    <Check className="h-4 w-4 text-[var(--text-quiet)]" />
                  ) : null}
                </CommandItem>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
