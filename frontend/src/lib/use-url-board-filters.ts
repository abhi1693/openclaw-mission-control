import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  ALL_FILTER_KEYS,
  type AllFilterKey,
  type TaskBoardFilterValues,
} from "@/components/organisms/TaskBoardFilters";

// Set for O(1) membership checks.
const VALID_FILTER_KEYS = new Set<string>(ALL_FILTER_KEYS);

/**
 * Parse URL search params into {@link TaskBoardFilterValues}.
 *
 * Only recognised filter keys are extracted; unknown or empty values are
 * silently ignored so invalid URLs never cause errors.
 */
const parseFiltersFromSearch = (search: string): TaskBoardFilterValues => {
  const params = new URLSearchParams(search);
  const filters: TaskBoardFilterValues = {};
  for (const [key, value] of params.entries()) {
    if (!VALID_FILTER_KEYS.has(key)) continue;
    const trimmed = value.trim();
    if (trimmed.length === 0) continue;
    filters[key as AllFilterKey] = trimmed;
  }
  return filters;
};

/**
 * Apply filter values onto a {@link URLSearchParams} instance, preserving
 * all other (non-filter) params.
 */
const applyFiltersToParams = (
  base: URLSearchParams,
  filters: TaskBoardFilterValues,
): URLSearchParams => {
  const next = new URLSearchParams(base);
  // Remove all filter keys first.
  for (const key of ALL_FILTER_KEYS) {
    next.delete(key);
  }
  // Then set active ones.
  for (const key of ALL_FILTER_KEYS) {
    const value = filters[key];
    if (value && value.trim().length > 0) {
      next.set(key, value.trim());
    }
  }
  return next;
};

type UseUrlBoardFiltersOptions = {
  /**
   * Optional set of known-valid values per filter key.  When provided, URL
   * param values that are not in the set are silently discarded (AC-4).
   *
   * If a key is absent from the map, any non-empty value is accepted.
   */
  allowedValues?: Partial<Record<AllFilterKey, Set<string>>>;
};

type UseUrlBoardFiltersResult = {
  /** Current filters (derived from URL). */
  filters: TaskBoardFilterValues;
  /** Replace the full filter state (updates URL). */
  setFilters: (next: TaskBoardFilterValues) => void;
};

/**
 * Bi-directional sync between {@link TaskBoardFilterValues} and URL query
 * params.
 *
 * Mirrors the approach used by {@link useUrlSorting}: state is derived from
 * `window.location.search` stored in React state, updated via
 * `router.replace` with `scroll: false`, and kept in sync with browser
 * back/forward via `popstate`.
 */
export function useUrlBoardFilters(
  options: UseUrlBoardFiltersOptions = {},
): UseUrlBoardFiltersResult {
  const router = useRouter();
  const pathname = usePathname();
  const { allowedValues } = options;

  // Mirror of window.location.search (without leading '?').
  const [searchString, setSearchString] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.location.search.replace(/^\?/, "");
  });

  // Keep searchString in sync with popstate (back/forward).
  useEffect(() => {
    const sync = () => {
      setSearchString(window.location.search.replace(/^\?/, ""));
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [pathname]);

  // Derive filters from the search string, validating against allowedValues.
  const filters = useMemo(() => {
    const raw = parseFiltersFromSearch(searchString);
    if (!allowedValues) return raw;
    const validated: TaskBoardFilterValues = {};
    for (const key of ALL_FILTER_KEYS) {
      const value = raw[key];
      if (!value) continue;
      const allowed = allowedValues[key];
      if (allowed && !allowed.has(value)) continue; // AC-4: ignore invalid
      validated[key] = value;
    }
    return validated;
  }, [allowedValues, searchString]);

  const setFilters = useCallback(
    (next: TaskBoardFilterValues) => {
      const base = new URLSearchParams(searchString);
      const nextParams = applyFiltersToParams(base, next);
      const query = nextParams.toString();
      setSearchString(query);
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [pathname, router, searchString],
  );

  return { filters, setFilters };
}
