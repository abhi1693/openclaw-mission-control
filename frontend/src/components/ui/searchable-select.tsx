"use client";

import DropdownSelect, {
  type DropdownSelectOption,
} from "@/components/ui/dropdown-select";
import { cn } from "@/lib/utils";

export type SearchableSelectOption = DropdownSelectOption;

type SearchableSelectProps = {
  value?: string;
  onValueChange: (value: string) => void;
  options: SearchableSelectOption[];
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

const baseTriggerClassName =
  "w-auto h-auto rounded-xl border-2 border-gray-200 bg-white px-4 py-3 text-left text-sm font-semibold text-gray-700 shadow-sm transition-all duration-200 hover:border-gray-300 focus:border-gray-900 focus:ring-4 focus:ring-gray-100";
const baseContentClassName =
  "rounded-xl border-2 border-gray-200 bg-white shadow-xl";
const baseItemClassName =
  "px-4 py-3 text-sm text-gray-700 transition-colors data-[selected=true]:bg-gray-50 data-[selected=true]:text-gray-900 data-[selected=true]:font-semibold hover:bg-gray-50";

export default function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  disabled = false,
  triggerClassName,
  contentClassName,
  itemClassName,
  searchEnabled,
  searchPlaceholder,
  emptyMessage,
}: SearchableSelectProps) {
  return (
    <DropdownSelect
      value={value}
      onValueChange={onValueChange}
      options={options}
      placeholder={placeholder}
      ariaLabel={ariaLabel}
      disabled={disabled}
      triggerClassName={cn(baseTriggerClassName, triggerClassName)}
      contentClassName={cn(baseContentClassName, contentClassName)}
      itemClassName={cn(baseItemClassName, itemClassName)}
      searchEnabled={searchEnabled}
      searchPlaceholder={searchPlaceholder}
      emptyMessage={emptyMessage}
    />
  );
}
