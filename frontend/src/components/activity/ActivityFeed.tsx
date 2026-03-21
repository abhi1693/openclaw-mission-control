import type { ReactNode } from "react";

type FeedItem = {
  id: string;
};

type ActivityFeedProps<TItem extends FeedItem> = {
  isLoading: boolean;
  errorMessage?: string | null;
  items: TItem[];
  renderItem: (item: TItem) => ReactNode;
};

export function ActivityFeed<TItem extends FeedItem>({
  isLoading,
  errorMessage,
  items,
  renderItem,
}: ActivityFeedProps<TItem>) {
  if (isLoading && items.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">Loading feed…</p>;
  }

  const hasError = errorMessage !== null && errorMessage !== undefined;
  if (hasError) {
    return (
      <div className="surface-card rounded-lg p-4 text-sm text-[var(--text-muted)] shadow-sm">
        {errorMessage || "Unable to load feed."}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="surface-card rounded-xl p-10 text-center">
        <p className="text-sm font-medium text-[var(--text)]">
          Waiting for new activity…
        </p>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          When updates happen, they will show up here.
        </p>
      </div>
    );
  }

  return <div className="space-y-4">{items.map(renderItem)}</div>;
}
