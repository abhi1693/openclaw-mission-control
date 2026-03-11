"use client";

import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export function GlobalLoader() {
  const [mounted, setMounted] = useState(false);
  const fetchingCount = useIsFetching({
    predicate: (query) =>
      query.state.fetchStatus === "fetching" && query.state.data === undefined,
  });
  const mutatingCount = useIsMutating();
  const visible = mounted && fetchingCount + mutatingCount > 0;

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <div
      data-cy="global-loader"
      className={`pointer-events-none fixed inset-x-0 top-0 z-[120] h-1 transition-opacity duration-200 ${
        visible ? "opacity-100" : "opacity-0"
      }`}
      aria-hidden={!visible}
      data-state={visible ? "visible" : "hidden"}
      role="status"
    >
      <div className="h-full w-full overflow-hidden bg-[var(--accent-soft)]">
        <div className="h-full w-full animate-progress-shimmer bg-[linear-gradient(90deg,transparent_0%,var(--accent)_50%,transparent_100%)]" />
      </div>
      <span className="sr-only">Loading</span>
    </div>
  );
}
