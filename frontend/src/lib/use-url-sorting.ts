import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  type OnChangeFn,
  type SortingState,
  functionalUpdate,
} from "@tanstack/react-table";

const SORT_NONE_SENTINEL = "none";

type UseUrlSortingOptions = {
  allowedColumnIds: string[];
  defaultSorting?: SortingState;
  paramPrefix?: string;
};

type UseUrlSortingResult = {
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
};

const resolveSortParam = (paramPrefix?: string) =>
  paramPrefix ? `${paramPrefix}_sort` : "sort";

const resolveDirectionParam = (paramPrefix?: string) =>
  paramPrefix ? `${paramPrefix}_dir` : "dir";

const normalizeSorting = (
  value: SortingState,
  allowedColumnIds: Set<string>,
): SortingState => {
  for (const sort of value) {
    if (!allowedColumnIds.has(sort.id)) continue;
    return [{ id: sort.id, desc: Boolean(sort.desc) }];
  }
  return [];
};

const isSameSorting = (a: SortingState, b: SortingState) => {
  if (a.length !== b.length) return false;
  if (!a.length) return true;
  return a[0]?.id === b[0]?.id && Boolean(a[0]?.desc) === Boolean(b[0]?.desc);
};

export function useUrlSorting({
  allowedColumnIds,
  defaultSorting = [],
  paramPrefix,
}: UseUrlSortingOptions): UseUrlSortingResult {
  const router = useRouter();
  const pathname = usePathname();
  const [searchParamsString, setSearchParamsString] = useState(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return window.location.search.replace(/^\?/, "");
  });

  const allowedSet = useMemo(
    () => new Set(allowedColumnIds),
    [allowedColumnIds],
  );
  const normalizedDefaultSorting = useMemo(
    () => normalizeSorting(defaultSorting, allowedSet),
    [defaultSorting, allowedSet],
  );

  const sortParam = resolveSortParam(paramPrefix);
  const directionParam = resolveDirectionParam(paramPrefix);

  useEffect(() => {
    const syncFromLocation = () => {
      setSearchParamsString(window.location.search.replace(/^\?/, ""));
    };

    syncFromLocation();
    window.addEventListener("popstate", syncFromLocation);

    return () => {
      window.removeEventListener("popstate", syncFromLocation);
    };
  }, [pathname]);

  const sorting = useMemo(() => {
    const searchParams = new URLSearchParams(searchParamsString);
    const sortValue = searchParams.get(sortParam);

    if (!sortValue) {
      return normalizedDefaultSorting;
    }
    if (sortValue === SORT_NONE_SENTINEL) {
      return [];
    }
    if (!allowedSet.has(sortValue)) {
      return normalizedDefaultSorting;
    }

    return [
      {
        id: sortValue,
        desc: searchParams.get(directionParam) === "desc",
      },
    ];
  }, [
    allowedSet,
    directionParam,
    normalizedDefaultSorting,
    searchParamsString,
    sortParam,
  ]);

  const onSortingChange = useCallback<OnChangeFn<SortingState>>(
    (updater) => {
      const nextSorting = normalizeSorting(
        functionalUpdate(updater, sorting),
        allowedSet,
      );

      if (isSameSorting(nextSorting, sorting)) {
        return;
      }

      const nextParams = new URLSearchParams(searchParamsString);

      if (nextSorting.length === 0) {
        nextParams.set(sortParam, SORT_NONE_SENTINEL);
        nextParams.delete(directionParam);
      } else if (isSameSorting(nextSorting, normalizedDefaultSorting)) {
        nextParams.delete(sortParam);
        nextParams.delete(directionParam);
      } else {
        const [primary] = nextSorting;
        nextParams.set(sortParam, primary.id);
        nextParams.set(directionParam, primary.desc ? "desc" : "asc");
      }

      const query = nextParams.toString();
      setSearchParamsString(query);
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [
      allowedSet,
      directionParam,
      normalizedDefaultSorting,
      pathname,
      router,
      searchParamsString,
      sortParam,
      sorting,
    ],
  );

  return { sorting, onSortingChange };
}
